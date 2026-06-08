"""
exchange_rates_spine - ExchangeRates via BAPI_EXCHRATE_CREATEMULTIPLE.

Object-promotion grind batch 6 / 4 (FINAL — closes the live-25 sweep).
Currency exchange rates (TCURR). The tricky shape:

1. TCURR.GDATU is an INVERTED date (99999999 - YYYYMMDD), and the IDES
   appliance's 'beginning of time' baseline decodes to 1798 which is below
   the BAPI's accepted floor. We un-invert + clamp.
2. Rate types (KURST) are CUSTOMIZING (no BAPI to create them) -- screen
   against TCURV upfront and dead-letter unsupported types as customizing
   prerequisites rather than letting the BAPI hard-fail per row.
3. Operational rate types -- those with translation factors in TCURF --
   are a STRICT SUBSET of TCURV. A type can exist in TCURV yet still
   reject rates with "valid system settings have not been made". We
   surface this as a distinct dead-letter reason so config-applier can
   pick it up.

Spine-pattern note: although the legacy bulk path uses
BAPI_EXCHRATE_CREATEMULTIPLE with EXCHRATE_LIST as a batch, the spine API
is row-by-row. We call the same BAPI with a 1-element list per row -- the
BAPI handles both shapes identically.

Source ECC TCURR row shape::

    {"KURST": "M",                  # rate type
     "FCURR": "USD",                # from currency
     "TCURR": "EUR",                # to currency
     "GDATU": "79019131",            # inverted date (= 20081269 -> 2008-12-31)
     "UKURS": "0.7234",             # exchange rate
     "FFACT": "1",                  # from factor (default 1)
     "TFACT": "1"}                  # to factor (default 1)
"""
from __future__ import annotations

import datetime
from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


# BAPI accepted date window for EXCH_RATE.VALID_FROM
_EXRATE_FLOOR   = datetime.date(1995, 1, 1)
_EXRATE_CEILING = datetime.date(9999, 12, 31)


def _parse_num(val, default=0.0) -> float:
    try:
        s = str(val or "").strip().replace(",", "")
        # Trailing-minus indirect-quote convention
        if s.endswith("-"):
            return -float(s[:-1])
        return float(s) if s else float(default)
    except Exception:
        return float(default)


