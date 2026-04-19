"""
azure_openai_engine.py — Azure OpenAI Engine for Migrate4HANA
==============================================================
Replaces bedrock_genai_engine.py. Invokes Azure OpenAI (GPT-4 / GPT-4o)
to remediate ABAP code issues that the deterministic AST engine cannot
handle (Dynpro calls, native SQL, SAPGui FMs, complex semantic patterns).

Used as Phase 3 of Stage 5 in the local pipeline (run_local_pipeline.py).

Authentication:
    - AZURE_OPENAI_API_KEY env var, or
    - DefaultAzureCredential (Managed Identity / Azure CLI)

Environment:
    AZURE_OPENAI_ENDPOINT       — e.g. "https://migrate4hana-oai.openai.azure.com/"
    AZURE_OPENAI_API_KEY        — API key (or fetched from Key Vault)
    AZURE_OPENAI_DEPLOYMENT     — deployment name (default "gpt-4")
    AZURE_OPENAI_API_VERSION    — API version (default "2024-02-01")
"""

import json
import os
import logging
import time
from typing import Any, Dict, List, Optional

import openai
from openai import AzureOpenAI

logger = logging.getLogger("azure_openai_engine")
logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")

MAX_TOKENS = 8192
MAX_SOURCE_CHARS = 60_000
TEMPERATURE = 0.1
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1  # seconds — exponential: 1s, 2s, 4s

# Cached client
_openai_client: Optional[AzureOpenAI] = None


def _create_client() -> AzureOpenAI:
    """
    Create and cache an AzureOpenAI client.

    Uses API key if available, otherwise falls back to
    DefaultAzureCredential (Managed Identity / Azure CLI token).
    """
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    if not AZURE_OPENAI_ENDPOINT:
        raise EnvironmentError(
            "AZURE_OPENAI_ENDPOINT is not set. "
            "Set it to your Azure OpenAI resource endpoint."
        )

    if AZURE_OPENAI_API_KEY:
        _openai_client = AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
        )
        logger.info(
            "AzureOpenAI client initialised with API key "
            "(endpoint=%s, deployment=%s)",
            AZURE_OPENAI_ENDPOINT,
            AZURE_OPENAI_DEPLOYMENT,
        )
    else:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        _openai_client = AzureOpenAI(
            azure_ad_token_provider=token_provider,
            api_version=AZURE_OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
        )
        logger.info(
            "AzureOpenAI client initialised with DefaultAzureCredential "
            "(endpoint=%s, deployment=%s)",
            AZURE_OPENAI_ENDPOINT,
            AZURE_OPENAI_DEPLOYMENT,
        )

    return _openai_client


# ═══════════════════════════════════════════════════════════════════════════════
# RETRY LOGIC
# ═══════════════════════════════════════════════════════════════════════════════


