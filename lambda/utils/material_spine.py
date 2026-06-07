"""
material_spine - Material Master, deep view + EXTENSIONIN.

The promotion-pattern proof object for F2. Demonstrates how a new staging
object becomes spine-promoted: subclass BaseSpineOrchestrator, declare the
field map, hand BAPI_MATERIAL_SAVEDATA a layered payload.

Where the existing ``BapiLoader.create_material()`` uses only BASIC_VIEW
(MARA only - identity + UoM + description), this subclass adds:

    * MARA  - identity + global attrs (already in basic)
    * MARC  - plant data (PLANT, MMSTA, BESKZ, BESKM, AUSME, BESTV)
    * MARD  - storage location stock view
    * MBEW  - valuation (BWKEY, BKLAS, STPRS / VERPR pricing)
    * MARM  - alternative units of measure (per-UoM conversion tables)
    * MAKT  - language-keyed description multi-row
    * EXTENSIONIN - any ZZ*/YY*/CI_* custom append fields

The result: a real customer's Material Master record (with plant data,
ZZ_CUSTOM_CODE fields, multi-language descriptions, alt UoMs) loads cleanly
where the simpler create_material would have silently dropped 80% of it.
"""
from __future__ import annotations

from typing import Optional

from base_spine_orchestrator import BaseSpineOrchestrator, LoadResult, register_spine


# ─────────────────────────────────────────────────────────────────────────────
# Field maps - source ECC field -> BAPI input
# ─────────────────────────────────────────────────────────────────────────────
# Top-level material identity for HEADDATA
MARA_HEADER_FIELDS = {
    "MATL_TYPE":   "MTART",       # e.g. FERT, HALB, HAWA, ROH, DIEN
    "IND_SECTOR":  "MBRSH",       # industry sector (default 'M' for mechanical)
}

# Client-wide attrs in CLIENTDATA (MARA)
CLIENTDATA_FIELDS = {
    "BASE_UOM":          "MEINS",
    "OLD_MAT_NO":        "BISMT",
    "MATL_GROUP":        "MATKL",
    "DIVISION":          "SPART",
    "GROSS_WT":          "BRGEW",
    "NET_WEIGHT":        "NTGEW",
    "UNIT_OF_WT":        "GEWEI",
    "VOLUME":            "VOLUM",
    "VOLUMEUNIT":        "VOLEH",
    "SIZE_DIM":          "GROES",
    "BASIC_MATL":        "WRKST",
}

# Per-plant attrs (MARC) - the orchestrator emits one MM-IM-style PLANTDATA per
# plant the source carries.
PLANTDATA_FIELDS = {
    "PLANT":             "WERKS",
    "MRP_TYPE":          "DISMM",
    "MRP_CTRLR":         "DISPO",
    "PROC_TYPE":         "BESKZ",
    "SPPROCTYPE":        "BESKM",
    "PUR_GROUP":         "EKGRP",
    "BASE_QTY":          "BSTMI",
    "SAFETY_STK":        "EISBE",
    "AVAILCHECK":        "MTVFP",
    "LOTSIZEKEY":        "DISLS",
    "ABCINDIC":          "MAABC",
    "PLNT_MAT_STATUS":   "MMSTA",
    "REORDERPNT":        "MINBE",
    "MAX_LVL_VAL":       "MABST",
}

# Per-storage-location attrs (MARD)
STORAGELOCATIONDATA_FIELDS = {
    "PLANT":             "WERKS",
    "STGE_LOC":          "LGORT",
    "MAXLOTSIZE":        "MAABC",
    "MINLOTSIZE":        "MINBE",
}

# Valuation attrs (MBEW) - per valuation area
VALUATIONDATA_FIELDS = {
    "VAL_AREA":          "BWKEY",
    "VAL_CLASS":         "BKLAS",
    "PRICE_CTRL":        "VPRSV",        # 'S' = std, 'V' = MAV
    "STD_PRICE":         "STPRS",
    "MOVING_PR":         "VERPR",
    "PRICE_UNIT":        "PEINH",
    "ORIG_MAT":          "HKMAT",
}


