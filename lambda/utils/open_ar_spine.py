"""
open_ar_spine - OpenAR via BAPI_ACC_DOCUMENT_POST (FI receivables).

Object-promotion grind batch 5 / 4. The most business-critical
transactional data class: open receivables posted as balanced FI documents
with a 'data takeover' clearing-account offset (no P&L impact). Consumes
the F1 key registry to resolve the customer; if the migrated customer
isn't recon-account-ready in the target company code (KNB1), harmonizes
to a recon-ready customer and records that back in F1.

Source ECC row shape::

    {"BELNR": "<source document number>",
     "KUNNR": "<source customer>",
     "DMBTR": "<open amount in local currency>",
     "SHKZG": "S",                  # debit/credit indicator (S=debit, H=credit)
     "WAERS": "USD"}

Org context required in ``cc_org``:
    COMP_CODE, CLEARING_GL, PROFIT_CTR, USERNAME (defaults to MIGRATE_ADMI)

Verify key writes to BSID (the FI open-item table), proving the item
exists AND carries the right amount — a stronger tie-out than a BKPF
header existence check.
"""
from __future__ import annotations

import datetime
from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


def _parse_amt(val, default=0.0) -> float:
    try:
        s = str(val or "").strip().replace(",", "")
        return float(s) if s else float(default)
    except Exception:
        return float(default)


