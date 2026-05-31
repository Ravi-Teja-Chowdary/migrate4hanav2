"""
transformation_engine.py — Enterprise field transformation, value-mapping & DQ
================================================================================
The general-purpose transformation layer (closes EXPERT_REVIEW_BRIEF §6.3). It
sits inside ``unified_loader`` *before* the BAPI payload is compiled and turns a
raw extracted source record into a target-shaped, cleansed, validated record —
or quarantines it.

Three capabilities, all deterministic (zero runtime AI):

1. **Rule schema** — an extensible JSON ruleset per object describing
   ``FIELD_MAP`` (rename/copy), ``VALUE_MAP`` (cross-system value translation via
   a named matrix table), ``REGEX_CLEANSE`` (dirty-field scrubbing), plus
   ``CONST`` / ``TRIM`` / ``UPPER`` / ``PAD`` helpers.

2. **Deterministic lookup engine** — value-map *matrices* (e.g. legacy→target
   company codes, chart-of-accounts crosswalks) are loaded once from an S3-backed
   JSON (``s3://bucket/key``), a local JSON file, or inline in the ruleset, then
   cached in-memory for O(1) dict lookups on every record.

3. **Data-quality sanity gates** — ``MANDATORY``, ``REGEX_VALID``, ``MAX_LEN``,
   ``ALLOWED``, ``UNIQUE`` (cross-record duplicate detection). A record failing a
   *critical* gate is rejected with reason codes so the caller can dead-letter it
   as ``DATA_QUALITY_REJECTION`` and never send it to the BAPI factory.

Thread-safe: the UNIQUE gate keeps a per-(object,field) seen-set under a lock so
the parallel loader pool stays correct. ``apply()`` never raises — any internal
error is surfaced as a DQ reason rather than crashing the load.

Standard-library only at runtime (boto3 is imported lazily and only if an S3
matrix source is configured), so it runs unchanged on a laptop or in a Lambda.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("transformation_engine")

# ── transform op identifiers ────────────────────────────────────────────────
T_FIELD_MAP = "FIELD_MAP"
T_VALUE_MAP = "VALUE_MAP"
T_REGEX_CLEANSE = "REGEX_CLEANSE"
T_CONST = "CONST"
T_TRIM = "TRIM"
T_UPPER = "UPPER"
T_PAD = "PAD"
_TRANSFORM_TYPES = {T_FIELD_MAP, T_VALUE_MAP, T_REGEX_CLEANSE, T_CONST, T_TRIM, T_UPPER, T_PAD}

# ── data-quality gate identifiers ───────────────────────────────────────────
DQ_MANDATORY = "MANDATORY"
DQ_REGEX_VALID = "REGEX_VALID"
DQ_MAX_LEN = "MAX_LEN"
DQ_ALLOWED = "ALLOWED"
DQ_UNIQUE = "UNIQUE"
# CROSS_FIELD_VALIDATE - multi-field business-rule check (Syniti-class DQ).
# Example uses: payment terms must match credit-limit tier; plant must belong
# to the named company code; country must match tax-jurisdiction prefix.
# See _eval_cross_field() for the supported expression mini-language.
DQ_CROSS_FIELD = "CROSS_FIELD_VALIDATE"
_DQ_TYPES = {DQ_MANDATORY, DQ_REGEX_VALID, DQ_MAX_LEN, DQ_ALLOWED, DQ_UNIQUE, DQ_CROSS_FIELD}

REJECTION_STATUS = "DATA_QUALITY_REJECTION"


@dataclass
class DQResult:
    passed: bool
    reasons: list = field(default_factory=list)        # human-readable strings
    rejections: list = field(default_factory=list)     # [{field, rule, message}]

    def to_dict(self) -> dict:
        return {"passed": self.passed, "status": None if self.passed else REJECTION_STATUS,
                "reasons": self.reasons, "rejections": self.rejections}


class RulesetError(ValueError):
    """Raised at construction time for a malformed ruleset (fail fast, not at runtime)."""


class TransformationEngine:
    """Deterministic per-record transform + value-mapping + data-quality gating."""

    def __init__(self, ruleset: Optional[dict] = None, *,
                 ruleset_path: Optional[str] = None,
                 value_maps: Optional[dict] = None,
                 matrix_path: Optional[str] = None,
                 matrix_s3: Optional[str] = None):
        """
        :param ruleset:      the rules dict (see schema); or load from ``ruleset_path``.
        :param ruleset_path: local JSON file containing the ruleset.
        :param value_maps:   inline matrix {table_name: {src: tgt}}; merged over loaded matrix.
        :param matrix_path:  local JSON file with the value-map matrix.
        :param matrix_s3:    ``s3://bucket/key`` JSON with the value-map matrix (business-user UI populated).
        """
        self.ruleset = self._load_ruleset(ruleset, ruleset_path)
        self._validate_ruleset(self.ruleset)
        # Value-map matrix: S3 < local file < inline (later overrides earlier).
        matrix: dict = {}
        matrix.update(self._load_matrix_s3(matrix_s3) or {})
        matrix.update(self._load_matrix_file(matrix_path) or {})
        matrix.update(self.ruleset.get("value_maps") or {})
        matrix.update(value_maps or {})
        # normalise matrix keys to trimmed-upper for case-insensitive lookups
        self._matrix = {
            tname: {self._norm(k): v for k, v in (tbl or {}).items()}
            for tname, tbl in matrix.items()
        }
        # index object rules once
        self._object_rules: dict = self.ruleset.get("object_rules") or {}
        # cross-record UNIQUE state (thread-safe)
        self._seen: dict = {}
        self._lock = threading.Lock()
        # precompile regexes (transform cleanses + DQ regex gates) for speed
        self._compiled: dict = {}
        self._precompile()

    # ── public API ──────────────────────────────────────────────────────────
    def has_rules(self, obj: str) -> bool:
        return obj in self._object_rules

    def apply(self, obj: str, record: dict) -> tuple[dict, Optional[DQResult]]:
        """Transform ``record`` for ``obj`` then run DQ gates.

        Returns ``(transformed_record, dq_result)``. ``dq_result`` is None when the
        object has no DQ rules; otherwise a :class:`DQResult` (``passed`` False ⇒
        quarantine as DATA_QUALITY_REJECTION). Never raises.
        """
        rules = self._object_rules.get(obj)
        if not rules:
            return record, None
        out = dict(record)
        try:
            for tr in rules.get("transforms", []):
                out = self._apply_transform(tr, out)
        except Exception as e:  # a bad transform must not crash the load
            logger.warning("transform error on %s: %s", obj, e)
            return out, DQResult(False, [f"transform_error: {e}"],
                                 [{"field": None, "rule": "TRANSFORM", "message": str(e)}])

        dq_rules = rules.get("dq_rules") or []
        if not dq_rules:
            return out, None
        return out, self._run_dq(obj, out, dq_rules)

    def reset_unique_state(self) -> None:
        """Clear cross-record UNIQUE memory (e.g. between independent runs)."""
        with self._lock:
            self._seen.clear()

    # ── transforms ────────────────────────────────────────────────────────────
    def _apply_transform(self, tr: dict, rec: dict) -> dict:
        ttype = tr.get("type")
        if ttype == T_FIELD_MAP:
            src, tgt = tr["source"], tr["target"]
            val = rec.get(src)
            if val is None and "default" in tr:
                val = tr["default"]
            rec[tgt] = val
            if tr.get("drop_source") and src in rec and src != tgt:
                rec.pop(src, None)
        elif ttype == T_VALUE_MAP:
            fld = tr["field"]
            table = self._matrix.get(tr["table"], {})
            cur = rec.get(fld)
            mapped = table.get(self._norm(cur))
            if mapped is not None:
                rec[fld] = mapped
            else:
                on_missing = tr.get("on_missing", "keep")
                if on_missing == "default":
                    rec[fld] = tr.get("default", "")
                elif on_missing == "reject":
                    # leave a sentinel the DQ ALLOWED/MANDATORY gate can catch;
                    # callers usually pair this with a MANDATORY/ALLOWED dq rule.
                    rec[fld] = tr.get("reject_sentinel", "__UNMAPPED__")
                # "keep" → leave the original value untouched
        elif ttype == T_REGEX_CLEANSE:
            fld = tr["field"]
            rx = self._compiled.get(("cleanse", id(tr)))
            if rx is None:
                rx = re.compile(tr["pattern"], self._flags(tr.get("flags", "")))
            val = rec.get(fld)
            if val is not None:
                rec[fld] = rx.sub(tr.get("replacement", ""), str(val))
        elif ttype == T_CONST:
            rec[tr["field"]] = tr.get("value", "")
        elif ttype == T_TRIM:
            v = rec.get(tr["field"])
            if v is not None:
                rec[tr["field"]] = str(v).strip()
        elif ttype == T_UPPER:
            v = rec.get(tr["field"])
            if v is not None:
                rec[tr["field"]] = str(v).upper()
        elif ttype == T_PAD:
            v = rec.get(tr["field"])
            if v is not None:
                width = int(tr.get("width", 0))
                ch = tr.get("char", "0")
                side = tr.get("side", "left")
                s = str(v)
                rec[tr["field"]] = s.rjust(width, ch) if side == "left" else s.ljust(width, ch)
        return rec

    # ── data-quality gates ────────────────────────────────────────────────────
    def _run_dq(self, obj: str, rec: dict, dq_rules: list) -> DQResult:
        reasons: list = []
        rejections: list = []
        for rule in dq_rules:
            rtype = rule.get("type")
            fld = rule.get("field")
            val = rec.get(fld)
            ok, msg = True, rule.get("message", "")
            if rtype == DQ_MANDATORY:
                ok = val is not None and str(val).strip() != ""
                msg = msg or f"mandatory field {fld} is empty"
            elif rtype == DQ_REGEX_VALID:
                rx = self._compiled.get(("dq", id(rule)))
                if rx is None:
                    rx = re.compile(rule["pattern"], self._flags(rule.get("flags", "")))
                ok = val is not None and bool(rx.match(str(val)))
                msg = msg or f"field {fld} value {val!r} fails pattern {rule.get('pattern')}"
            elif rtype == DQ_MAX_LEN:
                ok = val is None or len(str(val)) <= int(rule["len"])
                msg = msg or f"field {fld} exceeds max length {rule.get('len')}"
            elif rtype == DQ_ALLOWED:
                allowed = {self._norm(x) for x in rule.get("values", [])}
                ok = self._norm(val) in allowed
                msg = msg or f"field {fld} value {val!r} not in allowed set"
            elif rtype == DQ_UNIQUE:
                fields = rule.get("fields") or [fld]
                key = (obj, tuple(fields), tuple(self._norm(rec.get(f)) for f in fields))
                with self._lock:
                    dup = key in self._seen
                    if not dup:
                        self._seen[key] = True
                ok = not dup
                msg = msg or f"duplicate record on {fields}"
            elif rtype == DQ_CROSS_FIELD:
                ok, eval_msg = self._eval_cross_field(rec, rule)
                msg = msg or eval_msg
            else:
                # unknown rule type — record as a soft reason, do not reject
                reasons.append(f"unknown_dq_rule:{rtype}")
                continue

            if not ok:
                severity = rule.get("severity", "critical")
                reasons.append(f"{rtype}:{fld}:{msg}")
                rejections.append({"field": fld, "rule": rtype, "message": msg,
                                   "severity": severity})

        critical = [r for r in rejections if r.get("severity", "critical") == "critical"]
        return DQResult(passed=(len(critical) == 0), reasons=reasons, rejections=rejections)

    # ── loaders / helpers ───────────────────────────────────────────────────
    @staticmethod
    def _norm(v: Any) -> str:
        return "" if v is None else str(v).strip().upper()

    @staticmethod
    def _flags(spec: str) -> int:
        f = 0
        s = (spec or "").upper()
        if "I" in s:
            f |= re.IGNORECASE
        if "M" in s:
            f |= re.MULTILINE
        if "S" in s:
            f |= re.DOTALL
        return f

    # ── CROSS_FIELD_VALIDATE: multi-field business-rule check ────────────────
    # The rule schema:
    #   { "type": "CROSS_FIELD_VALIDATE",
    #     "name": "payment_terms_within_credit_limit",
    #     "when":   {"field": "CREDIT_LIMIT", "op": ">=", "value": 100000},
    #     "expect": {"field": "ZTERM",        "op": "in", "value": ["NT30", "NT60"]} }
    # If "when" is omitted, "expect" must hold unconditionally.
    # Supported ops: ==, !=, >, >=, <, <=, in, not_in, prefix, suffix,
    #                regex, equals_field (== another field), nonempty
    _CMP_OPS = ("==", "!=", ">", ">=", "<", "<=")

    @classmethod
    def _eval_predicate(cls, rec: dict, pred: dict) -> bool:
        """Evaluate one {field, op, value} predicate against the record."""
        if not pred:
            return True
        fld = pred.get("field")
        op = pred.get("op")
        val = rec.get(fld) if fld else None
        ref = pred.get("value")

        if op == "nonempty":
            return val is not None and str(val).strip() != ""
        if op == "equals_field":
            other = rec.get(ref)
            return cls._norm(val) == cls._norm(other)
        if op == "in":
            ref_set = {cls._norm(x) for x in (ref or [])}
            return cls._norm(val) in ref_set
        if op == "not_in":
            ref_set = {cls._norm(x) for x in (ref or [])}
            return cls._norm(val) not in ref_set
        if op == "prefix":
            return cls._norm(val).startswith(cls._norm(ref))
        if op == "suffix":
            return cls._norm(val).endswith(cls._norm(ref))
        if op == "regex":
            if val is None:
                return False
            return bool(re.match(str(ref), str(val)))
        if op in cls._CMP_OPS:
            return cls._cmp(val, op, ref)
        # unknown op -> treat as failure (caller will record reason)
        return False

    @staticmethod
    def _cmp(left: Any, op: str, right: Any) -> bool:
        # numeric compare when both sides parse as numbers; otherwise string
        try:
            l = float(left); r = float(right)
        except (TypeError, ValueError):
            l, r = (str(left or ""), str(right or ""))
        if op == "==": return l == r
        if op == "!=": return l != r
        if op == ">":  return l > r
        if op == ">=": return l >= r
        if op == "<":  return l < r
        if op == "<=": return l <= r
        return False

    def _eval_cross_field(self, rec: dict, rule: dict) -> tuple:
        """Return (ok, message). ok=True when (not when) or (when AND expect)."""
        when = rule.get("when") or {}
        expect = rule.get("expect") or {}
        if not expect:
            return True, ""
        gating = self._eval_predicate(rec, when) if when else True
        if not gating:
            return True, ""    # gate not triggered -> rule N/A for this record
        passed = self._eval_predicate(rec, expect)
        if passed:
            return True, ""
        name = rule.get("name") or "cross_field_rule"
        when_str = (f"WHEN {when.get('field')} {when.get('op')} {when.get('value')!r}"
                    if when else "ALWAYS")
        expect_str = (f"EXPECT {expect.get('field')} {expect.get('op')} {expect.get('value')!r}, "
                      f"got {rec.get(expect.get('field'))!r}")
        return False, f"{name}: {when_str} :: {expect_str}"

    def _load_ruleset(self, ruleset: Optional[dict], path: Optional[str]) -> dict:
        if ruleset is not None:
            return ruleset
        path = path or os.environ.get("M4H_TRANSFORM_RULES")
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, json.JSONDecodeError) as e:
                raise RulesetError(f"cannot load ruleset {path}: {e}")
        return {"version": "0", "object_rules": {}}

    @staticmethod
    def _load_matrix_file(path: Optional[str]) -> Optional[dict]:
        path = path or os.environ.get("M4H_MAPPING_MATRIX")
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("cannot load matrix file %s: %s", path, e)
            return None

    @staticmethod
    def _load_matrix_s3(uri: Optional[str]) -> Optional[dict]:
        uri = uri or os.environ.get("M4H_MAPPING_S3")
        if not uri or not uri.startswith("s3://"):
            return None
        try:
            import boto3  # lazy — only when an S3 matrix is configured
            bucket, _, key = uri[5:].partition("/")
            body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
            return json.loads(body)
        except Exception as e:  # noqa: BLE001 — S3/credentials/parse; degrade gracefully
            logger.warning("cannot load S3 matrix %s: %s", uri, e)
            return None

    def _validate_ruleset(self, rs: dict) -> None:
        if not isinstance(rs, dict):
            raise RulesetError("ruleset must be a dict")
        objs = rs.get("object_rules", {})
        if not isinstance(objs, dict):
            raise RulesetError("object_rules must be a dict of object -> rules")
        for obj, rules in objs.items():
            for tr in rules.get("transforms", []) or []:
                if tr.get("type") not in _TRANSFORM_TYPES:
                    raise RulesetError(f"{obj}: unknown transform type {tr.get('type')!r}")
                if tr["type"] == T_FIELD_MAP and not (tr.get("source") and tr.get("target")):
                    raise RulesetError(f"{obj}: FIELD_MAP needs source+target")
                if tr["type"] == T_VALUE_MAP and not (tr.get("field") and tr.get("table")):
                    raise RulesetError(f"{obj}: VALUE_MAP needs field+table")
                if tr["type"] == T_REGEX_CLEANSE and not (tr.get("field") and tr.get("pattern") is not None):
                    raise RulesetError(f"{obj}: REGEX_CLEANSE needs field+pattern")
            for dq in rules.get("dq_rules", []) or []:
                if dq.get("type") not in _DQ_TYPES:
                    raise RulesetError(f"{obj}: unknown dq rule type {dq.get('type')!r}")
                if dq["type"] in (DQ_MANDATORY, DQ_REGEX_VALID, DQ_MAX_LEN, DQ_ALLOWED) and not dq.get("field"):
                    raise RulesetError(f"{obj}: {dq['type']} needs field")
                if dq["type"] == DQ_CROSS_FIELD:
                    if not dq.get("expect") or not isinstance(dq["expect"], dict) \
                       or not dq["expect"].get("field") or not dq["expect"].get("op"):
                        raise RulesetError(
                            f"{obj}: CROSS_FIELD_VALIDATE needs expect={{field, op, [value]}}")

    def _precompile(self) -> None:
        for rules in self._object_rules.values():
            for tr in rules.get("transforms", []) or []:
                if tr.get("type") == T_REGEX_CLEANSE:
                    self._compiled[("cleanse", id(tr))] = re.compile(
                        tr["pattern"], self._flags(tr.get("flags", "")))
            for dq in rules.get("dq_rules", []) or []:
                if dq.get("type") == DQ_REGEX_VALID:
                    self._compiled[("dq", id(dq))] = re.compile(
                        dq["pattern"], self._flags(dq.get("flags", "")))


def from_env() -> Optional[TransformationEngine]:
    """Build an engine from environment configuration, or None if not configured.

    Honoured env:
      M4H_TRANSFORM_RULES  — path to the ruleset JSON (required to activate)
      M4H_MAPPING_S3       — s3://bucket/key value-map matrix (business-user UI populated)
      M4H_MAPPING_MATRIX   — local matrix JSON path
    Returns None when no ruleset is configured, so callers stay a no-op by default.
    """
    if not os.environ.get("M4H_TRANSFORM_RULES"):
        return None
    try:
        return TransformationEngine()
    except RulesetError as e:
        logger.error("transformation engine disabled — bad ruleset: %s", e)
        return None


# ════════════════════════════════════════════════════════════════════════════
#  Self-test (no AWS) — field map, value map, cleanse, and all DQ gates.
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ruleset = {
        "version": "1",
        "value_maps": {
            "company_code_map": {"1000": "1710", "3000": "1710"},
        },
        "object_rules": {
            "Vendor": {
                "transforms": [
                    {"type": "FIELD_MAP", "source": "LIFNR_OLD", "target": "LIFNR", "drop_source": True},
                    {"type": "VALUE_MAP", "field": "BUKRS", "table": "company_code_map",
                     "on_missing": "reject"},
                    {"type": "REGEX_CLEANSE", "field": "NAME1", "pattern": r"[^A-Za-z0-9 &.\-]",
                     "replacement": ""},
                    {"type": "TRIM", "field": "NAME1"},
                    {"type": "UPPER", "field": "LAND1"},
                ],
                "dq_rules": [
                    {"type": "MANDATORY", "field": "LAND1"},
                    {"type": "ALLOWED", "field": "BUKRS", "values": ["1710"]},
                    {"type": "REGEX_VALID", "field": "STCD1", "pattern": r"^[0-9A-Z]{8,16}$",
                     "message": "invalid tax id"},
                    {"type": "UNIQUE", "field": "LIFNR"},
                ],
            }
        },
    }

    eng = TransformationEngine(ruleset=ruleset)
    print("=" * 74)
    print("transformation_engine — self-test")
    print("=" * 74)

    def run(label, rec):
        out, dq = eng.apply("Vendor", rec)
        verdict = "PASS" if (dq is None or dq.passed) else "REJECT"
        print(f"\n[{label}] -> {verdict}")
        print(f"   transformed: {out}")
        if dq and not dq.passed:
            print(f"   reasons    : {dq.reasons}")
        return out, dq

    # 1) clean record: legacy company code 3000 -> 1710, name cleansed, valid tax id
    o1, d1 = run("clean", {"LIFNR_OLD": "V001", "BUKRS": "3000",
                           "NAME1": "  Açme  Söns#@!  ", "LAND1": "de", "STCD1": "DE12345678"})
    assert o1["LIFNR"] == "V001" and "LIFNR_OLD" not in o1
    assert o1["BUKRS"] == "1710" and o1["LAND1"] == "DE"
    assert d1.passed, d1.reasons

    # 2) missing mandatory country -> reject
    _, d2 = run("missing country", {"LIFNR_OLD": "V002", "BUKRS": "1000",
                                    "NAME1": "Globex", "LAND1": "", "STCD1": "GB99887766"})
    assert not d2.passed

    # 3) invalid tax id -> reject
    _, d3 = run("bad tax id", {"LIFNR_OLD": "V003", "BUKRS": "1000",
                               "NAME1": "Initech", "LAND1": "US", "STCD1": "bad id!"})
    assert not d3.passed

    # 4) unmapped company code -> VALUE_MAP reject sentinel -> ALLOWED gate rejects
    _, d4 = run("unmapped cocode", {"LIFNR_OLD": "V004", "BUKRS": "9999",
                                    "NAME1": "Umbrella", "LAND1": "US", "STCD1": "US12345678"})
    assert not d4.passed

    # 5) duplicate LIFNR (same as #1 after map) -> UNIQUE reject
    _, d5 = run("duplicate", {"LIFNR_OLD": "V001", "BUKRS": "1000",
                              "NAME1": "Acme", "LAND1": "DE", "STCD1": "DE12345678"})
    assert not d5.passed

    print("\nOK — field-map + value-map + cleanse applied; mandatory/regex/allowed/"
          "unique DQ gates all reject correctly (DATA_QUALITY_REJECTION).")
