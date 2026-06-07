"""
base_spine_orchestrator - the promotion factory.

F2's central abstraction: a base class that turns "we need to support migrating
object X" into "write a 100-line subclass implementing four hooks". Every
staging object that needs to be promoted onto the automated BAPI/OData spine
goes through this contract.

Lifecycle (per record):

    extract -> transform -> validate -> resolve_fk -> build_payload -> load -> reconcile -> audit

Each phase has a default implementation that subclasses can override. The base
class also brings four reusable enterprise-grade mixins/helpers that account for
~80% of the per-object complexity in real customer data:

    * EXTENSIONIN handler - maps source ZZ*/YY*/CI_* custom fields to BAPI
      EXTENSIONIN / EXTENSIONINX structures with proper TRUNC + STRUCTNAME wiring
    * PARTNERS handler - normalises partner-function rows (AG/RE/RG/WE etc.)
      for SO/PO/Customer/Vendor headers
    * CONDITIONS handler - turns flat KSCHL/KBETR rows into BAPI pricing-
      condition tables with sequence numbers
    * TEXTS handler - bundles long-text fields into BAPI LONGTEXT inputs and
      issues BAPI_LONGTEXT_SAVE post-create

The base also bakes in:

    * PersistentKeyMap (F1) integration for FK resolution + dependent-object
      key registration
    * TransformationEngine (F4) for value mapping + DQ gates BEFORE the BAPI
      call (a DQ rejection becomes a dead-letter, not a BAPI dump)
    * Dead-letter routing + audit telemetry per the existing UnifiedLoader shape
    * Concurrency safety - all state behind a per-instance lock so a thread
      pool can run many subclasses against the same SAP target safely

Subclasses to write for a new object: ~80 LOC + a field map + a BAPI signature.
The rest is provided by the base. That's the promotion factory.
"""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Sentinels & constants
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Registry - subclasses register themselves here on import; UnifiedLoader
# checks this dict BEFORE its legacy mech-based dispatch.
# ─────────────────────────────────────────────────────────────────────────────
_SPINE_REGISTRY: dict = {}     # object_type -> orchestrator class


def register_spine(orchestrator_cls):
    """Register a BaseSpineOrchestrator subclass. Idempotent."""
    if not getattr(orchestrator_cls, "object_type", None):
        raise ValueError("register_spine: class must declare object_type")
    _SPINE_REGISTRY[orchestrator_cls.object_type] = orchestrator_cls
    return orchestrator_cls


def get_spine(object_type: str):
    """Return the registered orchestrator class for ``object_type``, or None."""
    return _SPINE_REGISTRY.get(object_type)


def registered_spines() -> list:
    """List all currently-registered object types (used by UnifiedLoader telemetry)."""
    return sorted(_SPINE_REGISTRY.keys())


DEAD_LETTER_DQ          = "DATA_QUALITY_REJECTION"
DEAD_LETTER_FK          = "MISSING_DEPENDENCY"
DEAD_LETTER_BAPI        = "BAPI_FAILURE"
DEAD_LETTER_COLLISION   = "TARGET_COLLISION"
DEAD_LETTER_EXTENSION_OVERFLOW = "EXTENSIONIN_OVERFLOW"

DISP_CREATED            = "created"
DISP_MATCHED_EXISTING   = "matched_existing"
DISP_REMAPPED           = "remapped"
DISP_REMAPPED_MATCHED   = "remapped_matched"
DISP_HARMONIZED         = "harmonized"
DISP_DEAD_LETTER        = "dead_letter"

