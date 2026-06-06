"""
sap_host_runner — wrapper around AWS SSM Run Command for executing
shell commands on the SAP host (transport CI, tp imports, SWPM, log
fetch, etc.).

Extracted pattern from the legacy sum-orchestrator (see
lambda/_deprecated/sum-orchestrator/handler.py for original usage).
"""

from __future__ import annotations
import logging
import time
import boto3

logger = logging.getLogger(__name__)
ssm = boto3.client("ssm")


def run(instance_id: str, commands: list[str], comment: str = "",
        timeout_seconds: int = 1800, working_dir: str = "/tmp") -> dict:
    """Run a shell command on an SAP host via SSM and wait for completion.

    Returns: {status, stdout, stderr, return_code, command_id}
    """
    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands, "workingDirectory": [working_dir]},
        Comment=comment[:100] if comment else "migrate4hana",
        TimeoutSeconds=min(timeout_seconds, 2592000),
    )
    cmd_id = resp["Command"]["CommandId"]
    logger.info("ssm command %s dispatched to %s", cmd_id, instance_id)

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(5)
        inv = ssm.get_command_invocation(CommandId=cmd_id, InstanceId=instance_id)
        if inv["Status"] in ("Success", "Failed", "Cancelled", "TimedOut"):
            return {
                "status": inv["Status"],
                "stdout": inv.get("StandardOutputContent", ""),
                "stderr": inv.get("StandardErrorContent", ""),
                "return_code": inv.get("ResponseCode"),
                "command_id": cmd_id,
            }
    return {"status": "TimedOut", "command_id": cmd_id}
