"""
claude_engine.py — Claude Opus 4.6 Engine for Migrate4HANA
===========================================================
Invokes Claude Opus 4.6 via the Anthropic Python SDK to remediate ABAP
code issues that the deterministic AST engine cannot handle (Dynpro calls,
native SQL, SAPGui FMs, complex semantic patterns).

Used as Phase 3 of Stage 5 in the local pipeline (run_local_pipeline.py).

Authentication:
    ANTHROPIC_API_KEY env var (loaded from Azure Key Vault at runtime).

Environment:
    ANTHROPIC_API_KEY   — API key for the Anthropic API
    ANTHROPIC_MODEL     — model name (default "claude-opus-4-6-20250219")
"""

import json
import os
import logging
import time
from typing import Any, Dict, List, Optional

import anthropic

logger = logging.getLogger("claude_engine")
logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6-20250219")

MAX_TOKENS = 8192
MAX_SOURCE_CHARS = 60_000
TEMPERATURE = 0.1
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1  # seconds — exponential: 1s, 2s, 4s

# Cached client
_anthropic_client: Optional[anthropic.Anthropic] = None


def _create_client() -> anthropic.Anthropic:
    """
    Create and cache an Anthropic client instance.

    Uses the ANTHROPIC_API_KEY environment variable for authentication.
    The key is typically loaded from Azure Key Vault at application startup.

    Returns:
        Cached ``anthropic.Anthropic`` client.

    Raises:
        EnvironmentError: If ANTHROPIC_API_KEY is not set.
    """
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY is not set. "
            "Load it from Azure Key Vault or set it as an environment variable."
        )

    _anthropic_client = anthropic.Anthropic(api_key=api_key)
    logger.info(
        "Anthropic client initialised (model=%s)",
        ANTHROPIC_MODEL,
    )
    return _anthropic_client


# ═══════════════════════════════════════════════════════════════════════════════
# RETRY LOGIC
# ═══════════════════════════════════════════════════════════════════════════════


def _call_with_retry(
    system_prompt: str, user_prompt: str, max_retries: int = MAX_RETRIES
) -> Optional[str]:
    """
    Call Claude via the Anthropic Messages API with exponential backoff.

    Args:
        system_prompt: System-level instruction for the model.
        user_prompt:   User message containing the analysis request.
        max_retries:   Maximum number of retry attempts.

    Returns:
        Response content string, or None on unrecoverable failure.
    """
    client = _create_client()
    last_error = "Unknown error"

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Claude invoke attempt %d/%d (model=%s)",
                attempt, max_retries, ANTHROPIC_MODEL,
            )

            response = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Extract text from content blocks
            content = ""
            for block in response.content:
                if block.type == "text":
                    content += block.text

            usage = response.usage
            logger.info(
                "Claude response: %d chars, "
                "input_tokens=%s, output_tokens=%s",
                len(content),
                getattr(usage, "input_tokens", "?"),
                getattr(usage, "output_tokens", "?"),
            )
            return content

        except anthropic.RateLimitError as exc:
            wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            logger.warning(
                "Claude rate limited (429), retrying in %ds… (%s)",
                wait, exc,
            )
            if attempt < max_retries:
                time.sleep(wait)
                last_error = f"Rate limited after {max_retries} attempts"
                continue
            logger.error("Claude rate limit exhausted after %d attempts", max_retries)
            return None

        except anthropic.AuthenticationError as exc:
            logger.error("Claude authentication failed: %s", exc)
            return None

        except anthropic.APIConnectionError as exc:
            logger.error("Cannot connect to Anthropic API: %s", exc)
            if attempt < max_retries:
                time.sleep(RETRY_BACKOFF_BASE * attempt)
                continue
            return None

        except anthropic.APIError as exc:
            logger.error("Anthropic API error: %s", exc)
            last_error = str(exc)
            if attempt < max_retries:
                time.sleep(RETRY_BACKOFF_BASE * attempt)
                continue
            return None

    logger.error("Claude invocation failed: %s", last_error)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSE PARSING
# ═══════════════════════════════════════════════════════════════════════════════


