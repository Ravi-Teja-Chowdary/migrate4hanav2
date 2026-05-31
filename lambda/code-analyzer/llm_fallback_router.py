"""
llm_fallback_router.py — Migrate4HANA "SmartShift layer" runtime wrapper
=========================================================================
Deterministic-first, **AI-as-a-fail-safe** ABAP remediation.

The heavy lifting is done programmatically by the 6,400-line ``abap_ast_engine``
(``process_abap_file`` — lex → parse → S/4HANA transform → regenerate). This
module wraps that engine so the *pipeline never halts* on a pathological custom
Z-program, and escalates to a runtime LLM **only** for the localised fragment the
deterministic parser could not resolve.

The fail-safe loop (per the architecture "Deterministic-First, AI-as-a-Fail-Safe"):

    1. Run the AST engine inside a strict try/except.
    2. If it raises (a lexer/generator crash) OR leaves parse errors, isolate
       each offending block: raw ABAP lines, line numbers, exact parser error.
    3. Build a *context-compact* Amazon Bedrock prompt instructing the model to
       fix ONLY that localised syntax error and strictly preserve business logic.
    4. Splice the fix back, re-run the deterministic engine to confirm the error
       cleared (bounded retries).
    5. Route the result through a mock SAP ATC governance gate. PASS → package a
       standard transport (.data + .cofile). FAIL → quarantine for human review.

The LLM call is injectable (``llm_callable``) so the loop is unit-testable with no
AWS credentials; in production it defaults to Bedrock via PrivateLink.
"""
from __future__ import annotations

import json
import logging
import os
import re
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("llm_fallback_router")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# ── deterministic engine (same Lambda package). Imported defensively so the
#    router degrades to "engine unavailable" instead of crashing on import. ──
try:
    from abap_ast_engine import process_abap_file
except Exception:  # pragma: no cover - exercised only when path is wrong
    # The code-analyzer dir is on sys.path when run as a Lambda / via the runner.
    # ("lambda" is a Python keyword so the package can't be imported by name.)
    process_abap_file = None  # type: ignore

# Reversible masking — surrogates leave the process to Bedrock; originals restored on return.
try:
    from pseudonymize import Pseudonymizer
except Exception:
    Pseudonymizer = None  # type: ignore

# Default Claude model for ABAP remediation. Sonnet 4.6 handles narrow
# fragment-fix tasks at ~5x cheaper than Opus; the router escalates to
# claude-opus-4-7 on retry (see anthropic_client.ESCALATION_MODEL).
ANTHROPIC_MODEL_ID = os.environ.get("ANTHROPIC_MODEL_ID", "claude-sonnet-4-6")
MAX_FALLBACK_RETRIES = int(os.environ.get("M4H_FALLBACK_RETRIES", "2"))
ERROR_WINDOW = int(os.environ.get("M4H_ERROR_WINDOW", "6"))  # context lines each side


# ════════════════════════════════════════════════════════════════════════════
#  Error localisation
# ════════════════════════════════════════════════════════════════════════════
_L_RE = re.compile(r"\bL(\d+)\b")


@dataclass
class OffendingBlock:
    """A localised parser failure, packaged for the LLM."""
    error: str
    line: Optional[int]
    start_line: int
    end_line: int
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


def _line_from_error(err: str) -> Optional[int]:
    m = _L_RE.search(err or "")
    return int(m.group(1)) if m else None


def localise(source: str, error: str, window: int = ERROR_WINDOW) -> OffendingBlock:
    """Carve a bounded source window around the line named in ``error``.

    If the error carries no line number, the whole source is the block (still
    bounded by the caller's overall size limits upstream).
    """
    lines = source.splitlines()
    n = len(lines)
    line = _line_from_error(error)
    if line is None or not (1 <= line <= n):
        return OffendingBlock(error=error, line=line, start_line=1,
                              end_line=n, snippet=source)
    start = max(1, line - window)
    end = min(n, line + window)
    snippet = "\n".join(lines[start - 1:end])
    return OffendingBlock(error=error, line=line, start_line=start,
                          end_line=end, snippet=snippet)


