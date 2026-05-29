"""
genai_router.py — GenAI Dispatch Router for Migrate4HANA
=========================================================
**Bedrock-only mode (2026-05-30).** For the end-to-end pipeline certification we
intentionally route the AI escalation through **AWS Bedrock only** — the local
Ollama path is dormant and will be re-enabled once the cloud loop is signed off.

Pipeline:
  1. AST Engine (local, deterministic) — always runs first.
  2. If AST produces fewer changes than ``AST_CHANGE_THRESHOLD``, escalate to
     **Bedrock** (Claude via PrivateLink) for semantic analysis.
  3. ``LLM_MODE`` / ``sensitivity`` are accepted for forward compatibility but
     currently ignored — selection is hard-pinned to Bedrock.
  4. All payloads are PII-scrubbed via ``data_scrubber`` before dispatch.

When the local-LLM path is re-introduced, restore the original ``_select_backends``
logic + the ``invoke_ollama`` import + the ``ollama`` branch in ``_dispatch``.
"""

import json
import os
import logging
import boto3
from typing import Dict, Any, Optional

logger = logging.getLogger("genai_router")
logger.setLevel(logging.INFO)

# Lazy imports — these modules live in the same Lambda package
from data_scrubber import mask_payload_for_infosec
from abap_ast_engine import process_abap_file
# from ollama_genai_engine import invoke_ollama  # disabled — Bedrock-only mode

# ── Configuration ─────────────────────────────────────────────────────────────
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0"
)
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
    """Bedrock-only mode: ignore LLM_MODE/sensitivity and route to Bedrock.

    The Ollama/local-LLM branch will be restored after the end-to-end pipeline
    test signs off the cloud loop. See module docstring for re-enablement notes.
    """
    return "bedrock", None


def _dispatch(backend: str, prompt: str) -> Optional[Dict[str, Any]]:
    """Dispatch to the named backend, catching all exceptions. Bedrock-only mode
    refuses any non-Bedrock backend rather than silently falling through."""
    try:
        if backend == "bedrock":
            return _invoke_bedrock(prompt)
        logger.warning(f"Backend '{backend}' disabled in Bedrock-only mode")
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
    """Invoke AWS Bedrock via PrivateLink (zero internet egress)."""
    try:
        client = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        })
        response = client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        response_body = json.loads(response["body"].read())
        content = response_body.get("content", [{}])[0].get("text", "")

        return _parse_genai_response(content, BEDROCK_MODEL_ID)
    except Exception as e:
        logger.warning(f"Bedrock invocation failed: {e}")
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