def _call_with_retry(
    messages: List[Dict[str, str]], max_retries: int = MAX_RETRIES
) -> Optional[str]:
    """
    Call Azure OpenAI chat completions with exponential backoff on rate limits.

    Args:
        messages:    List of chat messages (system + user).
        max_retries: Maximum number of retry attempts.

    Returns:
        Response content string, or None on unrecoverable failure.
    """
    client = _create_client()
    last_error = "Unknown error"

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Azure OpenAI invoke attempt %d/%d (deployment=%s)",
                attempt, max_retries, AZURE_OPENAI_DEPLOYMENT,
            )

            response = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=messages,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
            )

            content = response.choices[0].message.content or ""
            usage = response.usage
            logger.info(
                "Azure OpenAI response: %d chars, "
                "prompt_tokens=%s, completion_tokens=%s",
                len(content),
                getattr(usage, "prompt_tokens", "?"),
                getattr(usage, "completion_tokens", "?"),
            )
            return content

        except openai.RateLimitError as exc:
            wait = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            logger.warning(
                "Azure OpenAI rate limited (429), retrying in %ds… (%s)",
                wait, exc,
            )
            if attempt < max_retries:
                time.sleep(wait)
                last_error = f"Rate limited after {max_retries} attempts"
                continue
            logger.error("Azure OpenAI rate limit exhausted after %d attempts", max_retries)
            return None

        except openai.AuthenticationError as exc:
            logger.error("Azure OpenAI authentication failed: %s", exc)
            return None

        except openai.APIConnectionError as exc:
            logger.error(
                "Cannot connect to Azure OpenAI endpoint '%s': %s",
                AZURE_OPENAI_ENDPOINT, exc,
            )
            if attempt < max_retries:
                time.sleep(RETRY_BACKOFF_BASE * attempt)
                continue
            return None

        except openai.APIError as exc:
            logger.error("Azure OpenAI API error: %s", exc)
            last_error = str(exc)
            if attempt < max_retries:
                time.sleep(RETRY_BACKOFF_BASE * attempt)
                continue
            return None

    logger.error("Azure OpenAI invocation failed: %s", last_error)
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

        logger.warning("Could not parse Azure OpenAI response as JSON — returning raw text")
        return {
            "fixes": [],
            "recommendations": [],
            "raw_response": content,
            "full_remediated_source": None,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════


def analyze_abap_code(
    source_code: str, issue_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Analyse ABAP source code for S/4HANA migration issues using Azure OpenAI.

    Drop-in replacement for bedrock_genai_engine's public API.

    Args:
        source_code:   Raw ABAP source code.
        issue_context: Optional dict with keys like ``program_name``,
                       ``unfixed_issues``, ``ast_changes_summary``.

    Returns:
        Dict with keys: remediated_code, explanation, confidence, fixes,
        recommendations.  On failure, includes ``_error`` and ``_error_reason``.
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

    system_msg = (
        "You are an ABAP code remediation engine. You output ONLY valid JSON. "
        "Never include conversational text, greetings, or explanations outside "
        "the JSON structure. All ABAP code must be wrapped in ```abap``` blocks. "
        "If you cannot produce a fix, return the JSON with an empty fixes array."
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

STRICT OUTPUT RULES — FOLLOW EXACTLY:
- Return ONLY a valid JSON object. No conversational text before or after.
- All code values must contain ONLY raw ABAP code wrapped in ```abap ... ``` blocks.
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
  "program": "{program_name}",
  "fixes": [
    {{
      "rule_id": "MANUAL-001",
      "line": 42,
      "original_code": "```abap\\nCALL SCREEN 100.\\n```",
      "fixed_code": "```abap\\n* Fiori replacement\\n```",
      "explanation": "Why this fix is needed.",
      "confidence": "high|medium|low"
    }}
  ],
  "recommendations": ["Free-text architectural recommendations"],
  "full_remediated_source": "```abap\\n<complete program with fixes>\\n```"
}}"""

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_prompt},
    ]

    logger.info(
        "Sending %s to Azure OpenAI (%d unfixed issues, %d chars source)",
        program_name, len(unfixed_issues), len(source_code),
    )

    content = _call_with_retry(messages)

    if content is None:
        return {
            "_error": True,
            "_error_reason": "Azure OpenAI invocation failed",
            "fixes": [],
            "recommendations": [],
            "remediated_code": None,
            "explanation": None,
            "confidence": None,
        }

    result = _parse_response(content)

    # Normalise output to match bedrock_genai_engine format
    if "full_remediated_source" in result:
        result["remediated_code"] = result["full_remediated_source"]
    result.setdefault("explanation", "Azure OpenAI analysis complete")
    result.setdefault("confidence", "medium")
    result.setdefault("fixes", [])
    result.setdefault("recommendations", [])

    return result


def check_openai_connectivity() -> bool:
    """Quick check that Azure OpenAI is reachable with current credentials."""
    try:
        client = _create_client()
        # Lightweight call to verify credentials and endpoint
        response = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        logger.info(
            "Azure OpenAI connectivity OK (endpoint=%s, deployment=%s)",
            AZURE_OPENAI_ENDPOINT,
            AZURE_OPENAI_DEPLOYMENT,
        )
        return True
    except Exception as exc:
        logger.warning("Azure OpenAI connectivity check failed: %s", exc)
        return False