def _gdatu_to_date(gdatu) -> tuple:
    """TCURR.GDATU is inverted (99999999 - YYYYMMDD). Returns (date, clamped_bool)."""
    try:
        ymd = 99999999 - int(str(gdatu).strip())
        d = datetime.date(ymd // 10000, (ymd // 100) % 100, ymd % 100)
    except Exception:
        return datetime.date.today(), False
    if d < _EXRATE_FLOOR:
        return _EXRATE_FLOOR, True
    if d > _EXRATE_CEILING:
        return _EXRATE_CEILING, True
    return d, False


@register_spine
class ExchangeRatesSpineOrchestrator(BaseSpineOrchestrator):
    """ExchangeRates via BAPI_EXCHRATE_CREATEMULTIPLE (one rate per spine row)."""

    object_type           = "ExchangeRates"
    # Composite-key shape; use the rate-tuple slug as the source_key
    source_key_field      = "_rate_key"
    extension_structure   = "BAPI_TE_TCURR"
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("FCURR") or "").strip():
            return "FCURR is required (from currency)"
        if not (row.get("TCURR") or "").strip():
            return "TCURR is required (to currency)"
        return None

    def transform(self, row: dict) -> Optional[dict]:
        """Augment the row with a composite source_key so the base load_one
        sees a non-empty source_key_field. We compute KURST/FCURR/TCURR/GDATU
        as the natural key."""
        out = dict(row or {})
        rate_type = (out.get("KURST") or "M").strip()
        out["KURST"] = rate_type
        out["_rate_key"] = (f"{rate_type}|{(out.get('FCURR') or '').strip()}|"
                             f"{(out.get('TCURR') or '').strip()}|"
                             f"{(out.get('GDATU') or '').strip()}")
        # Continue through the transformer if attached (FX-rate ruleset, etc.)
        if self.transformer is None:
            return out
        try:
            out2, dq = self.transformer.apply(self.object_type, out)
        except Exception:
            return out
        if dq and not dq.passed:
            return None
        return out2

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        rate_type = (row.get("KURST") or "M").strip()
        # Customizing gates
        known = self._target_rate_types()
        if known and rate_type not in known:
            return {"_no_rate_type": True, "_rt": rate_type}
        operational = self._configured_rate_types()
        valid_from, clamped = _gdatu_to_date(row.get("GDATU"))
        exch_rate = _parse_num(row.get("UKURS"))
        ffact = str(int(_parse_num(row.get("FFACT"), 1)) or 1)
        tfact = str(int(_parse_num(row.get("TFACT"), 1)) or 1)
        line = {
            "RATE_TYPE":    rate_type,
            "FROM_CURR":    (row.get("FCURR") or "").strip(),
            "TO_CURRNCY":   (row.get("TCURR") or "").strip(),
            "VALID_FROM":   valid_from,   # datetime.date (DATS)
            "EXCH_RATE":    exch_rate,
            "FROM_FACTOR":  ffact,
            "TO_FACTOR":    tfact,
        }
        payload: dict = {
            "UPD_ALLOW":     "X",
            "EXCHRATE_LIST": [line],
            "_rate_type":    rate_type,
            "_from_curr":    line["FROM_CURR"],
            "_to_curr":      line["TO_CURRNCY"],
            "_valid_from":   valid_from,
            "_clamped":      clamped,
            "_operational":  (not operational) or (rate_type in operational),
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple[Optional[str], list, Optional[str]]:
        from base_spine_orchestrator import DISP_CREATED
        if payload.get("_no_rate_type"):
            rt = payload.get("_rt")
            return None, [f"rate type {rt} not defined in target (TCURV) -- customizing prerequisite"], None

        rate_type   = payload.pop("_rate_type", "")
        fcurr       = payload.pop("_from_curr", "")
        tcurr       = payload.pop("_to_curr", "")
        valid_from  = payload.pop("_valid_from", datetime.date.today())
        clamped     = payload.pop("_clamped", False)
        operational = payload.pop("_operational", True)

        try:
            resp = self.c.call("BAPI_EXCHRATE_CREATEMULTIPLE", **payload)
        except Exception as e:
            try:
                self.c.call("BAPI_TRANSACTION_ROLLBACK")
            except Exception:
                pass
            return None, [f"exchrate create exception: {str(e).splitlines()[0]}"], None

        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        if hard:
            try:
                self.c.call("BAPI_TRANSACTION_ROLLBACK")
            except Exception:
                pass
            # Distinguish customizing-factor gap from genuine data error
            txt = " ".join((m.get("MESSAGE") or "") for m in hard).lower()
            cfg_gap = ("system settings" in txt or "not been made" in txt
                        or "no exchange rate type" in txt)
            if cfg_gap:
                msgs.insert(0, f"customizing prerequisite: rate type {rate_type} lacks TCURF factor settings")
            return None, msgs, None

        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None

        if clamped:
            msgs.append(f"valid-from clamped to {valid_from.isoformat()} (source date out of BAPI range)")
        if not operational:
            msgs.append(f"rate type {rate_type} not in TCURF operational set (loaded but may not apply at runtime)")
        # Target key is the rate tuple: KURST/FCURR/TCURR@valid_from
        target = f"{rate_type}|{fcurr}|{tcurr}@{valid_from.isoformat()}"
        return target, msgs, DISP_CREATED

    # ── target customizing discovery ─────────────────────────────────────────
    def _target_rate_types(self) -> set:
        """Set of KURST configured in target TCURV (customizing). Cached."""
        cache = getattr(self, "_rt_cache", None)
        if cache is not None:
            return cache
        types: set = set()
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="TCURV", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "KURST"}], ROWCOUNT=1000,
            )
            for x in r.get("DATA") or []:
                wa = (x.get("WA") or "").strip()
                if wa:
                    types.add(wa.split("|")[0].strip())
        except Exception:
            pass
        self._rt_cache = types
        return types

    def _configured_rate_types(self) -> set:
        """Set of KURST with TCURF factor settings — i.e. operational. Cached."""
        cache = getattr(self, "_op_cache", None)
        if cache is not None:
            return cache
        types: set = set()
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="TCURF", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "KURST"}], ROWCOUNT=100000,
            )
            for x in r.get("DATA") or []:
                wa = (x.get("WA") or "").strip()
                if wa:
                    types.add(wa.split("|")[0].strip())
        except Exception:
            pass
        self._op_cache = types
        return types
