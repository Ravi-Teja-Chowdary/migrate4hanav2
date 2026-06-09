"""
mc_file_exporter - SAP Migration Cockpit file-lane exporter.

Single framework covering the ~20 catalog objects that DON'T have a usable
direct create BAPI (probed and documented in BREADTH_TRACKER.md). These
intentionally route to SAP's Migration Cockpit XML/CSV templates rather
than to a per-object spine subclass.

The exporter:
  1. Pulls source rows from the extracted staging tier
  2. Validates each row against the MC object's template column spec
  3. Writes a UTF-8 CSV / XML conforming to the MC template
  4. Uploads to the customer's staging bucket under a canonical key
     so the customer's CSV->MC upload step is a single mc.upload call

A "MigrationCockpitFile" pseudo-spine is registered in the
BaseSpineOrchestrator registry so UnifiedLoader.load_object() routes
file-lane objects through the SAME interface as BAPI-lane objects --
caller sees a uniform load_result shape with `mechanism = "mc_file/..."`.

Covered objects (registered at import time):
  Routing · ActivityType · StatisticalKeyFigure · CommitmentItem · GLAccount
  TaskList · InspPlan · InspMethod · ServiceMaster · SourceList · HouseBank
  HouseBankAccount · ConditionRecord · CustomerHierarchy · BOMItem · Network
  WBSElement · OrgUnit · Position · EmployeeAction
"""
from __future__ import annotations

import csv
import io
import json
from typing import Optional

from base_spine_orchestrator import (
    BaseSpineOrchestrator, register_spine,
    DISP_CREATED, DEAD_LETTER_DQ,
)


