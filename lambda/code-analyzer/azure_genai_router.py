"""
azure_genai_router.py — Dual-path GenAI Router for Migrate4HANA (Azure)
========================================================================
Replaces genai_router.py. Routes ABAP code analysis requests to the
optimal GenAI backend:

  1. AST Engine        (local, zero-latency, deterministic)
  2. Azure OpenAI      (cloud, GPT-4 via Azure Private Endpoint)
  3. Air-gapped LLM    (on-prem GPU, for classified workloads)

Routing Logic:
  - Always run the AST engine first (structural, deterministic transforms)
  - If AST produces fewer changes than the threshold, escalate to GenAI
    for deeper semantic analysis
  - LLM_MODE controls the backend: "auto" (default), "cloud", "airgapped"
  - All payloads are PII-scrubbed via data_scrubber before GenAI dispatch
  - Fallback chain: Azure OpenAI → Local LLM → AST-only

Environment:
    LOCAL_LLM_ENDPOINT      — URL for air-gapped local LLM (OpenAI-compatible)
    AST_CHANGE_THRESHOLD    — minimum AST changes to skip GenAI (default 3)
    LLM_MODE                — "auto" | "cloud" | "airgapped"
"""

import json
import os
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("azure_genai_router")
logger.setLevel(logging.INFO)

# Lazy imports — these modules live in the same Lambda package
from data_scrubber import mask_payload_for_infosec
from abap_ast_engine import process_abap_file

# ── Configuration ─────────────────────────────────────────────────────────────
LOCAL_LLM_ENDPOINT = os.environ.get("LOCAL_LLM_ENDPOINT", "")
AST_CHANGE_THRESHOLD = int(os.environ.get("AST_CHANGE_THRESHOLD", "3"))
LLM_MODE = os.environ.get("LLM_MODE", "auto").lower()  # auto | cloud | airgapped


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


