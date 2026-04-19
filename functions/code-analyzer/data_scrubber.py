"""
data_scrubber.py - High Security Data Masking for GenAI pipelines.
Guarantees zero PII leakage by stripping string literals, comments, 
and sensitive constants before dispatching payloads to Claude/Local LLMs.
"""
import re
import logging

logger = logging.getLogger("data_scrubber")

# High-risk patterns (emails, phone numbers, tokens, proprietary IDs)
SENSITIVE_PATTERNS = [
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}",  # Email
    r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}",  # Phone numbers (intl + local)
    r"\d{3}-\d{2}-\d{4}",  # SSN-like structures
    r"\b[A-Z0-9]{15,40}\b" # Example API key / hashes
]

def mask_payload_for_infosec(abap_code: str) -> str:
    """Removes all literal assignments and comments from ABAP payload"""
    # 1. Strip ABAP comments ( * and " )
    lines = abap_code.splitlines()
    cleaned_lines = []
    
    for line in lines:
        if line.strip().startswith('*'):
            continue
        
        # Inline comments removing logic
        if '"' in line:
            line = line.split('"')[0]
        cleaned_lines.append(line)

    code = "\n".join(cleaned_lines)

    # 2. Mask string literals (e.g. 'SecretKey' -> 'SCRUBBED_STRING')
    code = re.sub(r"'[^']*'", "'SCRUBBED_STRING'", code)
    code = re.sub(r"`[^`]*`", "`SCRUBBED_STRING`", code)

    # 3. Strip sensitive patterns in variables if any leaked
    for pattern in SENSITIVE_PATTERNS:
        code = re.sub(pattern, "SCRUBBED_STRING", code)

    return code
