"""
ollama_genai_engine.py — Local Air-Gapped LLM Engine for Migrate4HANA
======================================================================
Invokes a local Ollama instance running Gemma2 27B for sensitive ABAP
code analysis that must not leave the on-premises network.

Uses the `ollama` Python package if available, else falls back to
HTTP POST to OLLAMA_URL (default http://localhost:11434).

Environment variables:
  OLLAMA_URL   - Base URL of Ollama server (default: http://localhost:11434)
  OLLAMA_MODEL - Model to use (default: gemma2:27b)

Public API:
  invoke_ollama(prompt: str) -> Optional[Dict]

Return shape (matches _invoke_bedrock in genai_router):
  {"findings": [...], "model": "<model name>"}            on success
  {"findings": [], "raw_response": "<text>", "model": ...} if JSON parse fails
  None                                                    if Ollama unreachable
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("ollama_genai_engine")
logger.setLevel(logging.INFO)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma2:27b")
_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "120"))


def _parse_findings(content: str, model: str) -> Dict[str, Any]:
    """Parse the raw LLM text output into the router's findings shape."""
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, list):
            parsed = [parsed]
        return {"findings": parsed, "model": model}
    except json.JSONDecodeError:
        return {"findings": [], "raw_response": content, "model": model}


def _invoke_via_package(prompt: str) -> Optional[Dict[str, Any]]:
    """Prefer the official ollama Python client when available."""
    try:
        import ollama  # type: ignore
    except ImportError:
        return None

    try:
        client_kwargs = {}
        if OLLAMA_URL and OLLAMA_URL != "http://localhost:11434":
            client_kwargs["host"] = OLLAMA_URL
        client = ollama.Client(**client_kwargs) if client_kwargs else ollama
        response = client.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        content = ""
        if isinstance(response, dict):
            content = (response.get("message") or {}).get("content", "") or response.get("response", "")
        else:
            msg = getattr(response, "message", None)
            content = getattr(msg, "content", "") if msg is not None else ""
        return _parse_findings(content, OLLAMA_MODEL)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Ollama package invocation failed: {e}")
        return None


def _invoke_via_http(prompt: str) -> Optional[Dict[str, Any]]:
    """HTTP fallback — POST to /api/generate on the Ollama server."""
    try:
        import requests  # type: ignore
    except ImportError:
        logger.warning("Neither `ollama` nor `requests` package is available; cannot reach Ollama")
        return None

    url = f"{OLLAMA_URL}/api/generate"
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    try:
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        content = body.get("response", "") if isinstance(body, dict) else ""
        return _parse_findings(content, OLLAMA_MODEL)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Ollama HTTP invocation failed ({url}): {e}")
        return None


def invoke_ollama(prompt: str) -> Optional[Dict[str, Any]]:
    """
    Invoke the configured Ollama server.

    Order of attempts:
      1. Official `ollama` Python package (if installed)
      2. Raw HTTP POST to {OLLAMA_URL}/api/generate

    Returns None on unreachable server / missing clients so the caller can
    gracefully fall back to another backend.
    """
    result = _invoke_via_package(prompt)
    if result is not None:
        return result
    return _invoke_via_http(prompt)
