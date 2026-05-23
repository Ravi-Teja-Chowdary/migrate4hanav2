"""
data_scrubber.py — PII / secret masking for payloads dispatched to GenAI.

WARNING: This module is for *LLM dispatch only*. Do NOT call it on source code
that will be written to disk, used by the AST engine, or returned to a
transport builder — it deliberately mangles string literals, comments, and
high-entropy identifiers in ways that produce uncompilable ABAP.

It is invoked exclusively from genai_router.route_analysis() before sending
the prompt to Bedrock or Ollama. The on-disk remediated source is produced
from the *raw* AST output.

Scrubbing rules:
  1. Strip ABAP comments (`*` line-start and inline `"`).
  2. Replace single/back-tick string literals with placeholder.
  3. Mask high-risk patterns: emails, phone numbers, SSN-like, long tokens.

The "long token" pattern is intentionally conservative (length ≥ 28) so it
catches API keys and Bearer tokens but not legitimate ABAP identifiers
(the 30-char ABAP identifier limit means short ones are common).
"""
import re
import logging

logger = logging.getLogger("data_scrubber")

# High-risk patterns (emails, phone numbers, SSN-like, long tokens)
SENSITIVE_PATTERNS = [
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}",       # Email
    r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}",  # Phone
    r"\d{3}-\d{2}-\d{4}",                                       # SSN-like
    r"\b[A-Za-z0-9_\-]{28,}\b",                                 # API key / Bearer
]


def mask_payload_for_infosec(abap_code: str) -> str:
    """
    Mask string literals and PII patterns in an ABAP payload prior to LLM dispatch.

    This is destructive — the returned string is NOT valid ABAP. Use only for
    constructing GenAI prompts. Never write the result to disk or feed it to
    the AST engine / transport builder.
    """
    if not abap_code:
        return ""

    lines = abap_code.splitlines()
    cleaned_lines = []
    for line in lines:
        if line.strip().startswith('*'):
            continue
        # Inline comment stripper — only after the first " that isn't in a string
        if '"' in line:
            line = _strip_inline_comment(line)
        cleaned_lines.append(line)
    code = "\n".join(cleaned_lines)

    # Mask string literals
    code = re.sub(r"'[^']*'", "'<MASKED>'", code)
    code = re.sub(r"`[^`]*`", "`<MASKED>`", code)

    # Mask high-risk identifiers
    for pattern in SENSITIVE_PATTERNS:
        code = re.sub(pattern, "<MASKED>", code)

    return code


def _strip_inline_comment(line: str) -> str:
    """Remove a trailing ABAP inline comment ( `"` outside a string ) from one line."""
    in_str = False
    for i, ch in enumerate(line):
        if ch == "'":
            in_str = not in_str
        elif ch == '"' and not in_str:
            return line[:i].rstrip()
    return line