# ─────────────────────────────────────────────────────────────────────────────
# MC template registry: (object_type, csv_columns, mandatory_columns,
#                        mc_template_name, target_table)
# Drawn from the standard SAP Migration Cockpit catalogue (S/4 2023);
# customer-specific Z-columns are absorbed via extension fields.
# ─────────────────────────────────────────────────────────────────────────────
MC_TEMPLATES: dict = {
    "Routing": {
        "csv_columns":         ["PLNNR", "PLNAL", "WERKS", "MATNR",
                                 "OBJEKT", "ARBPL", "USAGE", "VERWE"],
        "mandatory":           ["PLNNR", "WERKS", "MATNR", "ARBPL"],
        "template":            "MC_PP_ROUTING_TEMPLATE_V1",
        "target_table":        "PLKO",
    },
    "ActivityType": {
        "csv_columns":         ["KOKRS", "LSTAR", "TXT", "ATYP", "OUTPUT_UNIT"],
        "mandatory":           ["KOKRS", "LSTAR", "ATYP"],
        "template":            "MC_CO_ACTIVITY_TYPE_V1",
        "target_table":        "CSLA",
    },
    "StatisticalKeyFigure": {
        "csv_columns":         ["KOKRS", "STAGR", "TXT", "MEINS"],
        "mandatory":           ["KOKRS", "STAGR"],
        "template":            "MC_CO_STAT_KEY_FIG_V1",
        "target_table":        "TKA03",
    },
    "CommitmentItem": {
        "csv_columns":         ["FIKRS", "FIPEX", "TXT", "FIPLEVEL", "FIPSTATUS"],
        "mandatory":           ["FIKRS", "FIPEX"],
        "template":            "MC_FM_COMMITMENT_ITEM_V1",
        "target_table":        "FMCI",
    },
    "GLAccount": {
        "csv_columns":         ["KTOPL", "SAKNR", "TXT", "KTOKS", "MITKZ"],
        "mandatory":           ["KTOPL", "SAKNR"],
        "template":            "MC_FI_GL_ACCOUNT_V1",
        "target_table":        "SKA1",
    },
    "TaskList": {
        "csv_columns":         ["PLNTY", "PLNNR", "PLNAL", "MATNR", "WERKS"],
        "mandatory":           ["PLNTY", "PLNNR", "WERKS"],
        "template":            "MC_PM_TASK_LIST_V1",
        "target_table":        "PLKO",
    },
    "InspPlan": {
        "csv_columns":         ["PLNNR", "PLNAL", "WERKS", "PRUEFART", "STATU"],
        "mandatory":           ["PLNNR", "WERKS"],
        "template":            "MC_QM_INSP_PLAN_V1",
        "target_table":        "PLKO",
    },
    "InspMethod": {
        "csv_columns":         ["WERKS", "METHODE", "VERWMETH", "TXT"],
        "mandatory":           ["WERKS", "METHODE"],
        "template":            "MC_QM_INSP_METHOD_V1",
        "target_table":        "QPMT",
    },
    "ServiceMaster": {
        "csv_columns":         ["ASNUM", "TXT", "KTEXT", "MEINS", "MATKL"],
        "mandatory":           ["ASNUM"],
        "template":            "MC_MM_SERVICE_MASTER_V1",
        "target_table":        "ASMD",
    },
    "SourceList": {
        "csv_columns":         ["MATNR", "WERKS", "LIFNR", "EKORG", "VDATU", "BDATU"],
        "mandatory":           ["MATNR", "WERKS", "LIFNR", "EKORG"],
        "template":            "MC_MM_SOURCE_LIST_V1",
        "target_table":        "EORD",
    },
    "HouseBank": {
        "csv_columns":         ["BUKRS", "HBKID", "BANKS", "BANKL"],
        "mandatory":           ["BUKRS", "HBKID", "BANKS", "BANKL"],
        "template":            "MC_FI_HOUSE_BANK_V1",
        "target_table":        "T012",
    },
    "HouseBankAccount": {
        "csv_columns":         ["BUKRS", "HBKID", "HKTID", "BANKN", "BKONT", "WAERS"],
        "mandatory":           ["BUKRS", "HBKID", "HKTID"],
        "template":            "MC_FI_HOUSE_BANK_ACCOUNT_V1",
        "target_table":        "T012K",
    },
    "ConditionRecord": {
        "csv_columns":         ["KSCHL", "VKORG", "VTWEG", "KUNNR", "MATNR",
                                 "KBETR", "WAERS", "DATBI"],
        "mandatory":           ["KSCHL", "KBETR"],
        "template":            "MC_SD_CONDITION_RECORD_V1",
        "target_table":        "KONP",
    },
    "CustomerHierarchy": {
        "csv_columns":         ["HITYP", "KUNNR", "HKUNNR", "VKORG",
                                 "VTWEG", "SPART", "DATAB", "DATBI"],
        "mandatory":           ["HITYP", "KUNNR", "HKUNNR"],
        "template":            "MC_SD_CUSTOMER_HIERARCHY_V1",
        "target_table":        "KNVH",
    },
    "BOMItem": {
        "csv_columns":         ["STLNR", "STLKN", "POSNR", "IDNRK", "MENGE", "MEINS"],
        "mandatory":           ["STLNR", "POSNR", "IDNRK"],
        "template":            "MC_PP_BOM_ITEM_V1",
        "target_table":        "STPO",
    },
    "Network": {
        "csv_columns":         ["AUFNR", "AUART", "WERKS", "TXT", "PRIO"],
        "mandatory":           ["AUFNR", "AUART", "WERKS"],
        "template":            "MC_PS_NETWORK_V1",
        "target_table":        "AUFK",
    },
    "WBSElement": {
        "csv_columns":         ["PSPID", "POSID", "POST1", "STUFE", "PRART"],
        "mandatory":           ["PSPID", "POSID"],
        "template":            "MC_PS_WBS_ELEMENT_V1",
        "target_table":        "PRPS",
    },
    "OrgUnit": {
        "csv_columns":         ["OBJID", "STELL", "PLANS", "BEGDA", "ENDDA"],
        "mandatory":           ["OBJID"],
        "template":            "MC_HR_ORG_UNIT_V1",
        "target_table":        "HRP1000",
    },
    "Position": {
        "csv_columns":         ["PLANS", "STELL", "ORGEH", "BEGDA", "ENDDA"],
        "mandatory":           ["PLANS"],
        "template":            "MC_HR_POSITION_V1",
        "target_table":        "HRP1000",
    },
    "EmployeeAction": {
        "csv_columns":         ["PERNR", "MASSN", "MASSG", "BEGDA", "ENDDA"],
        "mandatory":           ["PERNR", "MASSN"],
        "template":            "MC_HR_EMPLOYEE_ACTION_V1",
        "target_table":        "PA0000",
    },
}