def _parse_response(content: str) -> Dict[str, Any]:
    """Parse the LLM response, extracting JSON from markdown fences if needed."""
    text = content.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass

        logger.warning("Could not parse Claude response as JSON — returning raw text")
        return {
            "remediated_code": None,
            "explanation": None,
            "confidence": None,
            "changes": [],
            "raw_response": content,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


def analyze_abap_code(
    source_code: str, issue_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Analyse ABAP source code for S/4HANA migration issues using Claude Opus 4.6.

    Args:
        source_code:   Raw ABAP source code.
        issue_context: Optional dict with keys like ``program_name``,
                       ``unfixed_issues``, ``ast_changes_summary``.

    Returns:
        Dict with keys: remediated_code, explanation, confidence, model, changes.
        On failure, includes ``_error`` and ``_error_reason``.
    """
    context = issue_context or {}
    program_name = context.get("program_name", "UNKNOWN")
    unfixed_issues = context.get("unfixed_issues", [])
    ast_changes_summary = context.get("ast_changes_summary", "No AST changes were applied.")

    # Truncate source to fit within token budget
    truncated = source_code[:MAX_SOURCE_CHARS]
    trunc_note = ""
    if len(source_code) > MAX_SOURCE_CHARS:
        trunc_note = (
            f"\n[NOTE: Source truncated from {len(source_code)} "
            f"to {MAX_SOURCE_CHARS} chars]\n"
        )

    issues_text = "\n".join(
        f"  - Line {i.get('line', '?')}: [{i.get('rule_id', '?')}] "
        f"{i.get('description', '')} (severity: {i.get('severity', '?')})"
        for i in unfixed_issues
    )

    system_prompt = (
        "You are an expert ABAP developer performing ECC to S/4HANA migration "
        "analysis. Identify deprecated APIs, data model changes "
        "(BSEG→ACDOCA, KNA1→BUT000), obsolete transactions, and provide "
        "remediated code. You output ONLY valid JSON. Never include "
        "conversational text, greetings, or explanations outside the JSON "
        "structure."
    )

    user_prompt = f"""You are an expert SAP ABAP developer specializing in S/4HANA migration.

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
6. Identify deprecated data models (BSEG→ACDOCA, KNA1→BUT000) and migrate them.

STRICT OUTPUT RULES — FOLLOW EXACTLY:
- Return ONLY a valid JSON object. No conversational text before or after.
- Return ONLY valid ABAP code — no pseudocode, no placeholders.
- Preserve the original program structure and variable names.
- Do NOT remove business logic — only modernize the syntax/API calls.
{trunc_note}
ABAP Source Code:
```abap
{truncated}
```

Respond with ONLY this JSON:
{{
  "remediated_code": "<complete remediated ABAP source>",
  "explanation": "Summary of all changes made",
  "confidence": 0.85,
  "model": "{ANTHROPIC_MODEL}",
  "changes": [
    {{
      "rule_id": "MANUAL-001",
      "line": 42,
      "original_code": "CALL SCREEN 100.",
      "fixed_code": "* Fiori replacement pattern",
      "description": "Why this fix is needed."
    }}
  ]
}}"""

    logger.info(
        "Sending %s to Claude (%d unfixed issues, %d chars source)",
        program_name, len(unfixed_issues), len(source_code),
    )

    content = _call_with_retry(system_prompt, user_prompt)

    if content is None:
        return {
            "_error": True,
            "_error_reason": "Claude invocation failed",
            "remediated_code": None,
            "explanation": None,
            "confidence": None,
            "model": ANTHROPIC_MODEL,
            "changes": [],
        }

    result = _parse_response(content)

    # Normalise output fields
    if "full_remediated_source" in result and "remediated_code" not in result:
        result["remediated_code"] = result.pop("full_remediated_source")
    result.setdefault("remediated_code", None)
    result.setdefault("explanation", "Claude analysis complete")
    result.setdefault("confidence", 0.5)
    result.setdefault("model", ANTHROPIC_MODEL)
    result.setdefault("changes", [])

    # Normalise confidence to float
    conf = result["confidence"]
    if isinstance(conf, str):
        confidence_map = {"high": 0.9, "medium": 0.7, "low": 0.4}
        result["confidence"] = confidence_map.get(conf.lower(), 0.5)

    return result
