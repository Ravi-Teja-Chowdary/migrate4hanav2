"""
sap_log_collector — pull SAP host log files (sapinst, tp, dev_*, work
directory traces) into S3 with run_id prefix.
"""
import logging
import os
from .sap_host_runner import run

logger = logging.getLogger(__name__)


DEFAULT_LOG_PATHS = [
    "/usr/sap/trans/log/SLOG*.LOG",
    "/usr/sap/trans/log/ALOG*.LOG",
    "/usr/sap/trans/tmp/*.LOG",
    "/sapmnt/<SID>/global/security/data/SecStore.properties",
    "/usr/sap/<SID>/SUM/abap/log",
]


def collect(instance_id: str, run_id: str, s3_bucket: str,
            extra_paths: list[str] = None) -> dict:
    """Tar listed paths, upload to s3://bucket/logs/<run_id>/host.tar.gz."""
    paths = (extra_paths or []) + DEFAULT_LOG_PATHS
    tar_path = f"/tmp/{run_id}-host-logs.tar.gz"
    cmd = [
        f"tar czf {tar_path} {' '.join(paths)} 2>/dev/null || true",
        f"aws s3 cp {tar_path} s3://{s3_bucket}/logs/{run_id}/host.tar.gz",
        f"rm -f {tar_path}",
    ]
    return run(instance_id, cmd, comment=f"log-collect {run_id}", timeout_seconds=600)