def route_analysis(
    abap_source: str, context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Main routing entry point.

    1. Runs the deterministic AST engine on the raw source.
    2. If the AST engine finds fewer than AST_CHANGE_THRESHOLD changes,
       escalates to a GenAI backend for deeper semantic analysis.
    3. Returns a unified result containing both AST and (optional) GenAI output.

    Args:
        abap_source: Raw ABAP source code string.
        context:     Optional dict with custom_rules, country_code, etc.

    Returns:
        {
            "backend_used": "azure_openai" | "local_llm" | "ast_engine",
            "ast_result": {...},
            "genai_result": {...} | None,
            "scrubbed": bool
        }
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
    logger.info("AST engine found %d changes", change_count)

    if change_count >= AST_CHANGE_THRESHOLD:
        logger.info("AST results sufficient — skipping GenAI escalation")
        return result

    # ── Step 2: PII scrub before sending to GenAI ─────────────────────────────
    logger.info("AST changes below threshold — escalating to GenAI")
    scrubbed_code = mask_payload_for_infosec(abap_source)
    result["scrubbed"] = True

    prompt = _build_analysis_prompt(scrubbed_code, ast_result, context)

    # ── Step 3: Route based on LLM_MODE ───────────────────────────────────────
    if LLM_MODE == "airgapped":
        # Air-gapped mode: try local LLM only, no cloud fallback
        genai_result = _invoke_local_llm(prompt)
        if genai_result is not None:
            result["backend_used"] = "local_llm"
            result["genai_result"] = genai_result
        else:
            logger.warning("Air-gapped LLM unavailable — returning AST-only results")

    elif LLM_MODE == "cloud":
        # Cloud-only mode: try Azure OpenAI only
        genai_result = _invoke_azure_openai(prompt)
        if genai_result is not None:
            result["backend_used"] = "azure_openai"
            result["genai_result"] = genai_result
        else:
            logger.warning("Azure OpenAI unavailable — returning AST-only results")

    else:
        # Auto mode: prefer local LLM if endpoint is set, otherwise Azure OpenAI.
        # Full fallback chain: primary → secondary → AST-only.
        if LOCAL_LLM_ENDPOINT:
            # Air-gapped endpoint available — try it first
            genai_result = _invoke_local_llm(prompt)
            if genai_result is not None:
                result["backend_used"] = "local_llm"
                result["genai_result"] = genai_result
            else:
                # Fallback to Azure OpenAI
                logger.info("Local LLM failed — falling back to Azure OpenAI")
                genai_result = _invoke_azure_openai(prompt)
                if genai_result is not None:
                    result["backend_used"] = "azure_openai"
                    result["genai_result"] = genai_result
                else:
                    logger.warning(
                        "Both Local LLM and Azure OpenAI unavailable — "
                        "returning AST-only results"
                    )
        else:
            # No local endpoint — try Azure OpenAI first
            genai_result = _invoke_azure_openai(prompt)
            if genai_result is not None:
                result["backend_used"] = "azure_openai"
                result["genai_result"] = genai_result
            else:
                # Fallback to local LLM (maybe configured at runtime)
                genai_result = _invoke_local_llm(prompt)
                if genai_result is not None:
                    result["backend_used"] = "local_llm"
                    result["genai_result"] = genai_result
                else:
                    logger.warning(
                        "Both Azure OpenAI and Local LLM unavailable — "
                        "returning AST-only results"
                    )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


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


def _invoke_azure_openai(prompt: str) -> Optional[Dict]:
    """
    Invoke Azure OpenAI via the azure_openai_engine module.

    Returns parsed findings dict or None on failure.
    """
    try:
        from azure_openai_engine import analyze_abap_code

        result = analyze_abap_code(
            source_code=prompt,
            issue_context={"program_name": "PII_SCRUBBED", "unfixed_issues": []},
        )

        if result.get("_error"):
            logger.warning(
                "Azure OpenAI returned error: %s", result.get("_error_reason")
            )
            return None

        return _parse_genai_response(
            json.dumps(result.get("fixes", [])), "azure_openai"
        )

    except ImportError:
        logger.warning("azure_openai_engine module not available")
        return None
    except Exception as exc:
        logger.warning("Azure OpenAI invocation failed: %s", exc)
        return None


def _invoke_local_llm(prompt: str) -> Optional[Dict]:
    """
    Invoke the air-gapped local LLM running on a GPU instance.
    Uses the OpenAI-compatible chat completions format.

    Returns parsed findings dict or None on failure.
    """
    endpoint = LOCAL_LLM_ENDPOINT
    if not endpoint:
        logger.info("Local LLM endpoint not configured — skipping")
        return None

    try:
        import requests

        # OpenAI-compatible chat completions format
        payload = {
            "model": "local-model",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an SAP ABAP migration expert. "
                        "Respond with ONLY valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 4096,
            "temperature": 0.1,
        }

        response = requests.post(
            endpoint,
            json=payload,
            timeout=120,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()

        # OpenAI-compatible response format
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if not content:
            # Fallback for non-chat completion format
            content = data.get("choices", [{}])[0].get("text", "")

        return _parse_genai_response(content, "local_llm")

    except ImportError:
        logger.warning("requests package not available for local LLM call")
        return None
    except Exception as exc:
        logger.warning("Local LLM invocation failed: %s", exc)
        return None


def _parse_genai_response(content: str, model: str) -> Dict[str, Any]:
    """Attempt to parse GenAI response as JSON findings list."""
    text = content.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        findings = json.loads(text)
        if not isinstance(findings, list):
            findings = [findings]
        return {"findings": findings, "model": model}
    except json.JSONDecodeError:
        # Try extracting JSON from mixed text
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            try:
                findings = json.loads(text[start:end])
                return {"findings": findings, "model": model}
            except json.JSONDecodeError:
                pass
        return {"findings": [], "raw_response": content, "model": model}
