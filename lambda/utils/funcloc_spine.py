"""
funcloc_spine - FunctionalLocation via BAPI_FUNCLOC_CREATE.

Object-promotion grind batch 2 / 4. Functional-location labels are
**structure-indicator bound**: every TPLNR must conform to the target
structure indicator's editing mask (per-level delimiter + segment widths).
A source label whose pattern collides with the target mask is rejected by
the BAPI with an unhelpful error.

This orchestrator discovers the in-use structure indicator + mask once
(cached) and reformats the source label to conform; the (source, target)
pair is recorded in the F1 key_map ledger so dependent objects (equipment
installed at the location, work orders, etc.) follow the remap.

Source ECC IFLOT row shape::

    {"TPLNR": "<source label>",  # e.g. "1100-PMP-001"
     "FLTYP": "<category>",      # e.g. "1"
     "PLTXT": "<description>"}

Hierarchy is NOT auto-installed (standalone create). The Migration Cockpit
file lane handles in-hierarchy installation when needed.
"""
from __future__ import annotations

import re
from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class FunctionalLocationSpineOrchestrator(BaseSpineOrchestrator):
    """FunctionalLocation via BAPI_FUNCLOC_CREATE.

    Label reformat + collision-safe target assignment. Internal vs external
    numbering is determined by the structure indicator's coding. The result
    captures whatever SAP actually accepted.
    """

    object_type           = "FunctionalLocation"
    source_key_field      = "TPLNR"
    extension_structure   = "BAPI_TE_IFLOT"
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("TPLNR") or "").strip():
            return "TPLNR is required"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        cfg = self._floc_config()
        if not cfg["strind"]:
            # Surfaced via validate-style payload that call_bapi shortcircuits
            return {"_no_strind": True}
        src = (row["TPLNR"] or "").strip()
        label, remapped = self._floc_label(src, cfg)
        desc = ((row.get("PLTXT") or row.get("SHTXT") or f"Functional location {src or label}").strip())[:40]
        payload: dict = {
            "EXTERNAL_NUMBER": label,
            "DATA_GENERAL":    {"DESCRIPT": desc},
            "DATA_SPECIFIC":   {"STRIND": cfg["strind"], "CATEGORY": cfg["category"]},
            "_src_label":      src,
            "_target_label":   label,
            "_remapped":       remapped,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple:
        from base_spine_orchestrator import DISP_CREATED, DISP_REMAPPED
        if payload.get("_no_strind"):
            return None, ["target has no functional-location structure indicator"], None, None

        src_label  = payload.pop("_src_label", "")
        tgt_label  = payload.pop("_target_label", "")
        remapped   = payload.pop("_remapped", False)

        resp = self.c.call("BAPI_FUNCLOC_CREATE", **payload)
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
            return None, msgs, None, None

        target = (resp.get("FUNCTLOCATION") or tgt_label).strip()
        # Track to keep cross-run collision-safety
        taken = getattr(self, "_floc_taken", None)
        if taken is None:
            taken = self._floc_taken = set()
        taken.add(target)

        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None, None

        vk = {"table": "IFLOT", "key": {"TPLNR": target}}
        if remapped:
            msgs.append(f"label {src_label} reformatted -> {target}")
            return target, msgs, DISP_REMAPPED, vk
        # If SAP echoed back the label unchanged it's a clean create
        return target, msgs, DISP_CREATED, vk

    # ── discover the target structure indicator + mask ───────────────────────
    def _floc_config(self) -> dict:
        cache = getattr(self, "_flcfg_cache", None)
        if cache is not None:
            return cache
        cfg = {"strind": "", "category": "", "delim": "-",
               "widths": [4, 4, 4, 4], "existing": set()}
        try:
            # Read 100 existing IFLOT rows, derive the structure indicator from majority
            r = self.c.call(
                "RFC_READ_TABLE",
                QUERY_TABLE="IFLOT",
                DELIMITER="|",
                FIELDS=[{"FIELDNAME": "TPLKZ"},
                        {"FIELDNAME": "TPLNR"},
                        {"FIELDNAME": "FLTYP"}],
                ROWCOUNT=100,
            )
            from collections import Counter
            strinds = Counter()
            cats    = Counter()
            labels  = []
            for d in r.get("DATA") or []:
                wa = (d.get("WA") or "")
                parts = wa.split("|") if "|" in wa else [wa]
                if len(parts) >= 1: strinds[parts[0].strip()] += 1
                if len(parts) >= 2: labels.append(parts[1].strip())
                if len(parts) >= 3: cats[parts[2].strip()] += 1
            if strinds:
                cfg["strind"] = strinds.most_common(1)[0][0]
            if cats:
                cfg["category"] = cats.most_common(1)[0][0]
            cfg["existing"] = set(filter(None, labels))
            # Infer delimiter + widths from a sample label that matches the strind
            for lbl in labels:
                if not lbl:
                    continue
                # heuristic: any non-alnum char is the delimiter
                m = re.search(r"[^A-Za-z0-9]", lbl)
                if m:
                    cfg["delim"] = m.group(0)
                    segs = lbl.split(cfg["delim"])
                    if 1 < len(segs) <= 8:
                        cfg["widths"] = [len(s) for s in segs]
                        break
        except Exception:
            pass
        self._flcfg_cache = cfg
        return cfg

    def _floc_label(self, src: str, cfg: dict) -> tuple[str, bool]:
        """Reformat src to fit the target mask. Returns (final_label, remapped)."""
        delim  = cfg["delim"]
        widths = cfg["widths"]
        taken  = getattr(self, "_floc_taken", set())
        # Already in target? Try as-is first.
        if src in cfg["existing"] or src in taken:
            return self._next_free(src, cfg, taken), True
        # Test the source against the mask
        segs = src.split(delim) if delim and delim in src else [src]
        # Re-pad/truncate each segment to the corresponding width
        fitted = []
        for i, w in enumerate(widths):
            s = segs[i] if i < len(segs) else ""
            s_clean = re.sub(r"[^A-Za-z0-9]", "", s)[:w].zfill(w) if s else "0" * w
            fitted.append(s_clean)
        candidate = delim.join(fitted)
        if candidate == src:
            return src, False
        return candidate, True

    @staticmethod
    def _next_free(base: str, cfg: dict, taken: set) -> str:
        """Find a collision-free variant by incrementing the last segment."""
        delim = cfg["delim"]
        widths = cfg["widths"]
        parts = base.split(delim)
        for n in range(1, 99999):
            suffix = str(n).zfill(widths[-1])[-widths[-1]:]
            if len(parts) > 1:
                cand = delim.join(parts[:-1] + [suffix])
            else:
                cand = suffix
            if cand not in taken and cand not in cfg["existing"]:
                return cand
        return base   # give up; let BAPI reject
