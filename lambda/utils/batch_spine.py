"""
batch_spine - Batch via BAPI_BATCH_CREATE.

Object-promotion grind batch 5 / 4. Batch master under a (material, plant)
pair. The tricky shape: batches need a batch-managed material+plant; source
materials rarely carry the target's plant view (or the batch-managed
attribute, MARC.XCHPF='X'). We discover a target-ready material+plant and
harmonize.

Source ECC row shape::

    {"MATNR": "<source material>",
     "CHARG": "<source batch number>"}    # SAP CHARG max 10 chars

Strategy: source CHARG is preserved 1:1 under the target material when
free; on collision (MCH1 hit), append a numeric suffix (truncated to 10
chars). Up to 999 attempts before dead-letter.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, register_spine


@register_spine
class BatchSpineOrchestrator(BaseSpineOrchestrator):
    """Batch via BAPI_BATCH_CREATE under a target-ready (material, plant)."""

    object_type           = "Batch"
    source_key_field      = "CHARG"
    extension_structure   = "BAPI_TE_MCH1"
    fk_fields: dict       = {}

    def validate(self, row: dict) -> Optional[str]:
        if not (row.get("CHARG") or "").strip():
            return "CHARG is required (source batch number)"
        return None

    def build_payload(self, row: dict, ext_rows: list) -> dict:
        src_mat = (row.get("MATNR") or "").strip()
        src_batch = (row.get("CHARG") or "").strip()
        tgt_mat, plant = self._batch_target_mat()
        if not tgt_mat or not plant:
            return {"_no_target": True}

        # Collision-safe CHARG under the target material
        tgt_batch, n = src_batch, 0
        while self._batch_exists(tgt_mat, tgt_batch):
            n += 1
            tgt_batch = f"{src_batch}_{n}"[-10:]    # CHARG max 10 chars
            if n > 999:
                return {"_no_free_batch": True, "_src": f"{src_mat}/{src_batch}"}

        payload: dict = {
            "MATERIAL":     tgt_mat,
            "PLANT":        plant,
            "BATCH":        tgt_batch,
            "_src_mat":     src_mat,
            "_src_batch":   src_batch,
            "_tgt_mat":     tgt_mat,
            "_tgt_batch":   tgt_batch,
            "_plant":       plant,
        }
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            from base_spine_orchestrator import build_extensioninx
            field_names = [(r.get("VALUEPART1") or "")[:30].strip() for r in ext_rows]
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)
        return payload

    def call_bapi(self, payload: dict) -> tuple[Optional[str], list, Optional[str]]:
        from base_spine_orchestrator import DISP_CREATED, DISP_REMAPPED
        if payload.get("_no_target"):
            return None, ["no target batch-managed material/plant discovered"], None, None
        if payload.get("_no_free_batch"):
            return None, [f"could not find a free batch number for {payload.get('_src')}"], None, None

        src_mat   = payload.pop("_src_mat", "")
        src_batch = payload.pop("_src_batch", "")
        tgt_mat   = payload.pop("_tgt_mat", "")
        tgt_batch = payload.pop("_tgt_batch", "")
        plant     = payload.pop("_plant", "")

        resp = self.c.call("BAPI_BATCH_CREATE", **payload)
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

        target = (resp.get("BATCH") or tgt_batch).strip()
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs, None, None

        mat_remap = tgt_mat != src_mat
        batch_remap = target != src_batch
        if mat_remap:
            msgs.append(f"material {src_mat} harmonized to batch-managed {tgt_mat}/plant {plant}")
        if batch_remap:
            msgs.append(f"batch {src_batch} collided -> {target}")
        vk = {"table": "MCH1", "key": {"MATNR": tgt_mat, "CHARG": target}}
        if mat_remap or batch_remap:
            return target, msgs, DISP_REMAPPED, vk
        return target, msgs, DISP_CREATED, vk

    # ── target discovery ────────────────────────────────────────────────────
    def _batch_target_mat(self) -> tuple:
        cache = getattr(self, "_batch_mat_cache", None)
        if cache is not None:
            return cache
        mat, plant = "", ""
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="MARC", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "MATNR"}, {"FIELDNAME": "WERKS"}],
                OPTIONS=[{"TEXT": "XCHPF = 'X'"}], ROWCOUNT=1,
            )
            if r.get("DATA"):
                parts = (r["DATA"][0].get("WA") or "").split("|") + ["", ""]
                mat, plant = parts[0].strip(), parts[1].strip()
        except Exception:
            pass
        self._batch_mat_cache = (mat, plant)
        return mat, plant

    def _batch_exists(self, mat: str, batch: str) -> bool:
        try:
            r = self.c.call(
                "RFC_READ_TABLE", QUERY_TABLE="MCH1", DELIMITER="|",
                FIELDS=[{"FIELDNAME": "CHARG"}],
                OPTIONS=[{"TEXT": f"MATNR = '{mat}' AND CHARG = '{batch}'"}],
                ROWCOUNT=1,
            )
            return bool(r.get("DATA"))
        except Exception:
            return False