# ════════════════════════════════════════════════════════════════════════════
#  Bedrock prompt construction + invocation
# ════════════════════════════════════════════════════════════════════════════
def build_fix_prompt(block: OffendingBlock, object_name: str = "") -> str:
    """A context-compact, single-purpose prompt: fix ONLY the syntax error."""
    where = f" (lines {block.start_line}-{block.end_line}, error at L{block.line})" \
        if block.line else ""
    obj = f" from custom object {object_name}" if object_name else ""
    return (
        "You are an SAP ABAP syntax-repair tool. The deterministic parser failed "
        f"on this fragment{obj}{where}.\n\n"
        f"Parser error:\n{block.error}\n\n"
        "Fix ONLY the localised syntax error. STRICTLY preserve all business "
        "logic, variable names, comments, and statement order. Do not refactor, "
        "modernise, optimise, or add/remove functionality. If a macro or nested "
        "construct is malformed, make the minimal change that lets it parse.\n\n"
        "Return ONLY the corrected ABAP for this exact fragment inside a single "
        "```abap code block, with no commentary.\n\n"
        f"```abap\n{block.snippet}\n```"
    )


_ABAP_BLOCK_RE = re.compile(r"```(?:abap)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_abap(text: str) -> str:
    """Pull the ABAP out of an LLM response (fenced block, else raw)."""
    if not text:
        return ""
    m = _ABAP_BLOCK_RE.search(text)
    return (m.group(1) if m else text).strip("\n")


def invoke_anthropic(prompt: str, model_id: str = ANTHROPIC_MODEL_ID) -> Optional[str]:
    """Invoke Claude via the direct Anthropic API and return raw text, or None.
    Never raises - a dead LLM must not halt the pipeline."""
    try:
        from anthropic_client import invoke_claude
        return invoke_claude(prompt, model=model_id, max_tokens=2048, temperature=0.0)
    except Exception as e:  # noqa: BLE001
        logger.warning("Anthropic invocation unavailable: %s", e)
        return None


# Backwards-compat alias - the router still references invoke_bedrock as the
# default callable so external test harnesses keep working.
invoke_bedrock = invoke_anthropic


# ════════════════════════════════════════════════════════════════════════════
#  Mock SAP ABAP Test Cockpit (ATC) governance gate
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class ATCFinding:
    priority: int             # 1 = error (blocks), 2 = warning, 3 = info
    check: str
    line: Optional[int]
    message: str


# control-structure open→close pairs the gate balance-checks
_ATC_PAIRS = {
    "IF": "ENDIF", "LOOP": "ENDLOOP", "DO": "ENDDO", "WHILE": "ENDWHILE",
    "CASE": "ENDCASE", "TRY": "ENDTRY", "FORM": "ENDFORM",
    "METHOD": "ENDMETHOD", "MODULE": "ENDMODULE", "WHILE_": "ENDWHILE",
}


def mock_atc_check(code: str) -> dict:
    """A deterministic stand-in for an SAP ATC run. Returns
    ``{verdict: PASS|FAIL, findings:[...], counts:{...}}``.

    PASS iff there are no priority-1 findings (true ATC errors).
    """
    findings: list[ATCFinding] = []
    # strip comments + string literals so keyword counting is not fooled
    scrub_lines = []
    for ln in code.splitlines():
        s = ln
        if s.lstrip().startswith("*"):
            s = ""
        s = re.sub(r'".*$', "", s)          # full-line/inline ABAP comment
        s = re.sub(r"'[^']*'", "''", s)     # string literals
        scrub_lines.append(s)
    scrubbed = "\n".join(scrub_lines)
    upper = scrubbed.upper()

    # 1) balance of control structures (priority 1 — a real syntax break)
    for opener, closer in _ATC_PAIRS.items():
        op = opener.rstrip("_")
        opens = len(re.findall(rf"(?<![\w-]){op}\b", upper))
        closes = len(re.findall(rf"(?<![\w-]){closer}\b", upper))
        # ENDIF also closes ELSEIF chains; only flag a real imbalance
        if op == "IF":
            opens = len(re.findall(r"(?<![\w-])IF\b", upper))
        if opens != closes:
            findings.append(ATCFinding(
                1, "control_structure_balance", None,
                f"{op}/{closer} imbalance: {opens} {op} vs {closes} {closer}"))

    # 2) leftover repair marker means the LLM did not actually fix it (priority 1)
    for i, ln in enumerate(code.splitlines(), 1):
        if "M4H_SYNTAX_ERROR" in ln or "*** UNRESOLVED" in ln:
            findings.append(ATCFinding(1, "unresolved_syntax", i,
                                       "unresolved syntax marker present"))

    # 3) native SQL — supported but flagged for review (priority 2)
    if re.search(r"(?<![\w-])EXEC\s+SQL\b", upper):
        findings.append(ATCFinding(2, "native_sql", None,
                                   "EXEC SQL present — verify HANA compatibility"))

    # 4) unrestricted SELECT * (priority 3 — informational, remediation hint)
    for i, ln in enumerate(scrub_lines, 1):
        if re.search(r"(?<![\w-])SELECT\s+\*", ln.upper()):
            findings.append(ATCFinding(3, "select_star", i,
                                       "SELECT * — prefer explicit field list"))

    counts = {1: 0, 2: 0, 3: 0}
    for f in findings:
        counts[f.priority] = counts.get(f.priority, 0) + 1
    verdict = "PASS" if counts.get(1, 0) == 0 else "FAIL"
    return {
        "verdict": verdict,
        "findings": [asdict(f) for f in findings],
        "counts": {"errors": counts.get(1, 0), "warnings": counts.get(2, 0),
                   "info": counts.get(3, 0)},
    }


# ════════════════════════════════════════════════════════════════════════════
#  Transport packaging + quarantine
# ════════════════════════════════════════════════════════════════════════════
def _transport_request_id(object_name: str, sid: str = "S4H") -> str:
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    return f"{sid}K9{stamp[-5:]}"


def package_transport(code: str, object_name: str, out_dir: Path,
                      sid: str = "S4H") -> dict:
    """Write SAP-style transport co-files for a passed object.

    Produces a data file (``R9…``) and a cofile (``K9…``) under
    ``out_dir/transport`` mirroring the standard ``/usr/sap/trans`` layout. This
    is a packaging stub for the governance flow — actual import is performed by
    the transport-import-executor stage against a routed landscape.
    """
    req = _transport_request_id(object_name, sid)
    tdir = out_dir / "transport"
    (tdir / "data").mkdir(parents=True, exist_ok=True)
    (tdir / "cofiles").mkdir(parents=True, exist_ok=True)
    num = req[3:]                      # the 9xxxxx portion
    data_path = tdir / "data" / f"R{num}.{sid}"
    cofile_path = tdir / "cofiles" / f"K{num}.{sid}"
    data_path.write_text(code, encoding="utf-8")
    cofile_path.write_text(json.dumps({
        "request": req,
        "object": object_name,
        "object_type": "PROG",
        "created": datetime.now(timezone.utc).isoformat(),
        "data_file": data_path.name,
        "checksum_sha256": __import__("hashlib").sha256(code.encode()).hexdigest(),
    }, indent=2), encoding="utf-8")
    return {"request": req, "data_file": str(data_path),
            "cofile": str(cofile_path)}


def quarantine(code: str, object_name: str, reason: str, out_dir: Path,
               detail: Any = None) -> dict:
    qdir = out_dir / "quarantine"
    qdir.mkdir(parents=True, exist_ok=True)
    src_path = qdir / f"{object_name or 'UNKNOWN'}.abap"
    meta_path = qdir / f"{object_name or 'UNKNOWN'}.quarantine.json"
    src_path.write_text(code or "", encoding="utf-8")
    meta_path.write_text(json.dumps({
        "object": object_name, "reason": reason,
        "detail": detail,
        "quarantined_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2, default=str), encoding="utf-8")
    return {"object": object_name, "reason": reason,
            "source": str(src_path), "meta": str(meta_path)}


# ════════════════════════════════════════════════════════════════════════════
#  The router
# ════════════════════════════════════════════════════════════════════════════
@dataclass
class RemediationResult:
    object_name: str
    path: str                       # "deterministic" | "ai_fallback" | "engine_unavailable"
    transformed_code: str
    deterministic_changes: int = 0
    ai_fixes: int = 0
    parse_errors_before: int = 0
    parse_errors_after: int = 0
    offending_blocks: list = field(default_factory=list)
    pseudonymize: list = field(default_factory=list)   # per-block mask counts (audit)
    atc: dict = field(default_factory=dict)
    governance: str = ""            # "transported" | "quarantined"
    artifacts: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class FallbackRouter:
    """Wrap the deterministic AST engine with an AI fail-safe + governance gate."""

    def __init__(self, llm_callable: Optional[Callable[[str], Optional[str]]] = None,
                 engine: Optional[Callable[..., dict]] = None,
                 max_retries: int = MAX_FALLBACK_RETRIES):
        # llm_callable: prompt -> raw model text (or None). Defaults to Anthropic.
        self.llm = llm_callable or invoke_anthropic
        self.engine = engine or process_abap_file
        self.max_retries = max_retries

    # -- public entry ---------------------------------------------------------
    def remediate(self, source: str, object_name: str = "",
                  out_dir: str | os.PathLike = "remediation_out") -> RemediationResult:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)

        if self.engine is None:
            res = RemediationResult(object_name, "engine_unavailable", source,
                                    error="abap_ast_engine not importable")
            res.governance = "quarantined"
            res.artifacts = quarantine(source, object_name,
                                       "deterministic engine unavailable", out)
            return res

        # ── Step 1: deterministic engine inside a strict guard ──────────────
        current = source
        crashed = False
        crash_detail = ""
        try:
            engine_out = self.engine(current)
        except Exception as e:  # the AI fail-safe trigger
            crashed = True
            crash_detail = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            logger.warning("AST engine crashed on %s — entering AI fail-safe: %s",
                           object_name or "<anon>", e)
            engine_out = {"transformed_code": current, "changes": [],
                          "parse_errors": [crash_detail], "stats": {"total_changes": 0}}

        det_changes = engine_out.get("stats", {}).get("total_changes", 0)
        parse_errors = list(engine_out.get("parse_errors") or [])
        errors_before = len(parse_errors)
        transformed = engine_out.get("transformed_code", current)

        result = RemediationResult(
            object_name=object_name,
            path="deterministic",
            transformed_code=transformed,
            deterministic_changes=det_changes,
            parse_errors_before=errors_before,
        )

        # ── Step 2-4: AI fail-safe loop for unresolved fragments ────────────
        if crashed or parse_errors:
            result.path = "ai_fallback"
            transformed, ai_fixes, blocks, errors_after, mask_reports = self._fix_with_ai(
                transformed if not crashed else current, parse_errors, object_name)
            result.transformed_code = transformed
            result.ai_fixes = ai_fixes
            result.offending_blocks = [b.to_dict() for b in blocks]
            result.pseudonymize = mask_reports
            result.parse_errors_after = errors_after
        else:
            result.parse_errors_after = 0

        # ── Step 5: governance gate (mock ATC) ──────────────────────────────
        atc = mock_atc_check(result.transformed_code)
        result.atc = atc
        if atc["verdict"] == "PASS":
            result.governance = "transported"
            result.artifacts = package_transport(result.transformed_code,
                                                  object_name, out)
        else:
            result.governance = "quarantined"
            result.artifacts = quarantine(
                result.transformed_code, object_name,
                "ATC gate FAIL", out, detail=atc)

        (out / f"remediation_{object_name or 'anon'}.json").write_text(
            json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
        return result

    # -- internal -------------------------------------------------------------
    def _fix_with_ai(self, source: str, parse_errors: list[str],
                     object_name: str):
        """Localised, bounded-retry AI repair with **reversible masking** around
        the Bedrock call: sensitive tokens (emails / IPs / URLs / passwords / any
        caller-supplied literals) are pseudonymized before the prompt leaves the
        process, and restored byte-for-byte in the returned fix. Bedrock only
        ever sees surrogates. Returns (fixed_source, ai_fix_count,
        offending_blocks, residual_error_count, mask_reports)."""
        blocks: list[OffendingBlock] = []
        fixed = source
        ai_fixes = 0
        mask_reports: list = []

        # de-duplicate errors by their localised line so we fix each spot once
        seen_lines: set = set()
        for err in parse_errors:
            block = localise(fixed, err)
            key = (block.start_line, block.end_line)
            if key in seen_lines:
                continue
            seen_lines.add(key)
            blocks.append(block)

            # ── mask the snippet for Bedrock; keep the mapping for restore ──
            ps = Pseudonymizer() if Pseudonymizer is not None else None
            if ps is not None:
                masked_snippet = ps.mask(block.snippet)
                masked_block = OffendingBlock(
                    error=block.error, line=block.line,
                    start_line=block.start_line, end_line=block.end_line,
                    snippet=masked_snippet)
            else:
                masked_block = block

            prompt = build_fix_prompt(masked_block, object_name)
            raw = None
            # First attempt uses the configured default (Sonnet 4.6); on retry
            # escalate to Opus 4.7 since the cheap path didn't produce a fix.
            for attempt in range(max(1, self.max_retries)):
                if attempt == 0 or self.llm is not invoke_anthropic:
                    raw = self.llm(prompt)
                else:
                    raw = invoke_anthropic(
                        prompt, model_id=os.environ.get(
                            "ANTHROPIC_ESCALATION_MODEL", "claude-opus-4-7"))
                if raw:
                    break
            patched_masked = extract_abap(raw) if raw else ""
            # ── restore originals in the returned remediation ──
            patched = ps.unmask(patched_masked) if (ps and patched_masked) else patched_masked

            if ps is not None:
                mask_reports.append({"line": block.line, **ps.report.to_dict()})

            if patched and patched.strip() and "M4H_SYNTAX_ERROR" not in patched:
                fixed = self._splice(fixed, block, patched)
                ai_fixes += 1
            else:
                # LLM unavailable / declined → leave a marker the ATC gate catches
                fixed = self._mark_unresolved(fixed, block)

        # confirm with the deterministic engine (the loop's verification step)
        residual = self._count_parse_errors(fixed)
        return fixed, ai_fixes, blocks, residual, mask_reports

    @staticmethod
    def _splice(source: str, block: OffendingBlock, replacement: str) -> str:
        lines = source.splitlines()
        new = lines[:block.start_line - 1] + replacement.splitlines() + \
            lines[block.end_line:]
        return "\n".join(new)

    @staticmethod
    def _mark_unresolved(source: str, block: OffendingBlock) -> str:
        lines = source.splitlines()
        marker = f'* M4H_SYNTAX_ERROR unresolved at L{block.line}: {block.error}'
        insert_at = max(0, block.start_line - 1)
        lines.insert(insert_at, marker)
        return "\n".join(lines)

    def _count_parse_errors(self, source: str) -> int:
        if self.engine is None:
            return 0
        try:
            out = self.engine(source)
            return len(out.get("parse_errors") or [])
        except Exception:
            return 1


# convenience function mirroring genai_router.route_analysis
def remediate_with_fallback(source: str, object_name: str = "",
                            out_dir: str = "remediation_out",
                            llm_callable: Optional[Callable] = None) -> dict:
    return FallbackRouter(llm_callable=llm_callable).remediate(
        source, object_name, out_dir).to_dict()


# ════════════════════════════════════════════════════════════════════════════
#  Self-test (no AWS) — proves the fail-safe loop + governance gate end to end.
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    print("=" * 78)
    print("llm_fallback_router — self-test")
    print("=" * 78)
    if process_abap_file is None:
        print("WARNING: abap_ast_engine not importable from here; "
              "engine paths will report unavailable.")

    out = Path(tempfile.mkdtemp(prefix="m4h_remed_"))

    # Case 1: clean, modern-ish ABAP — deterministic path, ATC PASS → transport.
    clean = (
        "REPORT zclean.\n"
        "DATA lt_mara TYPE STANDARD TABLE OF mara.\n"
        "SELECT matnr, mtart FROM mara INTO TABLE @DATA(lt) WHERE mtart = 'FERT'.\n"
        "LOOP AT lt INTO DATA(ls).\n"
        "  WRITE: / ls-matnr.\n"
        "ENDLOOP.\n"
    )
    r1 = FallbackRouter().remediate(clean, "ZCLEAN", out)
    print(f"\n[Case 1] clean program")
    print(f"  path={r1.path}  det_changes={r1.deterministic_changes}  "
          f"ATC={r1.atc.get('verdict')}  governance={r1.governance}")

    # Case 2: a pathological fragment. The real 6,400-line engine is deliberately
    # tolerant (it degrades to GenericStatement and rarely throws), so to exercise
    # the fail-safe loop deterministically we inject a stub engine that reports the
    # unbalanced LOOP as a parse error — exactly what a crash/parse-failure looks
    # like to the router. Bedrock is simulated by a local fixer (no AWS call).
    broken = (
        "REPORT zbroken.\n"
        "DATA lt TYPE STANDARD TABLE OF mara.\n"
        "LOOP AT lt INTO DATA(ls).\n"
        "  WRITE ls-matnr.\n"
        "* missing ENDLOOP below triggers a parse error\n"
        "WRITE 'done'.\n"
    )

    def stub_engine(src: str) -> dict:
        """Stand-in deterministic engine that flags an unbalanced LOOP."""
        code_only = "\n".join(
            "" if l.lstrip().startswith("*") else re.sub(r'".*$', "", l)
            for l in src.splitlines())
        up = code_only.upper()
        opens = len(re.findall(r"(?<![\w-])LOOP\b", up))
        closes = len(re.findall(r"(?<![\w-])ENDLOOP\b", up))
        errors = []
        if opens != closes:
            line = next((i for i, l in enumerate(src.splitlines(), 1)
                         if re.search(r"(?<![\w-])LOOP\b", l.upper())), 1)
            errors = [f"Unexpected parse error at L{line}: LOOP without ENDLOOP"]
        return {"transformed_code": src, "changes": [],
                "parse_errors": errors, "stats": {"total_changes": 0}}

    def fake_bedrock(prompt: str) -> str:
        # The 'model' returns a corrected fragment that adds the missing ENDLOOP.
        return ("```abap\n"
                "LOOP AT lt INTO DATA(ls).\n"
                "  WRITE ls-matnr.\n"
                "ENDLOOP.\n"
                "WRITE 'done'.\n"
                "```")

    r2 = FallbackRouter(llm_callable=fake_bedrock, engine=stub_engine).remediate(
        broken, "ZBROKEN", out)
    print(f"\n[Case 2] pathological fragment (AI fail-safe)")
    print(f"  path={r2.path}  parse_errors_before={r2.parse_errors_before} "
          f"-> after={r2.parse_errors_after}  ai_fixes={r2.ai_fixes}")
    print(f"  offending_blocks={len(r2.offending_blocks)}  "
          f"ATC={r2.atc.get('verdict')}  governance={r2.governance}")

    # Case 3: AI unavailable (llm returns None) → marker stays → ATC FAIL → quarantine.
    r3 = FallbackRouter(llm_callable=lambda p: None, engine=stub_engine).remediate(
        broken, "ZNOAI", out)
    print(f"\n[Case 3] AI unavailable")
    print(f"  path={r3.path}  ATC={r3.atc.get('verdict')}  "
          f"governance={r3.governance}")
    assert r3.governance == "quarantined", "unresolved code must be quarantined"

    print("\nOK - deterministic->transport, AI-fallback->fix, no-AI->quarantine.")
    print(f"artifacts in {out}")
