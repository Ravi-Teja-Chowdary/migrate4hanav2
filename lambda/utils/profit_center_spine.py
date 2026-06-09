"""
profit_center_spine - ProfitCenter via BAPI_PROFITCENTER_CREATE.

Object-promotion grind batch 1 / 4. Composite-key master object
(KOKRS = controlling area, PRCTR = profit center). Idempotent re-runs via
CEPC target probe.

Source ECC CEPC row shape::

    {"KOKRS": "<controlling area>",  # e.g. "1710"
     "PRCTR": "<profit center>",     # e.g. "YB600"
     "DATBI": "99991231",
     "MCTXT": "<short text>",
     "LTEXT": "<long text>",
     "VERAK": "<person in charge>"}

Org context is required (hierarchy node, validity dates). The orchestrator
expects the caller (or UnifiedLoader) to attach an ``org`` dict via
``self.cc_org`` containing CO_AREA + PC_HIER + VALID_FROM. Falls back to
runtime discovery if not provided.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class ProfitCenterSpineOrchestrator(BaseSpineOrchestrator):
    """ProfitCenter via BAPI_PROFITCENTER_CREATE. Composite key (KOKRS, PRCTR)."""

    object_type           = "ProfitCenter"
    source_key_field      = "PRCTR"
    extension_structure   = "BAPI_TE_CEPC"
    fk_fields: dict       = {}    # KOKRS is configuration, not a migration ledger key

    # Org context - set by the caller after construction. Mirrors the pattern
    # UnifiedLoader uses to attach discovery output (see handler.py loader.cc_org).
    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        # Make cc_org instance-level (frozen class-attr would be shared)
        self.cc_org = dict(cc_org or {})

    # ── validate the composite key + org context ─────────────────────────────
    def validate(self, row: dict) -> Optional[str]:
        prctr = (row.get("PRCTR") or "").strip()
        if not prctr:
            return "PRCTR is required"
        if not (self.cc_org.get("CO_AREA") or row.get("KOKRS")):
            return "CO_AREA missing - configure controlling area or pass KOKRS on the row"
        return None

    # ── BAPI payload ─────────────────────────────────────────────────────────
    def build_payload(self, row: dict, ext_rows: list) -> dict:
        prctr = (row["PRCTR"] or "").strip()
        kokrs = (self.cc_org.get("CO_AREA") or row.get("KOKRS") or "").strip()
        pc_hier = (self.cc_org.get("PC_HIER") or row.get("KHINR") or "").strip()
        valid_from = (self.cc_org.get("VALID_FROM") or row.get("DATAB") or "20240101")
        valid_to   = (row.get("DATBI") or "99991231")
        short = ((row.get("MCTXT") or row.get("KOKRS_TEXT") or f"PC {prctr}").strip() or prctr)[:20]
        long_ = ((row.get("LTEXT") or short).strip() or short)[:40]
        verak = (row.get("VERAK") or "M4H").strip()[:20]

        master_data: dict = {
            "PROFIT_CTR":     prctr,
            "CONTROLLINGAREA": kokrs,
            "VALID_FROM":     valid_from,
            "VALID_TO":       valid_to,
            "NAME":           short,
            "LONG_TEXT":      long_,
            "PERSON_RESP":    verak,
            "PRCTR_HIER_GRP": pc_hier,
        }
        payload = {"PROFITCENTER_KEY": {"CONTROLLINGAREA": kokrs,
                                         "PROFIT_CTR": prctr,
                                         "VALID_FROM": valid_from,
                                         "VALID_TO":   valid_to},
                   "MASTER_DATA": master_data}
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    # ── BAPI invocation (pre-flight idempotency probe) ───────────────────────
    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_MATCHED_EXISTING, DISP_CREATED
        kokrs = payload["PROFITCENTER_KEY"]["CONTROLLINGAREA"]
        prctr = payload["PROFITCENTER_KEY"]["PROFIT_CTR"]
        vk = {"table": "CEPC", "key": {"KOKRS": kokrs, "PRCTR": prctr}}
        if self._profit_center_exists(kokrs, prctr):
            return prctr, [f"profit center {prctr} already exists in {kokrs}"], DISP_MATCHED_EXISTING, vk

        resp = self.c.call("BAPI_PROFITCENTER_CREATE", **payload)
        ret = resp.get("RETURN") or {}
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
            return None, msgs, None, None
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None, None
        return prctr, msgs, DISP_CREATED, vk

    # ── target probe ─────────────────────────────────────────────────────────
    def _profit_center_exists(self, kokrs: str, prctr: str) -> bool:
        try:
            r = self.c.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="CEPC",
                DELIMITER="|",
                OPTIONS=[{"TEXT": f"KOKRS = '{kokrs}' AND PRCTR = '{prctr}'"}],
                FIELDS=[{"FIELDNAME": "PRCTR"}],
                ROWCOUNT=1,
            )
            return bool(r.get("DATA"))
        except Exception:
            return False
