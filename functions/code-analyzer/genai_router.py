"""
genai_router.py — Dual-path GenAI Router for Migrate4HANA
=========================================================
Routes ABAP code analysis requests to the optimal GenAI backend:

  1. AST Engine        (local, zero-latency, deterministic)
  2. Claude Opus 4.6   (cloud, via Anthropic API)
  3. Air-gapped LLM    (Gemma 4 26B via Ollama on Azure GPU VM, for classified workloads)

Routing Logic:
  - Always run the AST engine first (structural, deterministic transforms)
  - If AST produces fewer changes than the threshold, escalate to GenAI
    for deeper semantic analysis (custom logic patterns, BP implications)
  - LLM_MODE controls the backend: "auto" (default), "cloud", "airgapped"
  - All payloads are PII-scrubbed via data_scrubber before GenAI dispatch
  - Fallback chain (auto mode): Claude → Local LLM → AST-only

Environment:
    LOCAL_LLM_HOST          — Ollama host for air-gapped Gemma 4 (e.g. http://10.0.5.4:11434)
    LOCAL_LLM_MODEL         — Ollama model tag (default "gemma4:26b")
    AST_CHANGE_THRESHOLD    — minimum AST changes to skip GenAI (default 3)
    LLM_MODE                — "auto" | "cloud" | "airgapped"
"""

import json
import os
import logging
from typing import Any, Dict, Optional

import ollama as ollama_sdk

import claude_engine
from data_scrubber import mask_payload_for_infosec
from abap_ast_engine import process_abap_file

logger = logging.getLogger("genai_router")
logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
LOCAL_LLM_HOST = os.environ.get("LOCAL_LLM_HOST", "")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "gemma4:26b")
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
            "backend_used": "claude_opus" | "local_llm" | "ast_engine",
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

    # ── Step 3: Route based on LLM_MODE ───────────────────────────────────────
    if LLM_MODE == "airgapped":
        genai_result = _invoke_local_llm(scrubbed_code)
        if genai_result is not None:
            result["backend_used"] = "local_llm"
            result["genai_result"] = genai_result
        else:
            logger.warning("Air-gapped LLM unavailable — returning AST-only results")

    elif LLM_MODE == "cloud":
        genai_result = _invoke_claude(scrubbed_code, context)
        if genai_result is not None:
            result["backend_used"] = "claude_opus"
            result["genai_result"] = genai_result
        else:
            logger.warning("Claude API unavailable — returning AST-only results")

    else:
        # Auto mode: try Claude first, fall back to local LLM, then AST-only
        genai_result = _invoke_claude(scrubbed_code, context)
        if genai_result is not None:
            result["backend_used"] = "claude_opus"
            result["genai_result"] = genai_result
        else:
            logger.info("Claude unavailable — falling back to local LLM")
            genai_result = _invoke_local_llm(scrubbed_code)
            if genai_result is not None:
                result["backend_used"] = "local_llm"
                result["genai_result"] = genai_result
            else:
                logger.warning(
                    "Both Claude and Local LLM unavailable — "
                    "returning AST-only results"
                )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _invoke_claude(
    source_code: str, context: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """
    Invoke Claude Opus 4.6 via the claude_engine module.

    Returns parsed result dict or None on failure.
    """
    try:
        result = claude_engine.analyze_abap_code(
            source_code=source_code,
            issue_context=context,
        )

        if result.get("_error"):
            logger.warning(
                "Claude returned error: %s", result.get("_error_reason")
            )
            return None

        return result

    except Exception as exc:
        logger.warning("Claude invocation failed: %s", exc)
        return None


def _invoke_local_llm(prompt: str) -> Optional[Dict[str, Any]]:
    """
    Invoke the air-gapped Gemma 4 (26B) model via Ollama on an Azure GPU VM.

    Connects to the Ollama API at LOCAL_LLM_HOST using the ``ollama`` Python SDK.
    Timeout: 120 seconds. Handles connection errors gracefully.

    Returns parsed findings dict or None on failure.
    """
    host = LOCAL_LLM_HOST
    if not host:
        logger.info("LOCAL_LLM_HOST not configured — skipping air-gapped LLM")
        return None

    try:
        client = ollama_sdk.Client(host=host, timeout=120)

        logger.info(
            "Invoking Ollama (%s) at %s", LOCAL_LLM_MODEL, host
        )

        response = client.chat(
            model=LOCAL_LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an SAP S/4HANA migration expert. "
                        "Fix the following ABAP code. "
                        "Respond with ONLY valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.1, "num_predict": 4096},
        )

        content = response["message"]["content"]
        logger.info(
            "Ollama response: %d chars (model=%s)",
            len(content), LOCAL_LLM_MODEL,
        )
        return _parse_genai_response(content, f"ollama/{LOCAL_LLM_MODEL}")

    except ConnectionError as exc:
        logger.warning("Cannot connect to Ollama at %s: %s", host, exc)
        return None
    except Exception as exc:
        logger.warning("Ollama invocation failed: %s", exc)
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