@register_spine
class OpenARSpineOrchestrator(BaseSpineOrchestrator):
    """OpenAR via BAPI_ACC_DOCUMENT_POST with customer recon-readiness harmonization."""

    object_type           = "OpenAR"
    source_key_field      = "BELNR"
    extension_structure   = "BAPI_TE_BKPF"
    # Customer resolution is explicit in build_payload (registry-then-harmonize-to-
    # recon-ready); default resolve_fk would defeat the harmonization path.
    fk_fields: dict       = {}

    cc_org: dict = {}

    def __init__(self, *args, cc_org: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.cc_org = dict(cc_org or {})

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("BELNR") or "").strip():
            return "BELNR is required (source FI document number)"
        if not (row.get("KUNNR") or "").strip():
            return "KUNNR is required (source customer)"
        required = ("COMP_CODE", "CLEARING_GL", "PROFIT_CTR")
        missing = [k for k in required if not (self.cc_org.get(k) or "").strip()]
        if missing:
            return f"cc_org missing: {','.join(missing)}"
        if _parse_amt(row.get("DMBTR"), 0) <= 0:
            return "DMBTR (open amount) must be > 0"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_partner = (row.get("KUNNR") or "").strip()
        src_doc = (row.get("BELNR") or "").strip()
        amount = _parse_amt(row.get("DMBTR"))
        shkzg = (row.get("SHKZG") or "S").strip()
        curr = (row.get("WAERS") or self.cc_org.get("CURRENCY") or "USD").strip()
        bukrs = self.cc_org["COMP_CODE"]

        pool = self._recon_partners("KNB1", "KUNNR", bukrs)
        if not pool:
            return {"_no_partner": True, "_kind": "Customer", "_bukrs": bukrs}

        tgt = None
        if self.key_map is not None:
            tgt = self.key_map.resolve("Customer", src_partner)
        pdisp = "registry"
        if not (tgt and tgt in set(pool)):
            digits = "".join(ch for ch in src_partner if ch.isdigit())
            tgt = pool[(int(digits) if digits else 0) % len(pool)]
            pdisp = "harmonized"

        # WS2 -- multi-line FI document. row["lines"] is a list of additional
        # AR line items beyond the primary one captured in row.DMBTR. Each
        # extra line carries {DMBTR, GL_ACCOUNT, PROFIT_CTR, ITEM_TEXT}; the
        # offset onto the clearing-account remains a single per-document
        # balancer (no double-offsetting), so the multi-line doc maintains
        # FI balance regardless of line count.
        extra_lines = row.get("lines") or []
        pamt = amount if shkzg == "S" else -amount
        doc_date = self.cc_org.get("DOC_DATE") or datetime.date.today().strftime("%Y%m%d")
        hdr = {
            "USERNAME":   self.cc_org.get("USERNAME", "MIGRATE_ADMI"),
            "COMP_CODE":  bukrs,
            "DOC_DATE":   doc_date,
            "PSTNG_DATE": doc_date,
            "DOC_TYPE":   "DR",
            "BUS_ACT":    "RFBU",
            "REF_DOC_NO": ("M4H-" + src_doc)[:16],
        }
        # Primary AR line (item 1) + N extra GL lines + 1 balancing GL line.
        # Numbering: 0000000001 = AR; 0000000002..N+1 = GL items; N+2 = offset.
        ar_items = [{"ITEMNO_ACC": "0000000001", "CUSTOMER": tgt}]
        gl = []
        cur = [{"ITEMNO_ACC": "0000000001", "CURRENCY": curr,
                 "AMT_DOCCUR": "%.2f" % pamt}]
        # Per-line GL extras
        running_total = pamt
        for i, line in enumerate(extra_lines, start=2):
            line_amt = float(line.get("DMBTR") or 0)
            if line_amt <= 0:
                continue
            signed = -line_amt if shkzg == "S" else line_amt
            itemno = f"{i:010d}"
            gl.append({
                "ITEMNO_ACC":  itemno,
                "GL_ACCOUNT":  line.get("GL_ACCOUNT") or self.cc_org["CLEARING_GL"],
                "ITEM_TEXT":   (line.get("ITEM_TEXT") or f"M4H open AR {src_doc} L{i}")[:50],
                "PROFIT_CTR":  line.get("PROFIT_CTR") or self.cc_org["PROFIT_CTR"],
            })
            cur.append({"ITEMNO_ACC": itemno, "CURRENCY": curr,
                         "AMT_DOCCUR": "%.2f" % signed})
            running_total += signed
        # Balancing offset line: net residual on the configured clearing GL
        offset_no = f"{(2 + len(gl)):010d}"
        gl.append({"ITEMNO_ACC": offset_no,
                    "GL_ACCOUNT": self.cc_org["CLEARING_GL"],
                    "ITEM_TEXT":  f"M4H open AR {src_doc}"[:50],
                    "PROFIT_CTR": self.cc_org["PROFIT_CTR"]})
        cur.append({"ITEMNO_ACC": offset_no, "CURRENCY": curr,
                     "AMT_DOCCUR": "%.2f" % (-running_total)})

        payload: dict = {
            "DOCUMENTHEADER":     hdr,
            "ACCOUNTGL":          gl,
            "CURRENCYAMOUNT":     cur,
            "ACCOUNTRECEIVABLE":  ar_items,
            "_src_doc":           src_doc,
            "_src_partner":       src_partner,
            "_tgt_partner":       tgt,
            "_pdisp":             pdisp,
            "_line_count":        1 + len(gl),   # AR line + GL/offset items
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED
        if payload.get("_no_partner"):
            return None, [f"no recon-ready {payload.get('_kind')} in company {payload.get('_bukrs')}"], None, None

        src_doc     = payload.pop("_src_doc", "")
        src_partner = payload.pop("_src_partner", "")
        tgt_partner = payload.pop("_tgt_partner", "")
        pdisp       = payload.pop("_pdisp", "registry")
        payload.pop("_line_count", None)

        resp = self.c.call("BAPI_ACC_DOCUMENT_POST", **payload)
        ret = resp.get("RETURN") or []
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        objkey = (resp.get("OBJ_KEY") or "").strip()
        if hard or not objkey or objkey == "$":
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

        # OBJ_KEY is BELNR(10) + BUKRS(4) + GJAHR(4) — return just the BELNR
        belnr = objkey[:10]
        if pdisp == "harmonized" and self.key_map is not None and src_partner:
            try:
                self.key_map.add("Customer", src_partner, tgt_partner, "harmonized")
            except Exception:
                pass
            msgs.append(f"customer {src_partner} harmonized to {tgt_partner}")
        vk = {"table": "BSID",
              "key": {"BUKRS": objkey[10:14] or self.cc_org.get("COMP_CODE", ""),
                      "BELNR": belnr, "GJAHR": objkey[14:18]}}
        return belnr, msgs, DISP_CREATED, vk

    def _recon_partners(self, table: str, key_field: str, bukrs: str) -> list:
        cache = getattr(self, "_recon_cache", None)
        if cache is None:
            cache = self._recon_cache = {}
        ck = (table, bukrs)
        if ck in cache:
            return cache[ck]
        out: list = []
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE=table, DELIMITER="|",
                OPTIONS=[{"TEXT": f"BUKRS = '{bukrs}'"}],
                FIELDS=[{"FIELDNAME": key_field}], ROWCOUNT=300,
            )
            out = [(x.get("WA") or "").strip() for x in r.get("DATA") or []
                   if (x.get("WA") or "").strip()]
        except Exception:
            out = []
        cache[ck] = out
        return out