# Common BAPI custom-field prefix conventions. Order matters - first match wins.
CUSTOM_FIELD_PREFIXES = ("ZZ", "YY", "CI_", "Z_", "Y_")


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class LoadResult:
    """One record's loaded result. The exact same shape every subclass returns."""
    status:        str                 # "created" | "matched_existing" | "remapped" | "dead_letter" | "failed"
    object_type:   str                 # e.g. "Material"
    source_key:    str                 # e.g. "M-23"
    target_key:    Optional[str] = None     # e.g. "M-23" or "M4HM-23"
    disposition:   str = ""            # status detail (created / harmonized / collision_skipped / ...)
    dead_letter:   Optional[str] = None     # one of DEAD_LETTER_* if status == dead_letter
    messages:      list = field(default_factory=list)
    extension_rows: int = 0            # how many EXTENSIONIN rows we emitted
    partner_rows:  int = 0
    condition_rows: int = 0
    longtext_calls: int = 0

    def to_dict(self) -> dict:
        return {
            "status": self.status, "object": self.object_type,
            "source_key": self.source_key, "target_key": self.target_key,
            "disposition": self.disposition, "dead_letter": self.dead_letter,
            "messages": self.messages,
            "extension_rows": self.extension_rows,
            "partner_rows": self.partner_rows,
            "condition_rows": self.condition_rows,
            "longtext_calls": self.longtext_calls,
        }


