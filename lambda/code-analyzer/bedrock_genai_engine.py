"""
bedrock_genai_engine.py - Claude GenAI Engine for Migrate4HANA
===============================================================
Invokes Claude (Sonnet 4.6 by default, Opus 4.7 on escalation) via the direct
Anthropic API to remediate ABAP code issues the deterministic AST engine
cannot handle (Dynpro calls, native SQL, SAPGui FMs, complex semantic patterns).

Module name retained for callsite compatibility - the actual transport is
api.anthropic.com over the Lambda's NAT egress (Bedrock access not required).

Used as Phase 3 of Stage 5 in the local pipeline (run_local_pipeline.py).

Requirements:
    - ANTHROPIC_API_KEY env var OR M4H_ANTHROPIC_SECRET_ARN pointing to a
      Secrets Manager secret containing the key
"""

import json
import os
import logging
from typing import Dict, List, Optional

from anthropic_client import invoke_claude

logger = logging.getLogger("bedrock_genai_engine")
logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
# Default model. Sonnet 4.6 is the production default for code remediation:
# strong instruction-following on narrow tasks at ~5x lower cost than Opus.
ANTHROPIC_MODEL_ID = os.environ.get("ANTHROPIC_MODEL_ID", "claude-sonnet-4-6")
MAX_TOKENS = 8192
MAX_SOURCE_CHARS = 60_000  # Truncate very large programs to stay within token limits


def _build_remediation_prompt(
    program_name: str,
    abap_source: str,
    unfixed_issues: List[Dict],
    ast_changes_summary: str,
) -> str:
    """Build a focused remediation prompt for Claude Opus 4.6."""
    truncated = abap_source[:MAX_SOURCE_CHARS]
    trunc_note = ""
    if len(abap_source) > MAX_SOURCE_CHARS:
        trunc_note = f"\n[NOTE: Source truncated from {len(abap_source)} to {MAX_SOURCE_CHARS} chars]\n"

    issues_text = "\n".join(
        f"  - Line {i.get('line', '?')}: [{i.get('rule_id', '?')}] {i.get('description', '')} "
        f"(severity: {i.get('severity', '?')})"
        for i in unfixed_issues
    )

    return f"""You are an expert SAP ABAP developer specializing in S/4HANA migration.

PROGRAM: {program_name}

The deterministic AST engine has already applied these structural fixes:
{ast_changes_summary}

However, the following issues COULD NOT be auto-fixed by the AST engine and require
semantic understanding to remediate:

{issues_text}

Your task:
1. Analyze each unfixed issue in the context of the full program.
2. Provide the CORRECTED ABAP code that resolves each issue.
3. For Dynpro/CALL SCREEN issues: suggest the Fiori/Web Dynpro replacement pattern.
4. For Native SQL (EXEC SQL): rewrite using Open SQL / ABAP SQL.
5. For deprecated FM calls: provide the modern replacement code.

STRICT OUTPUT RULES — FOLLOW EXACTLY:
- Your response MUST contain ONLY a valid JSON object. No conversational text before or after.
- Do NOT include any preamble, explanation, greeting, or commentary outside the JSON.
- All code values in "fixed_code", "original_code", and "full_remediated_source" MUST contain
  ONLY raw ABAP code wrapped in ```abap ... ``` blocks. No natural language inside code fields.
- Return ONLY valid ABAP code in your fixes — no pseudocode, no placeholders.
- Preserve the original program structure and variable names.
- Do NOT remove business logic — only modernize the syntax/API calls.
- If a fix requires architectural changes beyond code (e.g., new Fiori app), note it
  as a recommendation but still provide the best possible code-level fix.
- If you cannot fix an issue, still include it with confidence "low" and explain in the
  explanation field — do NOT skip it or return empty.
{trunc_note}
ABAP Source Code:
```abap
{truncated}
```

Respond with ONLY this JSON (no other text):
{{
  "program": "{program_name}",
  "fixes": [
    {{
      "rule_id": "MANUAL-001",
      "line": 42,
      "original_code": "```abap\\nCALL SCREEN 100.\\n```",
      "fixed_code": "```abap\\n* TODO: Replace with Fiori LaunchPad call\\n* cl_gui_frontend_services=>execute(...).\\n```",
      "explanation": "Dynpro 100 must be replaced with a Fiori application.",
      "confidence": "high|medium|low"
    }}
  ],
  "recommendations": [
    "Free-text architectural recommendations that go beyond line-level fixes"
  ],
  "full_remediated_source": "```abap\\n<the complete program with all fixes applied>\\n```"
}}"""


def _invoke_bedrock(prompt: str) -> Optional[Dict]:
    """Invoke Claude via the direct Anthropic API (function name preserved for
    callsite compatibility - the transport is api.anthropic.com, not Bedrock).
    Returns parsed response dict, or an error dict with _error/_error_reason."""
    system_msg = (
        "You are an ABAP code remediation engine. You output ONLY valid JSON. "
        "Never include conversational text, greetings, or explanations outside "
        "the JSON structure. All ABAP code must be wrapped in ```abap``` blocks. "
        "If you cannot produce a fix, return the JSON with an empty fixes array."
    )

    logger.info(f"Anthropic invoke (model={ANTHROPIC_MODEL_ID}, prompt_len={len(prompt)})")
    text = invoke_claude(prompt, model=ANTHROPIC_MODEL_ID, system=system_msg,
                         max_tokens=MAX_TOKENS, temperature=0.1)

    if not text:
        return {"_error": True,
                "_error_reason": "Anthropic API unavailable or returned empty",
                "fixes": [], "recommendations": []}
    return _parse_response(text)


def _parse_response(content: str) -> Dict:
    """Parse the Claude response, extracting JSON from markdown fences if needed."""
    text = content.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        parsed = json.loads(text)
        return parsed
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                parsed = json.loads(text[start:end])
                return parsed
            except json.JSONDecodeError:
                pass

        logger.warning("Could not parse Bedrock response as JSON — returning raw text")
        return {
            "fixes": [],
            "recommendations": [],
            "raw_response": content,
            "full_remediated_source": None,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API — called from run_local_pipeline.py Stage 5
# ═══════════════════════════════════════════════════════════════════════════════

def check_bedrock_connectivity() -> bool:
    """Quick check that the Anthropic API key is loadable. Name preserved for
    callsite compatibility."""
    try:
        from anthropic_client import _load_api_key
        ok = bool(_load_api_key())
        if ok:
            logger.info(f"Anthropic API key loaded (model={ANTHROPIC_MODEL_ID})")
        else:
            logger.warning("Anthropic API key unavailable")
        return ok
    except Exception as e:
        logger.warning(f"Anthropic connectivity check failed: {e}")
        return False


def remediate_with_genai(
    program_name: str,
    abap_source: str,
    unfixed_issues: List[Dict],
    ast_changes_summary: str = "No AST changes were applied.",
) -> Optional[Dict]:
    """
    Send a program + its unfixed issues to Claude Opus 4.6 on Bedrock
    for semantic remediation.

    Returns a dict with keys: fixes, recommendations, full_remediated_source
    or None if Bedrock is unavailable.
    """
    if not unfixed_issues:
        return None

    prompt = _build_remediation_prompt(
        program_name, abap_source, unfixed_issues, ast_changes_summary
    )

    logger.info(f"Sending {program_name} to Bedrock ({len(unfixed_issues)} unfixed issues, "
                f"{len(abap_source)} chars source)")

    result = _invoke_bedrock(prompt)
    return result
