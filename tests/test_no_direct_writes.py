"""
Static-scan test: enforce the two-plane principle.

Fails the build if any active Lambda contains a forbidden direct-write call
into S/4HANA. Allowed paths are: transport import (CTS/TMS/tp), Migration
Cockpit execution, IDoc inbound posting, BODS jobs.

Forbidden = anything that mutates S/4HANA state via custom-driven RFC.

This is the machine-verifiable enforcement of the rule documented in
MIGRATE4HANA-LIFT-AND-SHIFT.md and plan.md §10b-A.

Lambdas under lambda/_deprecated/ are excluded from the scan.
"""
import re
from typing import List, Tuple, Dict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LAMBDA_DIR = REPO_ROOT / "lambda"
DEPRECATED_DIR = LAMBDA_DIR / "_deprecated"

# Forbidden function-module names. Match as whole-word string literals
# in Python source. Case-insensitive.
FORBIDDEN_FMS = [
    # Business BAPIs that POST/CREATE/UPDATE in S/4
    r"BAPI_ACC_DOCUMENT_POST",
    r"BAPI_BUPA_CREATE_FROM_DATA",
    r"BAPI_BUPA_ROLE_ADD_2?",
    r"BAPI_BUPA_GROUPING_CREATE",
    r"BAPI_GOODSMVT_CREATE",
    r"BAPI_USER_ACTGROUPS_ASSIGN",
    r"BAPI_PO_CREATE1?",
    r"BAPI_SALESORDER_CREATEFROMDAT[12]",
    r"BAPI_MATERIAL_SAVEDATA",
    # Workbench / repository writes
    r"RPY_PROGRAM_INSERT",
    r"RPY_PROGRAM_UPDATE",
    r"RS_CORR_INSERT",
    # Role / auth direct creation
    r"PRGN_RFC_ROLE_CREATE",
    r"SUSR_USER_CHANGE_PASSWORD_RFC",
    # Integration infrastructure direct creation
    r"RFC_MODIFY_R3_DESTINATION",
    r"IDOC_PORT_CREATE",
    r"EDI_PARTNER_CREATE",
    r"EDI_PARTNER_ADD_MSGTYPE",
    # Customizing direct writes
    r"NUMBER_RANGE_INTERVAL_CREATE",
    r"CKML_START_MATERIAL_LEDGER",
    # Catch-all for custom Z* writes
    r"Z_MIGRATE4HANA_TABLE_INSERT",
]

# Transitional allow-list — Lambdas whose retool to remove direct writes
# is tracked as a separate Wave 2 todo. Removing entries from this list
# is the literal acceptance criterion for the corresponding retool todo.
# Each entry is a path relative to the repo root.
PENDING_RETOOL_ALLOWLIST = {
    "lambda/code-deployer/handler.py",         # retool-code-deployer
    "lambda/config-applier/handler.py",        # retool-config-applier
    "lambda/data-loader/handler.py",           # retool-data-loader
    "lambda/integration-activator/handler.py", # retool-integration-activator
    "lambda/role-provisioner/handler.py",      # retool-role-provisioner
}

# We only flag ACTUAL invocations: `conn.call("FM"` or `connection.call("FM"`
# or `.call('FM'`. This avoids false positives from rule libraries and docs
# that merely *reference* the FM name as data.
PATTERN = re.compile(
    r"""\.call\s*\(\s*['"](""" + "|".join(FORBIDDEN_FMS) + r""")['"]""",
    re.IGNORECASE,
)


def _scan_file(path: Path) -> List[Tuple[int, str, str]]:
    findings = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = PATTERN.search(line)
        if m:
            findings.append((lineno, m.group(1), line.strip()))
    return findings


def test_no_direct_s4_writes_in_active_lambdas():
    """No active Lambda may call a forbidden S/4 write function module."""
    if not LAMBDA_DIR.exists():
        return  # nothing to scan
    violations: Dict[str, list] = {}
    pending_seen = set()
    for py_file in LAMBDA_DIR.rglob("*.py"):
        # skip deprecated handlers
        try:
            py_file.relative_to(DEPRECATED_DIR)
            continue
        except ValueError:
            pass
        rel = str(py_file.relative_to(REPO_ROOT)).replace("\\", "/")
        findings = _scan_file(py_file)
        if findings:
            if rel in PENDING_RETOOL_ALLOWLIST:
                pending_seen.add(rel)
                continue
            violations[rel] = findings

    # Surface stale allow-list entries (already retooled but still listed).
    stale = PENDING_RETOOL_ALLOWLIST - pending_seen
    if stale:
        print(f"NOTE: {len(stale)} allow-list entries are now clean and can be removed: {sorted(stale)}")

    if violations:
        msg_lines = [
            "Forbidden direct-write call(s) into S/4HANA found in active Lambdas.",
            "Two-plane principle violated. See MIGRATE4HANA-LIFT-AND-SHIFT.md.",
            "",
        ]
        for fpath, finds in violations.items():
            msg_lines.append(f"  {fpath}:")
            for lineno, fm, line in finds:
                msg_lines.append(f"    line {lineno}: {fm}  -->  {line[:120]}")
        raise AssertionError("\n".join(msg_lines))


if __name__ == "__main__":
    import sys as _sys
    try:
        test_no_direct_s4_writes_in_active_lambdas()
        print("OK - no direct-write violations.")
    except AssertionError as e:
        # Windows console may be cp1252; force ASCII-safe output.
        msg = str(e).encode("ascii", errors="replace").decode("ascii")
        print(msg)
        _sys.exit(1)