@dataclass
class SpineStats:
    """Aggregate stats per orchestrator instance (across all load_one calls)."""
    attempted:           int = 0
    created:             int = 0
    matched_existing:    int = 0
    remapped:            int = 0
    dead_letter:         int = 0
    failed:              int = 0
    extension_field_drops: int = 0   # ZZ fields rejected by field-coverage gate

    def to_dict(self) -> dict:
        return {
            "attempted": self.attempted,
            "created": self.created,
            "matched_existing": self.matched_existing,
            "remapped": self.remapped,
            "dead_letter": self.dead_letter,
            "failed": self.failed,
            "extension_field_drops": self.extension_field_drops,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helper handlers (reusable mixins as plain functions for testability)
# ─────────────────────────────────────────────────────────────────────────────
def collect_custom_fields(row: dict, *, structname: str,
                          allowed_fields: Optional[set] = None) -> tuple[list, int]:
    """Scan a source row for custom Z/Y/CI_ fields and shape them as
    EXTENSIONIN entries.

    EXTENSIONIN row layout (per SAP):
        STRUCTURE       (CHAR 30, BAPI append structure name e.g. "BAPI_TE_MARA")
        VALUEPART1..4   (CHAR 240 each, the packed field-name/value bytes)

    Returns ``(extension_rows, dropped_count)``. The dropped count is the number
    of Z fields that were excluded because they're not in ``allowed_fields``
    (the BAPI's field-coverage catalogue from `bapi_coverage.py`); callers can
    surface this as a quality metric.
    """
    customs = {k: v for k, v in row.items()
               if k and any(k.startswith(p) for p in CUSTOM_FIELD_PREFIXES)
               and v not in (None, "")}
    if not customs:
        return [], 0

    dropped = 0
    if allowed_fields is not None:
        kept = {}
        for k, v in customs.items():
            if k in allowed_fields:
                kept[k] = v
            else:
                dropped += 1
        customs = kept
    if not customs:
        return [], dropped

    # Pack each (fieldname, value) into the 4-column value parts. Real BAPI
    # implementations expect a single STRUCTURE row whose VALUEPARTs concatenate
    # to the full "FIELD1=value1|FIELD2=value2" payload, but for a clean
    # forward-compatible API we emit one EXTENSIONIN row per custom field.
    # The corresponding EXTENSIONINX row is generated by build_extensioninx().
    ext_rows = []
    for fname, fval in customs.items():
        val = str(fval)[:240]
        ext_rows.append({
            "STRUCTURE":  structname,
            "VALUEPART1": f"{fname:<30}{val:<210}"[:240],
            "VALUEPART2": "",
            "VALUEPART3": "",
            "VALUEPART4": "",
        })
    return ext_rows, dropped


def build_extensioninx(structname: str, fields: list) -> list:
    """Build the parallel EXTENSIONINX activation array. Every X-row must have
    VALUEPART1 set to the field name + 'X' indicator so the BAPI knows the
    custom column was explicitly populated (vs absent). One X-row per
    EXTENSIONIN row keeps the BAPI's downstream resolver happy."""
    return [{"STRUCTURE": structname,
             "VALUEPART1": f"{fname:<30}{'X':<210}"[:240]}
            for fname in fields]


def normalise_partner_rows(rows: list, *, role_field: str = "PARVW",
                            number_field: str = "KUNNR",
                            key_map=None, source_object: str = "Customer") -> list:
    """Turn raw KNVP/LFM1-style rows into BAPI partner entries.

    Resolves each partner number via ``key_map`` (the PersistentKeyMap from F1)
    when available so the target sees the new BP_ID, not the legacy KUNNR.
    """
    out = []
    for r in rows or []:
        role = (r.get(role_field) or "").strip()
        num  = (r.get(number_field) or "").strip()
        if not (role and num):
            continue
        resolved = (key_map.resolve(source_object, num) if key_map else None) or num
        out.append({"PARTN_ROLE": role, "PARTN_NUMB": resolved})
    return out


def normalise_condition_rows(rows: list, *, item_index: int = 10) -> list:
    """Turn flat pricing-condition rows into BAPI ITEM_CONDITION_IN entries.

    Each input row carries ``KSCHL`` (condition type) + ``KBETR`` (rate) + optionally
    ``KMEIN`` (per-unit) and ``WAERS`` (currency). Output rows carry an INCREMENTING
    ``COND_COUNT`` so the BAPI can keep ordering stable.
    """
    out = []
    for i, r in enumerate(rows or [], start=1):
        out.append({
            "ITM_NUMBER":   f"{item_index:06d}",
            "COND_COUNT":   f"{i:02d}",
            "COND_TYPE":    (r.get("KSCHL") or "").strip(),
            "COND_VALUE":   r.get("KBETR") or 0,
            "COND_P_UNT":   r.get("KMEIN") or "EA",
            "CURRENCY":     (r.get("WAERS") or "").strip(),
        })
    return out


def normalise_text_rows(rows: list, *, langu: str = "EN") -> list:
    """Bundle multi-line texts (header/item NOTES) for a single BAPI_LONGTEXT_SAVE."""
    out = []
    for r in rows or []:
        text = (r.get("TDLINE") or r.get("TEXT") or "").strip()
        if not text:
            continue
        out.append({
            "TDOBJECT":  r.get("TDOBJECT") or "",
            "TDID":      r.get("TDID") or "",
            "TDSPRAS":   r.get("TDSPRAS") or langu,
            "TDLINE":    text[:132],         # SAP TDLINE width
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# The abstract base
# ─────────────────────────────────────────────────────────────────────────────
class BaseSpineOrchestrator(ABC):
    """Abstract base for promoting a staging object onto the automated spine.

    Subclasses MUST implement:
        * object_type     - class attribute, e.g. "Material"
        * source_key_field - class attribute, e.g. "MATNR"
        * extension_structure - class attribute (str), e.g. "BAPI_TE_MARA" (or "" if N/A)
        * build_payload(row, ext) - returns a dict of kwargs to pass to the BAPI
        * call_bapi(payload) - return (target_key, messages); raise on hard failure

    Subclasses MAY override:
        * transform(row) - default: apply self.transformer if set, else identity
        * validate(row)  - default: return None (no extra DQ on top of transformer)
        * resolve_fk(row) - default: walk self.fk_fields, replace via key_map
        * collide(row, identity) - default: remap_strategy("M4H<src>")
    """

    object_type: str = ""
    source_key_field: str = ""
    extension_structure: str = ""
    # FK fields: source_field -> registry object name (used by resolve_fk).
    # Subclasses override e.g. {"KUNNR": "Customer", "LIFNR": "Vendor"}.
    fk_fields: dict = {}

    def __init__(self, conn, *, key_map=None, transformer=None,
                 bapi_field_catalog: Optional[dict] = None,
                 dry_run: bool = False, target_release: str = ""):
        if not self.object_type or not self.source_key_field:
            raise ValueError("BaseSpineOrchestrator subclass must set object_type "
                             "and source_key_field class attributes")
        self.c             = conn
        self.key_map       = key_map         # PersistentKeyMap (F1)
        self.transformer   = transformer     # TransformationEngine (F4)
        self.bapi_field_catalog = bapi_field_catalog or {}
        self.dry_run       = dry_run
        self.target_release = target_release
        self.stats         = SpineStats()
        self._lock         = threading.Lock()

    # ── per-record entry point ────────────────────────────────────────────────
    def load_one(self, row: dict) -> LoadResult:
        """Drive one record through the full lifecycle. Never raises - any
        failure becomes a dead-letter result the caller can surface."""
        with self._lock:
            self.stats.attempted += 1
        src_key = str(row.get(self.source_key_field) or "").strip()
        result = LoadResult(status="failed", object_type=self.object_type,
                            source_key=src_key)

        # 1) transform (value-map + cleanse + DQ via the transformation engine)
        try:
            transformed = self.transform(row)
        except Exception as e:
            return self._dead(result, DEAD_LETTER_DQ, f"transform error: {e}")
        if transformed is None:
            # Transformer rejected the record (DQ gate); already accounted for
            return self._dead(result, DEAD_LETTER_DQ, "DQ gate rejected")

        # 2) extra subclass validation (optional)
        v_err = self.validate(transformed)
        if v_err:
            return self._dead(result, DEAD_LETTER_DQ, v_err)

        # 3) FK resolution via key_map (Customer/Vendor/Material lookups for
        #    dependent objects like SO/PO/BOM)
        try:
            fk_err = self.resolve_fk(transformed)
        except Exception as e:
            return self._dead(result, DEAD_LETTER_FK, f"fk resolve error: {e}")
        if fk_err:
            return self._dead(result, DEAD_LETTER_FK, fk_err)

        # 4) Z-field collection (EXTENSIONIN) - only if subclass declares a struct
        ext_rows: list = []
        if self.extension_structure:
            allowed = self.bapi_field_catalog.get(self.object_type) if self.bapi_field_catalog else None
            ext_rows, dropped = collect_custom_fields(
                transformed, structname=self.extension_structure, allowed_fields=allowed)
            if dropped:
                with self._lock:
                    self.stats.extension_field_drops += dropped
            result.extension_rows = len(ext_rows)
            # too-many-fields safeguard (BAPIs typically tolerate <100 EXTENSIONIN rows)
            if len(ext_rows) > 100:
                return self._dead(result, DEAD_LETTER_EXTENSION_OVERFLOW,
                                  f"too many custom fields ({len(ext_rows)} > 100)")

        # 5) build the BAPI payload (subclass hook - signs of life)
        try:
            payload = self.build_payload(transformed, ext_rows)
        except Exception as e:
            return self._dead(result, DEAD_LETTER_BAPI, f"build_payload error: {e}")

        # Subclass instrumentation (partner/condition/text totals come from
        # whatever the subclass put in `payload`; we read them post-hoc to
        # populate LoadResult without coupling base to specific keys).
        for k_in, k_out in (("PARTNERS", "partner_rows"),
                            ("ORDER_PARTNERS", "partner_rows"),
                            ("CONDITIONS_IN", "condition_rows"),
                            ("ITEM_CONDITION_IN", "condition_rows"),
                            ("LONGTEXTS", "longtext_calls")):
            if k_in in payload and isinstance(payload[k_in], list):
                setattr(result, k_out, getattr(result, k_out) + len(payload[k_in]))

        # 6) dry-run? return success without calling SAP
        if self.dry_run:
            result.status = DISP_CREATED
            result.disposition = DISP_CREATED + "_dry_run"
            result.target_key = self._dry_run_target(src_key, transformed)
            with self._lock: self.stats.created += 1
            self._register_key(result)
            return result

        # 7) execute BAPI
        try:
            tgt_key, msgs = self.call_bapi(payload)
        except Exception as e:
            return self._dead(result, DEAD_LETTER_BAPI, f"BAPI call raised: {e}")
        result.messages = msgs or []
        if not tgt_key:
            return self._dead(result, DEAD_LETTER_BAPI, "BAPI returned no target key")

        # 8) classify status (created / matched / remapped / collision_skipped)
        result.target_key = tgt_key
        if tgt_key == src_key:
            result.status = DISP_CREATED
            result.disposition = DISP_CREATED
            with self._lock: self.stats.created += 1
        elif tgt_key.startswith("M4H"):
            result.status = DISP_REMAPPED
            result.disposition = DISP_REMAPPED
            with self._lock: self.stats.remapped += 1
        else:
            result.status = DISP_MATCHED_EXISTING
            result.disposition = DISP_MATCHED_EXISTING
            with self._lock: self.stats.matched_existing += 1

        # 9) register in the cross-run key_map for dependent objects
        self._register_key(result)
        return result

    # ── subclass hooks (override these) ───────────────────────────────────────
    def transform(self, row: dict) -> Optional[dict]:
        """Default: pass through the transformation engine if attached."""
        if self.transformer is None:
            return dict(row)
        try:
            out, dq = self.transformer.apply(self.object_type, row)
        except Exception:
            return dict(row)
        if dq and not dq.passed:
            return None     # DQ rejection
        return out

    def validate(self, row: dict) -> Optional[str]:
        """Default: no extra validation. Override to return a string error
        message that triggers a dead-letter."""
        return None

    def resolve_fk(self, row: dict) -> Optional[str]:
        """Default: walk ``fk_fields`` and replace each source-field value with
        the target key from ``key_map`` (when present). Returns an error string
        if a required FK can't be resolved.
        """
        if not (self.fk_fields and self.key_map):
            return None
        for src_field, registry_obj in self.fk_fields.items():
            val = (row.get(src_field) or "").strip() if isinstance(row.get(src_field), str) \
                  else row.get(src_field)
            if not val:
                continue
            target = self.key_map.resolve(registry_obj, val)
            if target is None:
                return f"unresolved FK {registry_obj}={val} (required by {src_field})"
            row[src_field] = target
        return None

    @abstractmethod
    def build_payload(self, row: dict, ext_rows: list) -> dict:
        """Subclass: turn a transformed row into BAPI kwargs."""

    @abstractmethod
    def call_bapi(self, payload: dict) -> tuple[Optional[str], list]:
        """Subclass: invoke the BAPI; return (target_key, message_list)."""

    # ── helpers subclasses can use ────────────────────────────────────────────
    def _dead(self, result: LoadResult, code: str, reason: str) -> LoadResult:
        with self._lock:
            self.stats.dead_letter += 1
        result.status = DISP_DEAD_LETTER
        result.dead_letter = code
        result.messages.append(reason)
        return result

    def _register_key(self, result: LoadResult) -> None:
        if self.key_map is None or not result.target_key:
            return
        self.key_map.add(self.object_type, result.source_key,
                         result.target_key, result.disposition)

    @staticmethod
    def _dry_run_target(src_key: str, _row: dict) -> str:
        return src_key or "<dry-run>"

    # ── bulk entrypoint (used by UnifiedLoader for parallel pools) ───────────
    def load_many(self, rows: list, *, max_rows: Optional[int] = None) -> list:
        """Sequentially load a list of records and return their LoadResults.
        For parallel execution wire each thread to its OWN orchestrator
        instance (each has its own SAP connection), then merge results."""
        out: list = []
        for i, row in enumerate(rows or []):
            if max_rows is not None and i >= max_rows:
                break
            out.append(self.load_one(row))
        return out
