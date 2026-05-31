"""
anthropic_client.py - direct Anthropic API client (drop-in for Bedrock).

Used by code-analyzer Lambda when the AWS account does not have Bedrock model
access. Calls https://api.anthropic.com/v1/messages over the Lambda's NAT
egress; no Bedrock VPC endpoint required.

Auth: API key fetched from Secrets Manager at module load and cached for the
warm container lifetime. Set M4H_ANTHROPIC_SECRET_ARN to the secret ARN; the
secret may store either the raw key or a JSON object with `api_key` / `apiKey`.

Models:
  - default: claude-sonnet-4-6 (cheap, fast, near-Opus quality on narrow tasks)
  - escalation: claude-opus-4-7 (used by callers on retry of failed remediations)
Override via ANTHROPIC_MODEL_ID / ANTHROPIC_ESCALATION_MODEL.

Returns text on success, None on any failure (never raises) - the pipeline must
not halt because the LLM is down.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger("anthropic_client")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL_ID", "claude-sonnet-4-6")
ESCALATION_MODEL = os.environ.get("ANTHROPIC_ESCALATION_MODEL", "claude-opus-4-7")

_HTTP_TIMEOUT_S = int(os.environ.get("ANTHROPIC_HTTP_TIMEOUT_S", "60"))
_MAX_RETRIES = int(os.environ.get("ANTHROPIC_MAX_RETRIES", "2"))
_RETRY_BACKOFF_S = int(os.environ.get("ANTHROPIC_RETRY_BACKOFF_S", "3"))

_cached_api_key: Optional[str] = None


def _load_api_key() -> Optional[str]:
    """Resolve the Anthropic API key, preferring Secrets Manager.

    Order:
      1. ANTHROPIC_API_KEY env var (set this for local dev)
      2. M4H_ANTHROPIC_SECRET_ARN -> SecretsManager:GetSecretValue (prod)
    """
    global _cached_api_key
    if _cached_api_key:
        return _cached_api_key

    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        _cached_api_key = env_key.strip()
        return _cached_api_key

    secret_arn = os.environ.get("M4H_ANTHROPIC_SECRET_ARN")
    if not secret_arn:
        logger.warning(
            "Anthropic API key unavailable: neither ANTHROPIC_API_KEY nor "
            "M4H_ANTHROPIC_SECRET_ARN is set")
        return None

    try:
        import boto3
        client = boto3.client(
            "secretsmanager",
            region_name=os.environ.get("AWS_REGION", "us-east-1"))
        resp = client.get_secret_value(SecretId=secret_arn)
        raw = resp.get("SecretString") or ""
        try:
            parsed = json.loads(raw)
            key = parsed.get("api_key") or parsed.get("apiKey") or parsed.get("ANTHROPIC_API_KEY")
            _cached_api_key = (key or raw).strip()
        except json.JSONDecodeError:
            _cached_api_key = raw.strip()
        return _cached_api_key
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to load Anthropic API key from %s: %s", secret_arn, e)
        return None


def invoke_claude(prompt: str,
                  model: Optional[str] = None,
                  system: Optional[str] = None,
                  max_tokens: int = 4096,
                  temperature: float = 0.0) -> Optional[str]:
    """POST to Anthropic /v1/messages and return the assistant's text.

    Returns None on auth failure, network error, or empty response - callers
    are expected to handle None and fall through to their quarantine path.
    """
    api_key = _load_api_key()
    if not api_key:
        return None

    model_id = model or DEFAULT_MODEL
    payload: dict = {
        "model": model_id,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
        },
    )

    last_err = "unknown"
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
                resp_body = resp.read().decode("utf-8")
            data = json.loads(resp_body)
            blocks = data.get("content") or []
            text_parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
            text = "".join(text_parts)
            if not text.strip():
                logger.warning("Anthropic returned empty content (model=%s)", model_id)
                return None
            usage = data.get("usage", {})
            logger.info("Anthropic OK: model=%s input=%s output=%s chars=%d",
                        model_id, usage.get("input_tokens", "?"),
                        usage.get("output_tokens", "?"), len(text))
            return text
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")
            except Exception:
                pass
            last_err = f"HTTP {e.code}: {err_body[:300]}"
            # 429 / 5xx are retriable; 4xx other than 429 are not
            if e.code == 429 or 500 <= e.code < 600:
                if attempt < _MAX_RETRIES:
                    wait = _RETRY_BACKOFF_S * attempt
                    logger.warning("Anthropic %s, retrying in %ds (attempt %d/%d)",
                                   e.code, wait, attempt, _MAX_RETRIES)
                    time.sleep(wait)
                    continue
            logger.error("Anthropic invocation failed: %s", last_err)
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_S * attempt)
                continue
            logger.error("Anthropic network error after %d attempts: %s",
                         _MAX_RETRIES, last_err)
            return None
        except Exception as e:  # noqa: BLE001
            logger.error("Anthropic unexpected error: %s", e)
            return None

    logger.error("Anthropic gave up after %d attempts: %s", _MAX_RETRIES, last_err)
    return None
