"""
bedrock_genai_engine.py — AWS Bedrock GenAI Engine for Migrate4HANA
===================================================================
Invokes Claude Opus 4.6 on AWS Bedrock to remediate ABAP code issues
that the deterministic AST engine cannot handle (Dynpro calls, native SQL,
SAPGui FMs, complex semantic patterns).

Used as Phase 3 of Stage 5 in the local pipeline (run_local_pipeline.py).

Requirements:
    - boto3 installed
    - AWS credentials configured via `aws configure`
    - Bedrock model access enabled for Claude Opus 4.6 in your AWS region
"""

import json
import os
import logging
import time
from typing import Dict, Any, List, Optional

import boto3
from botocore.exceptions import (
    ClientError,
    NoCredentialsError,
    EndpointConnectionError,
    BotoCoreError,
)

logger = logging.getLogger("bedrock_genai_engine")
logger.setLevel(logging.INFO)

# ── Configuration ─────────────────────────────────────────────────────────────
# Claude Opus 4.6 requires a cross-region inference profile (not raw model ID).
# Override via BEDROCK_MODEL_ID env var if using a custom inference profile ARN.
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-opus-4-6-v1")
BEDROCK_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
MAX_TOKENS = 8192
MAX_SOURCE_CHARS = 60_000  # Truncate very large programs to stay within token limits
MAX_RETRIES = 2
RETRY_BACKOFF = 3  # seconds


def _get_bedrock_client():
    """Create Bedrock runtime client using default AWS credential chain."""
    return boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


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
    """Invoke AWS Bedrock with Claude via invoke_model (Messages API).
    Uses array-format content blocks for compatibility with Claude Opus 4.6.
    Returns parsed response dict or error dict with _error/_error_reason."""
    last_error = "Unknown error"
    system_msg = (
        "You are an ABAP code remediation engine. You output ONLY valid JSON. "
        "Never include conversational text, greetings, or explanations outside "
        "the JSON structure. All ABAP code must be wrapped in ```abap``` blocks. "
        "If you cannot produce a fix, return the JSON with an empty fixes array."
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = _get_bedrock_client()

            # Use array-format content blocks (required by Claude Opus 4.6)
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": MAX_TOKENS,
                "system": [{"type": "text", "text": system_msg}],
                "messages": [{
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }],
                "temperature": 0.1,
            })

            logger.info(f"Bedrock invoke attempt {attempt}/{MAX_RETRIES} "
                        f"(model={BEDROCK_MODEL_ID}, region={BEDROCK_REGION}, "
                        f"prompt_len={len(prompt)})")

            response = client.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                body=body,
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            content_blocks = response_body.get("content", [])
            text = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text += block.get("text", "")

            if not text.strip():
                logger.warning("Bedrock returned empty content")
                return {"_error": True, "_error_reason": "Empty response from Bedrock",
                        "fixes": [], "recommendations": []}

            usage = response_body.get("usage", {})
            logger.info(f"Bedrock response: {len(text)} chars, "
                        f"input_tokens={usage.get('input_tokens', '?')}, "
                        f"output_tokens={usage.get('output_tokens', '?')}")

            return _parse_response(text)

        except NoCredentialsError:
            logger.error("AWS credentials not configured. Run 'aws configure' first.")
            return {"_error": True, "_error_reason": "AWS credentials not configured",
                    "fixes": [], "recommendations": []}
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            error_msg = e.response.get("Error", {}).get("Message", str(e))
            logger.error(f"Bedrock ClientError [{error_code}]: {error_msg}")
            if error_code == "AccessDeniedException":
                return {"_error": True, "_error_reason": f"Access denied for {BEDROCK_MODEL_ID}",
                        "fixes": [], "recommendations": []}
            elif error_code == "ThrottlingException" and attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF * attempt
                logger.warning(f"Bedrock throttled, retrying in {wait}s...")
                time.sleep(wait)
                last_error = f"Throttled after {MAX_RETRIES} attempts"
                continue
            else:
                return {"_error": True, "_error_reason": f"{error_code}: {error_msg}",
                        "fixes": [], "recommendations": []}
        except EndpointConnectionError:
            logger.error(f"Cannot connect to Bedrock endpoint in {BEDROCK_REGION}. "
                         f"Check region and network.")
            return {"_error": True, "_error_reason": f"Cannot connect to Bedrock in {BEDROCK_REGION}",
                    "fixes": [], "recommendations": []}
        except (BotoCoreError, Exception) as e:
            logger.error(f"Bedrock invocation failed: {e}")
            last_error = str(e)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF)
                continue
            return {"_error": True, "_error_reason": last_error,
                    "fixes": [], "recommendations": []}

    return {"_error": True, "_error_reason": last_error,
            "fixes": [], "recommendations": []}


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
    """Quick check that Bedrock is reachable with current credentials."""
    try:
        client = _get_bedrock_client()
        # Lightweight call to verify credentials and endpoint
        client.meta.service_model
        logger.info(f"Bedrock client initialized (region={BEDROCK_REGION}, model={BEDROCK_MODEL_ID})")
        return True
    except (NoCredentialsError, EndpointConnectionError, BotoCoreError) as e:
        logger.warning(f"Bedrock connectivity check failed: {e}")
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