def _make_mc_file_class(obj_name: str, spec: dict):
    """Factory for a MigrationCockpitFile spine subclass per object_type.

    The subclass:
      * registers itself under object_type
      * implements build_payload to ASSEMBLE a CSV record (no BAPI call)
      * implements call_bapi as a NO-BAPI passthrough that just records the
        row was queued -- actual upload happens at end-of-run via flush()
        triggered by the lambda handler
    """
    _source_key = spec["mandatory"][0] if spec["mandatory"] else spec["csv_columns"][0]

    class _MCFileSpine(BaseSpineOrchestrator):
        object_type           = obj_name
        source_key_field      = _source_key
        extension_structure   = ""    # MC file lane doesn't use BAPI EXTENSIONIN
        fk_fields: dict       = {}

        # Buffer of accumulated rows -- flushed at end of run
        _row_buffer: list = []

        def validate(self, row: dict) -> Optional[str]:
            missing = [c for c in spec["mandatory"]
                        if not (row.get(c) or "").strip()]
            if missing:
                return f"mandatory columns missing: {','.join(missing)}"
            return None

        def build_payload(self, row: dict, ext_rows: list) -> dict:
            # Project the source row onto the MC template's column set
            record = {c: (row.get(c) or "") for c in spec["csv_columns"]}
            # Z columns passed through as a JSON sidecar (the upload step
            # may map them via the MC customizing extension layer)
            customs = {k: v for k, v in row.items()
                        if k and not k.startswith("_")
                        and any(k.startswith(p) for p in ("ZZ", "YY", "CI_", "Z_", "Y_"))}
            return {"record": record, "customs": customs, "_src": record[self.source_key_field]}

        def call_bapi(self, payload: dict) -> tuple:
            src = payload.pop("_src", "")
            record = payload["record"]
            customs = payload["customs"]
            # Append to buffer; the actual S3 write happens at flush time
            self._row_buffer.append({"record": record, "customs": customs})
            vk = {"table": spec["target_table"],
                  "key":   {self.source_key_field: src}}
            return src, [f"queued for MC template {spec['template']}"], DISP_CREATED, vk

        @classmethod
        def flush_to_s3(cls, s3_client, bucket: str, run_id: str,
                         tenant_slug: str = "default") -> dict:
            """Write the accumulated buffer to S3 as CSV under the customer's
            staging path. Returns the S3 URI + row count + any sidecar
            blob written for custom Z columns."""
            if not cls._row_buffer:
                return {"object": cls.object_type, "rows": 0, "uri": None}
            # Main CSV
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=spec["csv_columns"])
            w.writeheader()
            for r in cls._row_buffer:
                w.writerow(r["record"])
            csv_key = (f"tenants/{tenant_slug}/runs/{run_id}/mc_file/"
                        f"{cls.object_type}.csv")
            s3_client.put_object(Bucket=bucket, Key=csv_key,
                                  Body=buf.getvalue().encode("utf-8"),
                                  ContentType="text/csv")
            # Custom Z column sidecar (optional)
            customs_present = any(r["customs"] for r in cls._row_buffer)
            customs_key = None
            if customs_present:
                sidecar = [{"key": r["record"].get(cls.source_key_field),
                             "customs": r["customs"]}
                            for r in cls._row_buffer if r["customs"]]
                customs_key = (f"tenants/{tenant_slug}/runs/{run_id}/mc_file/"
                                f"{cls.object_type}.customs.json")
                s3_client.put_object(Bucket=bucket, Key=customs_key,
                                      Body=json.dumps(sidecar, indent=2).encode("utf-8"),
                                      ContentType="application/json")
            result = {
                "object":     cls.object_type,
                "template":   spec["template"],
                "rows":       len(cls._row_buffer),
                "uri":        f"s3://{bucket}/{csv_key}",
                "customs_uri": (f"s3://{bucket}/{customs_key}" if customs_key else None),
                "target_table": spec["target_table"],
            }
            cls._row_buffer = []   # reset for next run
            return result

    _MCFileSpine.__name__ = f"MCFile_{obj_name}"
    return _MCFileSpine


# Register all 20 MC file objects at import time
_REGISTERED_MC_OBJECTS = []
for _obj, _spec in MC_TEMPLATES.items():
    _cls = _make_mc_file_class(_obj, _spec)
    register_spine(_cls)
    _REGISTERED_MC_OBJECTS.append(_obj)


def flush_all(s3_client, bucket: str, run_id: str, tenant_slug: str = "default") -> list:
    """Flush every MC-file pseudo-spine that has accumulated rows. Returns a
    list of per-object results (uri + row count + template name)."""
    from base_spine_orchestrator import _SPINE_REGISTRY
    results = []
    for obj in _REGISTERED_MC_OBJECTS:
        cls = _SPINE_REGISTRY.get(obj)
        if cls is None:
            continue
        r = cls.flush_to_s3(s3_client, bucket, run_id, tenant_slug)
        if r["rows"] > 0:
            results.append(r)
    return results


def registered_objects() -> list:
    """Roll-call of MC-file-lane objects on the spine registry."""
    return list(_REGISTERED_MC_OBJECTS)
