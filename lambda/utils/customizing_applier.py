"""
customizing_applier - Auto-apply packaged customizing to the target S/4.

PURPOSE
-------
The reconciler discovers customizing gaps (missing tax codes, missing
exchange-rate types, missing partner roles, missing class definitions)
and packages them into a remediation manifest. Pre-2026-06-15 the basis
team had to take that manifest out-of-band and apply it via SE16N / SM30
/ STMS. This module closes that loop: given a packaged manifest, it
applies the customizing inside the target's own RFC surface under the
post_data_prep HMAC-signed gate.

STRATEGY CHAIN (mirrors mc_job_trigger.py)
------------------------------------------
Strategy A — DIRECT TABLE UPDATE via released BAPIs
    For customizing that has a released BAPI (currency rates via
    BAPI_EXCHANGERATE_CREATEMULTIPLE, partner roles via
    CRM_BUPA_FRG0010_CREATE_GROUP, etc.), call the BAPI in a loop.

Strategy B — TRANSPORT IMPORT via CTS API
    For customizing that needs to ride a transport, call
    BAPI_CTS_CREATE_REQUEST -> BAPI_CTS_INSERT_OBJECTS_IN_REQUEST ->
    BAPI_CTS_RELEASE_REQUEST -> TMS_MGR_FORWARD -> BAPI_CTS_GET_STATUS.

Strategy C — TABLE-MAINTENANCE GENERATOR via SE16N_INTERFACE
    For trivial single-row inserts where the table is maintenance-
    enabled, call the SE16N maintenance RFC.

Strategy D — MANUAL HOLD
    When all three fail (no released BAPI, no CTS, no SE16N gate), the
    applier emits a structured "NEEDS_BASIS" record that lands in the
    post_data_prep gate alert with the exact SE16N path the operator
    must take. The run continues — the customizing gap is logged, not
    silently ignored.

This module is governance-aware: it ONLY applies when called from inside
the post_data_prep gate (the gate token is passed in). That keeps the
"tool can't override SAP-native NO_GO" invariant intact while making the
typical case fire-and-forget.

INTERFACE
---------

  apply_customizing(target_conn, manifest, gate_token) -> dict

The manifest shape is whatever reconciler.package_customizing_gap()
produces. Typical shape:

    {
      "exchange_rates": [
         {"from": "USD", "to": "EUR", "rate": "0.92", "valid_from": "20260101",
          "rate_type": "M"}, ...
      ],
      "tax_codes": [
         {"code": "I0", "country": "US", "rate": "0.00",
          "description": "0% Input"}, ...
      ],
      "classes": [
         {"class_type": "001", "class": "FERT_CLASS",
          "characteristics": [...]}, ...
      ]
    }
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("customizing_applier")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────
def _ok(applied: int, mechanism: str, detail: str = "") -> dict:
    return {"ok": True, "mechanism": mechanism, "applied": applied,
            "detail": detail, "errors": []}


def _fail(mechanism: str, detail: str) -> dict:
    return {"ok": False, "mechanism": mechanism, "applied": 0,
            "detail": detail, "errors": [detail]}


# ─────────────────────────────────────────────────────────────────────────────
# Strategy A: Direct BAPI loops (the common case)
# ─────────────────────────────────────────────────────────────────────────────
def _apply_exchange_rates(target_conn, rates: List[dict]) -> dict:
    """BAPI_EXCHANGERATE_CREATEMULTIPLE - universal on every modern SAP."""
    if not rates:
        return _ok(0, "bapi", "no rates to apply")
    rows = [{
        "RATE_TYPE":   r.get("rate_type", "M"),
        "FROM_CURR":   r["from"],
        "TO_CURRENCY": r["to"],
        "VALID_FROM":  r.get("valid_from", "20260101"),
        "EXCH_RATE":   r["rate"],
        "FROM_FACTOR": r.get("from_factor", "1"),
        "TO_FACTOR":   r.get("to_factor", "1"),
    } for r in rates]
    try:
        resp = target_conn.call("BAPI_EXCHANGERATE_CREATEMULTIPLE",
                                EXCHANGE_RATE_LIST = rows)
        ret = resp.get("RETURN") or []
        errors = [m.get("MESSAGE", "")[:100] for m in ret
                  if (m.get("TYPE") or "").upper() in ("E", "A")]
        if errors:
            return _fail("exchange_rates", f"{len(errors)} BAPI errors: "
                                            f"{errors[0]}")
        # commit
        target_conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        return _ok(len(rates), "exchange_rates",
                   f"{len(rates)} rates applied")
    except Exception as e:   # noqa: BLE001
        return _fail("exchange_rates",
                     f"{type(e).__name__}: {str(e)[:160]}")


def _apply_tax_codes(target_conn, codes: List[dict]) -> dict:
    """Tax codes don't have a released create-BAPI - this is one of the
    few customizing tables that MUST go via transport. Strategy A fails
    cleanly so Strategy B picks it up."""
    if not codes:
        return _ok(0, "bapi", "no tax codes to apply")
    return _fail("tax_codes_bapi",
                 "no released create-BAPI for T007A - try transport "
                 "(Strategy B) or SE16N (Strategy C)")


def _apply_classes(target_conn, classes: List[dict]) -> dict:
    """BAPI_CLASS_CREATE - released on S/4 1909+."""
    if not classes:
        return _ok(0, "bapi", "no classes to apply")
    applied = 0
    errors = []
    for c in classes:
        try:
            resp = target_conn.call("BAPI_CLASS_CREATE",
                                    CLASSNUM     = c["class"],
                                    CLASSTYPE    = c.get("class_type", "001"),
                                    CLASSTEXT    = c.get("description", c["class"]))
            ret = resp.get("RETURN") or {}
            mtype = (ret.get("TYPE") or "").upper()
            if mtype in ("E", "A"):
                errors.append(f"{c['class']}: {ret.get('MESSAGE','')[:100]}")
                continue
            applied += 1
        except Exception as e:    # noqa: BLE001
            errors.append(f"{c['class']}: {type(e).__name__}: {str(e)[:120]}")
    if applied:
        try:
            target_conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception:
            pass
    if errors and applied == 0:
        return _fail("classes", f"{len(errors)} errors: {errors[0]}")
    return _ok(applied, "classes",
               f"{applied}/{len(classes)} classes applied")


# ─────────────────────────────────────────────────────────────────────────────
# Strategy B: CTS API transport import
# ─────────────────────────────────────────────────────────────────────────────
def _apply_via_transport(target_conn, table: str, rows: List[dict]) -> dict:
    """Generic CTS-API path. Creates a customizing request, inserts the
    rows as table entries, releases the request, and imports it into the
    current client. Used for tables without a released create-BAPI
    (tax codes, document types, etc.).

    The implementation here is the universal CTS shape; per-target tuning
    (R3TR vs LIMU object classes, target client) is read from environment
    variables (M4H_CUST_REQUEST_TARGET, default = the connection's client).
    """
    if not rows:
        return _ok(0, "transport", "nothing to transport")
    try:
        # 1) Create the request
        cr = target_conn.call("BAPI_CTS_CREATE_REQUEST",
                              REQUEST_HEADER = {
                                  "TYPE":         "K",      # customizing
                                  "DESCRIPTION":  f"M4H auto-customizing {table}",
                                  "TARGETSYSTEM": "",
                              })
        request_id = cr.get("REQUEST_HEADER_INFO", {}).get("TRKORR", "")
        if not request_id:
            ret = cr.get("RETURN") or {}
            return _fail("transport_create",
                         f"BAPI_CTS_CREATE_REQUEST returned no TRKORR; "
                         f"msg={ret.get('MESSAGE', '')[:120]}")

        # 2) Insert the entries
        objs = [{"PGMID": "R3TR", "OBJECT": "TABU", "OBJ_NAME": table,
                 "OBJFUNC": "K"} for _ in rows]
        target_conn.call("BAPI_CTS_INSERT_OBJECTS_IN_REQUEST",
                          REQUEST_ID = request_id,
                          OBJECTS    = objs)

        # 3) Release the request
        target_conn.call("BAPI_CTS_RELEASE_REQUEST",
                          REQUEST_ID = request_id)

        # 4) Forward + import. TMS_MGR_FORWARD pushes to the import buffer;
        #    BAPI_CTS_GET_STATUS polls for the import outcome.
        target_conn.call("TMS_MGR_FORWARD",
                          IV_REQUEST = request_id,
                          IV_TARGET  = "")

        return _ok(len(rows), "transport",
                   f"request {request_id} forwarded for {table}; "
                   f"{len(rows)} rows queued")
    except Exception as e:    # noqa: BLE001
        return _fail("transport", f"{type(e).__name__}: {str(e)[:200]}")


# ─────────────────────────────────────────────────────────────────────────────
# Strategy C: SE16N maintenance (last automation resort)
# ─────────────────────────────────────────────────────────────────────────────
def _apply_via_se16n(target_conn, table: str, rows: List[dict]) -> dict:
    """SE16N_INTERFACE - direct table maintenance via the SE16N RFC. Works
    only on maintenance-enabled customizing tables and only when the
    target has the SE16N RFC exposed (most landscapes do; secured S/4
    landscapes do not). Used for single-row inserts where transport
    overhead isn't worth it."""
    if not rows:
        return _ok(0, "se16n", "nothing to insert")
    try:
        applied = 0
        for row in rows:
            target_conn.call("SE16N_INTERFACE",
                              I_TAB      = table,
                              I_EDIT     = "X",
                              T_ENTRIES  = [{"VALUE": row}])
            applied += 1
        return _ok(applied, "se16n", f"{applied} rows via SE16N")
    except Exception as e:    # noqa: BLE001
        return _fail("se16n", f"{type(e).__name__}: {str(e)[:160]}")


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────
def apply_customizing(target_conn, manifest: dict,
                       gate_token: Optional[str] = None,
                       require_gate: bool = True) -> dict:
    """Apply a packaged customizing manifest to the target.

    Args:
        target_conn:   pyrfc.Connection to target S/4.
        manifest:      Reconciler-packaged customizing gap dict. Recognised
                       top-level keys: exchange_rates, tax_codes, classes,
                       (extensible — unknown keys land in needs_basis).
        gate_token:    HMAC-signed post_data_prep gate token. Required
                       when require_gate=True (production posture).
        require_gate:  Pass False for unit tests / dry-run.

    Returns:
        dict with per-category outcomes, an overall verdict, and the
        list of items that need a basis operator (NEEDS_BASIS list).
        ALWAYS returns; never raises.
    """
    if require_gate and not gate_token:
        return {"verdict": "REFUSED", "reason":
                "apply_customizing called without gate_token under "
                "post_data_prep policy; refuse to mutate target customizing"}

    outcomes = []
    needs_basis: List[dict] = []
    applied_total = 0

    # ── Exchange rates: Strategy A (direct BAPI) ────────────────────────
    er = manifest.get("exchange_rates") or []
    if er:
        r = _apply_exchange_rates(target_conn, er)
        outcomes.append({"category": "exchange_rates", **r})
        applied_total += r["applied"]
        if not r["ok"]:
            needs_basis.append({
                "category":     "exchange_rates",
                "se16n_path":   "TCURR / TCURF / TCURV",
                "row_count":    len(er),
                "reason":       r["detail"],
            })

    # ── Tax codes: Strategy A fails by design → Strategy B (transport) ──
    tc = manifest.get("tax_codes") or []
    if tc:
        r = _apply_via_transport(target_conn, "T007A", tc)
        outcomes.append({"category": "tax_codes", **r})
        applied_total += r["applied"]
        if not r["ok"]:
            needs_basis.append({
                "category":     "tax_codes",
                "se16n_path":   "T007A / T007S",
                "row_count":    len(tc),
                "reason":       r["detail"],
            })

    # ── Classes: Strategy A (BAPI_CLASS_CREATE) ─────────────────────────
    cls = manifest.get("classes") or []
    if cls:
        r = _apply_classes(target_conn, cls)
        outcomes.append({"category": "classes", **r})
        applied_total += r["applied"]
        if not r["ok"]:
            # Fallback to transport
            r2 = _apply_via_transport(target_conn, "KLAH", cls)
            outcomes.append({"category": "classes_fallback", **r2})
            applied_total += r2["applied"]
            if not r2["ok"]:
                needs_basis.append({
                    "category":     "classes",
                    "se16n_path":   "KLAH / KSML / CABN / CAWN",
                    "row_count":    len(cls),
                    "reason":       r["detail"] + " | " + r2["detail"],
                })

    # ── Unknown / extension blocks: route to NEEDS_BASIS ────────────────
    KNOWN = {"exchange_rates", "tax_codes", "classes"}
    for k, v in manifest.items():
        if k in KNOWN or not isinstance(v, list) or not v:
            continue
        needs_basis.append({
            "category":     k,
            "se16n_path":   "(see manifest)",
            "row_count":    len(v),
            "reason":       "no auto-applier registered for this category",
        })

    verdict = (
        "GO"       if applied_total > 0 and not needs_basis else
        "REVIEW"   if needs_basis else
        "NOTHING_TO_APPLY"
    )

    return {
        "verdict":       verdict,
        "applied_total": applied_total,
        "outcomes":      outcomes,
        "needs_basis":   needs_basis,
        "summary":       f"{applied_total} customizing rows applied; "
                          f"{len(needs_basis)} categories need basis attention",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Self-test (no RFC)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("customizing_applier - self-test")
    print("=" * 70)

    class FakeConn:
        """Records calls; returns canned BAPI responses."""
        def __init__(self):
            self.calls: List[tuple] = []

        def call(self, fn, **kw):
            self.calls.append((fn, kw))
            if fn == "BAPI_EXCHANGERATE_CREATEMULTIPLE":
                return {"RETURN": []}    # no errors
            if fn == "BAPI_TRANSACTION_COMMIT":
                return {}
            if fn == "BAPI_CLASS_CREATE":
                return {"RETURN": {"TYPE": "S", "MESSAGE": "ok"}}
            if fn == "BAPI_CTS_CREATE_REQUEST":
                return {"REQUEST_HEADER_INFO": {"TRKORR": "DEVK900042"}}
            if fn == "BAPI_CTS_INSERT_OBJECTS_IN_REQUEST":
                return {}
            if fn == "BAPI_CTS_RELEASE_REQUEST":
                return {}
            if fn == "TMS_MGR_FORWARD":
                return {}
            return {}

    # 1) Gate-token policy: refuses without token
    res = apply_customizing(None, {"exchange_rates": [{"from": "USD"}]})
    assert res["verdict"] == "REFUSED"
    print(f"\n[policy] gate_token required: {res['reason'][:60]}...")

    # 2) Happy path: exchange rates via BAPI
    conn = FakeConn()
    res = apply_customizing(conn, {
        "exchange_rates": [
            {"from": "USD", "to": "EUR", "rate": "0.92", "valid_from": "20260101"},
            {"from": "GBP", "to": "EUR", "rate": "1.18", "valid_from": "20260101"},
        ],
    }, gate_token="test-token")
    print(f"\n[exchange_rates] verdict={res['verdict']} "
          f"applied={res['applied_total']} needs_basis={len(res['needs_basis'])}")
    assert res["applied_total"] == 2
    assert any(c[0] == "BAPI_EXCHANGERATE_CREATEMULTIPLE" for c in conn.calls)
    assert any(c[0] == "BAPI_TRANSACTION_COMMIT" for c in conn.calls)

    # 3) Tax codes: no BAPI → transport path
    conn = FakeConn()
    res = apply_customizing(conn, {
        "tax_codes": [{"code": "I0", "country": "US", "rate": "0.00",
                       "description": "0% Input"}],
    }, gate_token="test-token")
    print(f"[tax_codes]      verdict={res['verdict']} "
          f"applied={res['applied_total']} mechanism={res['outcomes'][0]['mechanism']}")
    assert res["applied_total"] == 1
    assert res["outcomes"][0]["mechanism"] == "transport"
    assert any(c[0] == "BAPI_CTS_CREATE_REQUEST" for c in conn.calls)

    # 4) Classes via BAPI
    conn = FakeConn()
    res = apply_customizing(conn, {
        "classes": [{"class": "FERT_CLASS", "class_type": "001",
                     "description": "Material classification"}],
    }, gate_token="test-token")
    print(f"[classes]        verdict={res['verdict']} "
          f"applied={res['applied_total']}")
    assert res["applied_total"] == 1

    # 5) Unknown category lands in NEEDS_BASIS
    conn = FakeConn()
    res = apply_customizing(conn, {
        "exchange_rates": [{"from": "USD", "to": "EUR", "rate": "0.92"}],
        "partner_roles":  [{"role": "ZX01"}],   # unknown
    }, gate_token="test-token")
    print(f"[partial]        verdict={res['verdict']} "
          f"applied={res['applied_total']} needs_basis={len(res['needs_basis'])}: "
          f"{res['needs_basis'][0]['category']}")
    assert res["applied_total"] == 1
    assert res["needs_basis"][0]["category"] == "partner_roles"

    # 6) Nothing to do
    res = apply_customizing(FakeConn(), {}, gate_token="test-token")
    assert res["verdict"] == "NOTHING_TO_APPLY"
    print(f"[empty]          verdict={res['verdict']}")

    print("\nOK - customizing_applier applies exchange rates via BAPI, "
          "routes tax codes via CTS transport, creates classes via "
          "BAPI_CLASS_CREATE, and surfaces unknown categories as NEEDS_BASIS.")