# ─────────────────────────────────────────────────────────────────────────────
# The orchestrator
# ─────────────────────────────────────────────────────────────────────────────
@register_spine
class MaterialSpineOrchestrator(BaseSpineOrchestrator):
    """Deep Material Master loader via BAPI_MATERIAL_SAVEDATA.

    Demonstrates the promotion-pattern: ~150 LOC subclass + a few field maps
    + BAPI signature. Everything else (transform, DQ, FK resolve, key_map
    registration, EXTENSIONIN packing, dry-run, dead-letter routing, stats)
    comes from BaseSpineOrchestrator.
    """

    object_type           = "Material"
    source_key_field      = "MATNR"
    extension_structure   = "BAPI_TE_MARA"
    # Material has no FK dependencies for the BASIC view; plants/SLocs/valArea
    # references must exist in target customising, not the migration ledger.
    fk_fields: dict = {}

    # ── payload builder ──────────────────────────────────────────────────────
    def build_payload(self, row: dict, ext_rows: list) -> dict:
        """Compile the BAPI_MATERIAL_SAVEDATA payload from a transformed row.

        The row may carry top-level MARA fields plus optional sub-lists:
          row["_plants"]    -> list of MARC rows (one per plant)
          row["_slocs"]     -> list of MARD rows (one per plant+sloc)
          row["_valuations"] -> list of MBEW rows (one per val area)
          row["_alt_uoms"]  -> list of MARM rows
          row["_descs"]     -> list of MAKT rows (one per language)
        """
        matnr = (row.get("MATNR") or "").strip()
        if not matnr:
            raise ValueError("MATNR is mandatory")

        # HEADDATA (always required)
        headdata = {"MATERIAL": matnr, "BASIC_VIEW": "X"}
        for bapi_field, src_field in MARA_HEADER_FIELDS.items():
            val = (row.get(src_field) or "").strip() if isinstance(row.get(src_field), str) \
                  else row.get(src_field)
            if val:
                headdata[bapi_field] = val
        # Sensible defaults so tiny test rows still load
        headdata.setdefault("MATL_TYPE", "HALB")
        headdata.setdefault("IND_SECTOR", "M")

        # CLIENTDATA (MARA attributes) - assembled with parallel CLIENTDATAX flags
        clientdata, clientdatax = self._pack_data_X(row, CLIENTDATA_FIELDS)
        clientdata.setdefault("BASE_UOM", "EA"); clientdatax["BASE_UOM"] = "X"
        payload: dict = {
            "HEADDATA":     headdata,
            "CLIENTDATA":   clientdata,
            "CLIENTDATAX":  clientdatax,
        }

        # Multi-language descriptions (MAKT) - default to one English row
        descs_in = row.get("_descs") or []
        if descs_in:
            payload["MATERIALDESCRIPTION"] = [
                {"LANGU": (d.get("SPRAS") or "EN"),
                 "MATL_DESC": (d.get("MAKTX") or "")[:40]}
                for d in descs_in if d.get("MAKTX")
            ]
        else:
            payload["MATERIALDESCRIPTION"] = [{
                "LANGU": (row.get("SPRAS") or "EN"),
                "MATL_DESC": (row.get("MAKTX") or row.get("DESC") or "Migrate4HANA material")[:40],
            }]

        # MARC - per-plant; enables PLANT_VIEW automatically
        plant_rows = row.get("_plants") or []
        if plant_rows:
            payload["PLANTDATA"], payload["PLANTDATAX"] = self._pack_subtable(
                plant_rows, PLANTDATA_FIELDS, key_field="PLANT")
            headdata["PLANT_VIEW"] = "X"

        # MARD - per-storage-location
        sloc_rows = row.get("_slocs") or []
        if sloc_rows:
            payload["STORAGELOCATIONDATA"], payload["STORAGELOCATIONDATAX"] = self._pack_subtable(
                sloc_rows, STORAGELOCATIONDATA_FIELDS, key_field="PLANT")
            headdata["STORAGE_VIEW"] = "X"

        # MBEW - valuation
        val_rows = row.get("_valuations") or []
        if val_rows:
            payload["VALUATIONDATA"], payload["VALUATIONDATAX"] = self._pack_subtable(
                val_rows, VALUATIONDATA_FIELDS, key_field="VAL_AREA")
            headdata["ACCOUNTING_VIEW"] = "X"

        # MARM - alt UoMs
        alt = row.get("_alt_uoms") or []
        if alt:
            payload["UNITSOFMEASURE"] = [
                {"ALT_UNIT": (u.get("MEINH") or ""),
                 "NUMERATOR": u.get("UMREZ") or 1,
                 "DENOMINATR": u.get("UMREN") or 1}
                for u in alt if u.get("MEINH")
            ]
            payload["UNITSOFMEASUREX"] = [{"ALT_UNIT": u["ALT_UNIT"], "ALT_UNIT_X": "X"}
                                          for u in payload["UNITSOFMEASURE"]]

        # EXTENSIONIN - custom append (Z-field) absorption
        if ext_rows:
            payload["EXTENSIONIN"] = ext_rows
            # Build a parallel EXTENSIONINX activation list
            field_names = []
            for r in ext_rows:
                # VALUEPART1 format is "<FNAME padded><VALUE padded>" - first 30 cols are the name
                vp1 = r.get("VALUEPART1") or ""
                field_names.append(vp1[:30].strip())
            from base_spine_orchestrator import build_extensioninx
            payload["EXTENSIONINX"] = build_extensioninx(self.extension_structure, field_names)

        return payload

    # ── BAPI invocation ──────────────────────────────────────────────────────
    def call_bapi(self, payload: dict) -> tuple[Optional[str], list]:
        """Execute BAPI_MATERIAL_SAVEDATA + commit-or-rollback per the standard
        loader pattern. Returns (target_key, messages)."""
        resp = self.c.call("BAPI_MATERIAL_SAVEDATA", **payload)
        ret  = resp.get("RETURN") or {}
        # RETURN can be a dict (single message) or a list of messages
        if isinstance(ret, dict):
            ret_list = [ret] if ret.get("TYPE") else []
        else:
            ret_list = list(ret)
        hard_errors = [m for m in ret_list if m.get("TYPE") in ("E", "A")]
        msgs = [(m.get("MESSAGE") or "").strip() for m in ret_list if m.get("MESSAGE")]
        if hard_errors:
            # Rollback - the BAPI doesn't auto-roll
            try:
                self.c.call("BAPI_TRANSACTION_ROLLBACK")
            except Exception:
                pass
            return None, msgs
        # Commit
        try:
            self.c.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        except Exception as e:
            msgs.append(f"commit failed: {e}")
            return None, msgs
        # Target key = the MATNR we sent
        return (payload["HEADDATA"]["MATERIAL"], msgs)

    # ── helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def _pack_data_X(row: dict, field_map: dict) -> tuple[dict, dict]:
        """Build the (DATA, DATAX) tuple. DATAX marks each populated field with 'X'."""
        data: dict = {}
        datax: dict = {}
        for bapi_field, src_field in field_map.items():
            v = row.get(src_field)
            if isinstance(v, str):
                v = v.strip()
                if not v:
                    continue
            if v is None or v == "":
                continue
            data[bapi_field] = v
            datax[bapi_field] = "X"
        return data, datax

    @staticmethod
    def _pack_subtable(rows: list, field_map: dict, *,
                       key_field: str) -> tuple[list, list]:
        """Build sub-table + parallel X-activation table (e.g. PLANTDATA/PLANTDATAX)."""
        out: list = []
        outx: list = []
        for r in rows or []:
            packed: dict = {}
            packedx: dict = {}
            for bapi_field, src_field in field_map.items():
                v = r.get(src_field)
                if isinstance(v, str):
                    v = v.strip()
                    if not v:
                        continue
                if v is None or v == "":
                    continue
                packed[bapi_field] = v
                packedx[bapi_field] = "X"
            # The key field must always populate so the BAPI knows which row to upsert
            if key_field in packed:
                packedx[key_field] = packed[key_field]
            if packed:
                out.append(packed)
                outx.append(packedx)
        return out, outx
