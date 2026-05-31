"""
genai_router.py - GenAI Dispatch Router for Migrate4HANA
=========================================================
Cloud LLM path: direct Anthropic API (api.anthropic.com over NAT egress, key
in Secrets Manager). Bedrock is NOT used on this account - this account does
not have Bedrock model access. The Ollama local-LLM branch is dormant.

Pipeline:
  1. AST Engine (local, deterministic) - always runs first.
  2. If AST produces fewer changes than ``AST_CHANGE_THRESHOLD``, escalate to
     Claude via ``anthropic_client.invoke_claude``.
  3. ``LLM_MODE`` / ``sensitivity`` are accepted for forward compatibility but
     currently ignored - selection is hard-pinned to the Anthropic API.
  4. All payloads are PII-scrubbed via ``data_scrubber`` before dispatch.

The internal ``_invoke_bedrock`` function name is preserved purely for
callsite compatibility; the actual transport is the Anthropic API.

When the local-LLM path is re-introduced, restore the original ``_select_backends``
logic + the ``invoke_ollama`` import + the ``ollama`` branch in ``_dispatch``.
"""

import json
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("genai_router")
logger.setLevel(logging.INFO)

# Lazy imports — these modules live in the same Lambda package
from data_scrubber import mask_payload_for_infosec
from abap_ast_engine import process_abap_file
# from ollama_genai_engine import invoke_ollama  # disabled — Bedrock-only mode

# ── Configuration ─────────────────────────────────────────────────────────────
ANTHROPIC_MODEL_ID = os.environ.get("ANTHROPIC_MODEL_ID", "claude-sonnet-4-6")
AST_CHANGE_THRESHOLD = int(os.environ.get("AST_CHANGE_THRESHOLD", "3"))

# Backend selection. Supported values: "cloud" (default), "local", "dual".
LLM_MODE = os.environ.get("LLM_MODE", "cloud").lower()


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def route_analysis(
    abap_source: str, context: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Main routing entry point.

    Steps:
      1. Run the deterministic AST engine on the raw source.
      2. If the AST engine finds fewer than AST_CHANGE_THRESHOLD changes,
         escalate to a GenAI backend chosen by LLM_MODE and context.sensitivity.
      3. Return a unified result containing AST and (optional) GenAI output.

    context keys honoured:
      - custom_rules  : list of AST rule overrides
      - country_code  : localisation hint passed to the GenAI prompt
      - sensitivity   : "high" routes to local Ollama when LLM_MODE in
                        {"local", "dual"}
    """
    context = context or {}
    result: Dict[str, Any] = {
        "backend_used": "ast_engine",
        "ast_result": None,
        "genai_result": None,
        "scrubbed": False,
    }

    # ── Step 1: Deterministic AST analysis ────────────────────────────────────
    ast_result = process_abap_file(abap_source, rules=context.get("custom_rules"))
    result["ast_result"] = ast_result

    change_count = ast_result["stats"]["total_changes"]
    logger.info(f"AST engine found {change_count} changes")

    if change_count >= AST_CHANGE_THRESHOLD:
        logger.info("AST results sufficient — skipping GenAI escalation")
        return result

    # ── Step 2: PII scrub before sending to GenAI ─────────────────────────────
    logger.info("AST changes below threshold — escalating to GenAI")
    scrubbed_code = mask_payload_for_infosec(abap_source)
    result["scrubbed"] = True

    prompt = _build_analysis_prompt(scrubbed_code, ast_result, context)

    # ── Step 3: Pick backend per LLM_MODE × sensitivity ──────────────────────
    sensitivity = str(context.get("sensitivity", "")).lower()
    primary, fallback = _select_backends(sensitivity)
    logger.info(f"LLM routing: mode={LLM_MODE} sensitivity={sensitivity or 'none'} "
                f"primary={primary} fallback={fallback}")

    genai_result = _dispatch(primary, prompt)
    backend_used = primary if genai_result is not None else None

    if genai_result is None and fallback:
        logger.info(f"Primary backend '{primary}' failed — trying fallback '{fallback}'")
        genai_result = _dispatch(fallback, prompt)
        if genai_result is not None:
            backend_used = fallback

    if genai_result is not None:
        result["backend_used"] = backend_used
        result["genai_result"] = genai_result
    else:
        logger.warning("All GenAI backends unavailable — returning AST-only results")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _select_backends(sensitivity: str) -> (str, Optional[str]):
    """Anthropic-API-only mode: ignore LLM_MODE/sensitivity and route to Claude.

    The Ollama/local-LLM branch will be restored when the on-prem GPU path is
    productionised. See module docstring for re-enablement notes.
    """
    return "anthropic", None


def _dispatch(backend: str, prompt: str) -> Optional[Dict[str, Any]]:
    """Dispatch to the named backend, catching all exceptions. The "bedrock"
    alias is accepted for backwards compatibility but routes to the Anthropic
    API just like the canonical "anthropic" name."""
    try:
        if backend in ("anthropic", "bedrock"):
            return _invoke_bedrock(prompt)
        logger.warning(f"Backend '{backend}' disabled (Anthropic-API-only mode)")
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Backend '{backend}' raised unexpectedly: {e}")
        return None


def _build_analysis_prompt(
    scrubbed_code: str, ast_result: Dict, context: Dict
) -> str:
    """Construct the analysis prompt for the GenAI backend."""
    existing_changes = json.dumps(ast_result.get("changes", []), indent=2)
    country = context.get("country_code", "")
    country_hint = f"\nTarget country/localisation: {country}" if country else ""

    return (
        "You are an SAP ABAP migration expert. Analyse the following ABAP code "
        "for S/4HANA compatibility issues.\n\n"
        f"The AST engine already identified these changes:\n{existing_changes}\n"
        f"{country_hint}\n"
        "Identify ADDITIONAL migration issues requiring human review or semantic "
        "understanding, such as:\n"
        "- Custom logic patterns that may break with new data models\n"
        "- Performance implications of S/4HANA universal journal (ACDOCA)\n"
        "- Business process changes for Fiori/S4 workflows\n"
        "- Authorisation concept changes\n"
        "- Custom table dependencies needing migration\n\n"
        f"ABAP Code (PII-scrubbed):\n```abap\n{scrubbed_code}\n```\n\n"
        "Return ONLY a JSON array of objects with keys: "
        "rule_id, line, category, description, severity, recommendation"
    )


def _invoke_bedrock(prompt: str) -> Optional[Dict]:
    """Invoke Claude via the direct Anthropic API (Bedrock-equivalent path).
    Name kept for backwards compatibility with the bedrock-only routing layer.
    Egress is via NAT, not Bedrock PrivateLink."""
    try:
        from anthropic_client import invoke_claude
        text = invoke_claude(prompt, model=ANTHROPIC_MODEL_ID, max_tokens=4096)
        if not text:
            return None
        return _parse_genai_response(text, ANTHROPIC_MODEL_ID)
    except Exception as e:
        logger.warning(f"Anthropic invocation failed: {e}")
        return None


def _parse_genai_response(content: str, model: str) -> Dict:
    """Attempt to parse GenAI response as JSON findings list."""
    try:
        findings = json.loads(content)
        if not isinstance(findings, list):
            findings = [findings]
        return {"findings": findings, "model": model}
    except json.JSONDecodeError:
        return {"findings": [], "raw_response": content, "model": model}
