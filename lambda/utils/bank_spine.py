"""
bank_spine - Bank master, BAPI_BANK_CREATE.

Object-promotion grind batch 1 / 4. Migrates the proven Bank load
(``bapi_loader.BapiLoader.create_bank``) onto the F2 spine pattern so it
benefits from F1 PersistentKeyMap + F3 dynamic schema + F4 transformation
engine + F5 benchmark instrumentation + F6 version routing uniformly.

Source ECC BNKA row shape::

    {"BANKS": "<country>",   # e.g. "US"
     "BANKL": "<bank key>",  # e.g. "BOFAUS3N"
     "BANKA": "<name>",
     "SWIFT": "<swift code>",
     "BRNCH": "<branch>",
     "ORT01": "<city>"}

Idempotency: a BNKA row keyed on (BANKS, BANKL) already in the target is
treated as matched_existing - we never re-create. Source key for the F1
ledger is BANKL (the bank key); we register one ``(Bank, BANKL) -> BANKL``
mapping per success since banks aren't renumbered.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class BankSpineOrchestrator(BaseSpineOrchestrator):
    """Bank master via BAPI_BANK_CREATE. Single-header, no FK, no subtables."""

    object_type           = "Bank"
    source_key_field      = "BANKL"
    extension_structure   = "BAPI_TE_BNKA"
    fk_fields: dict       = {}    # bank country LAND1 is customising, not in migration ledger

    # ── target probe so re-runs are idempotent ───────────────────────────────
    def validate(self, row: dict) -> Optional[str]:
        ctry = (row.get("BANKS") or "").strip()
        key  = (row.get("BANKL") or "").strip()
        if not (ctry and key):
            return "BANKS + BANKL are both required"
        # Cache probe results so re-validation doesn't pound RFC
        cache = getattr(self, "_bnka_cache", None)
        if cache is None:
            cache = self._bnka_cache = {}
        if (ctry, key) in cache:
            return None     # already probed; result captured in target_key path
        return None

    # ── BAPI payload ─────────────────────────────────────────────────────────
    def build_payload(self, row: dict, ext_rows: list) -> dict:
        ctry = (row["BANKS"] or "").strip()
        key  = (row["BANKL"] or "").strip()
        name = ((row.get("BANKA") or f"Bank {key}").strip() or key)[:60]
        addr: dict = {"BANK_NAME": name}
        swift = (row.get("SWIFT") or "").strip()
        if swift:
            addr["SWIFT_CODE"] = swift[:11]
        branch = (row.get("BRNCH") or "").strip()
        if branch:
            addr["BANK_BRANCH"] = branch[:40]
        city = (row.get("ORT01") or "").strip()
        if city:
            addr["CITY"] = city[:35]
        payload = {
            "BANK_CTRY":    ctry,
            "BANK_KEY":     key,
            "BANK_ADDRESS": addr,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    # ── BAPI invocation ──────────────────────────────────────────────────────
    def call_bapi(self, payload: dict) -> tuple[Optional[str], list]:
        """Pre-flight probe BNKA to keep re-runs idempotent (BAPI_BANK_CREATE
        raises if the bank already exists). Then call the BAPI and commit."""
        from base_spine_orchestrator import DISP_MATCHED_EXISTING
        ctry = payload["BANK_CTRY"]
        key  = payload["BANK_KEY"]
        if self._bank_exists(ctry, key):
            return key, [f"bank {ctry}/{key} already exists"], DISP_MATCHED_EXISTING

        resp = self.c.call("BAPI_BANK_CREATE", **payload)
        ret  = resp.get("RETURN") or {}
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
            return None, msgs
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs
        return key, msgs

    # ── target probe ─────────────────────────────────────────────────────────
    def _bank_exists(self, ctry: str, key: str) -> bool:
        try:
            r = self.c.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="BNKA",
                DELIMITER="|",
                OPTIONS=[{"TEXT": f"BANKS = '{ctry}' AND BANKL = '{key}'"}],
                FIELDS=[{"FIELDNAME": "BANKL"}],
                ROWCOUNT=1,
            )
            return bool(r.get("DATA"))
        except Exception:
            return False
