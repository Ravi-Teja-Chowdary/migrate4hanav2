"""
Input validation for Function handler events.
Validates event parameters at system boundaries before processing.
"""
import re
import logging

logger = logging.getLogger(__name__)

# SAP client numbers are 3-digit strings (000-999)
_CLIENT_RE = re.compile(r"^\d{3}$")
# Run IDs: alphanumeric + hyphens (UUIDs or manual-run)
_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9\-_]{1,64}$")


def validate_event(event: dict, required_fields: list = None) -> list:
    """
    Validate a Function handler event dict.

    Args:
        event: The incoming Durable Functions event.
        required_fields: List of dot-path field names that must be present,
                         e.g. ["metadata.run_id", "input.ecc_client"].

    Returns:
        List of error strings. Empty list means validation passed.
    """
    errors = []

    if not isinstance(event, dict):
        return ["Event must be a JSON object"]

    # Check required fields
    for field_path in (required_fields or []):
        parts = field_path.split(".")
        current = event
        for part in parts:
            if not isinstance(current, dict) or part not in current:
                errors.append(f"Missing required field: {field_path}")
                current = None
                break
            current = current[part]

    # Validate known field formats
    metadata = event.get("metadata", {})
    if isinstance(metadata, dict):
        run_id = metadata.get("run_id")
        if run_id is not None and not _RUN_ID_RE.match(str(run_id)):
            errors.append(f"Invalid run_id format: {run_id}")

    inp = event.get("input", {})
    if isinstance(inp, dict):
        ecc_client = inp.get("ecc_client")
        if ecc_client is not None and not _CLIENT_RE.match(str(ecc_client)):
            errors.append(f"Invalid ecc_client (must be 3 digits): {ecc_client}")

        mode = inp.get("mode")
        if mode is not None and mode not in ("full", "quick", "delta", "ecc_full"):
            errors.append(f"Invalid mode (must be full/quick/delta/ecc_full): {mode}")

        dry_run = inp.get("dry_run")
        if dry_run is not None and not isinstance(dry_run, bool):
            errors.append(f"dry_run must be boolean, got: {type(dry_run).__name__}")

    stage = event.get("stage")
    if stage is not None and not re.match(r"^[a-zA-Z0-9\-_]{1,50}$", str(stage)):
        errors.append(f"Invalid stage name: {stage}")

    if errors:
        logger.warning(f"Event validation failed: {errors}")

    return errors
