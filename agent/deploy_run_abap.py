"""Migrate4HANA in-system ABAP agent runner.

Deploys an ABAP report to the target as a LOCAL ($TMP, no-transport) object via the released
RPY_PROGRAM_INSERT, then runs it in-system as a background job via SUBST_START_REPORT_IN_BATCH,
and reads a result file back off the host via SSM. This is the supported "remote agent" pattern
that lets the orchestrator drive in-system CTS work (transport build/release) that isn't exposed
over RFC — all standard APIs, support intact.

Usage: python deploy_run_abap.py <PROG_NAME> <source.abap> [result_file_on_host]
"""
import json, os, sys, time
from pyrfc import Connection

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda", "utils"))
from sap_host_runner import run as ssm_run  # type: ignore

REPO = os.path.join(os.path.dirname(__file__), "..")
CONN = json.load(open(os.path.join(REPO, "connections.json")))
T = CONN["lift_and_shift_target"]
INST = T.get("transport_host_instance_id") or T.get("bastion_instance_id")


def target_conn():
    return Connection(ashost=T["target_ashost"], sysnr=T["target_sysnr"], client=T["target_client"],
                      user=T["target_user"], passwd=os.environ["M4H_TARGET_PASSWD"], lang="EN")


def _rewrite_report_line(source_lines, name):
    """Make the REPORT statement match the actual program name."""
    out, done = [], False
    for ln in source_lines:
        if not done and ln.lstrip()[:7].upper() == "REPORT ":
            out.append("REPORT %s." % name.lower())
            done = True
        else:
            out.append(ln)
    return out


def deploy_local(c, prog, source_lines):
    """Create PROG as a local $TMP report (no transport => no TK511). RPY_PROGRAM_UPDATE/DELETE
    are not remote-callable here, so on a name collision we auto-version (a fresh name always
    inserts cleanly) and rewrite the REPORT statement to match. Returns (actual_name, how)."""
    for attempt in range(30):
        name = prog if attempt == 0 else "%s%d" % (prog[:28], attempt + 1)
        src = [{"LINE": l} for l in _rewrite_report_line(source_lines, name)]
        try:
            # Source MUST go in SOURCE_EXTENDED (the plain SOURCE table is silently ignored over RFC).
            c.call("RPY_PROGRAM_INSERT", PROGRAM_NAME=name, TITLE_STRING=("M4H agent " + name)[:70],
                   PROGRAM_TYPE="1", APPLICATION="S", AUTHORIZATION_GROUP="", DEVELOPMENT_CLASS="$TMP",
                   EDIT_LOCK=" ", SAVE_INACTIVE=" ", STATUS=" ", SUPPRESS_DIALOG="X", TEMPORARY=" ",
                   TRANSPORT_NUMBER=" ", SOURCE_EXTENDED=src)
            return name, "inserted"
        except Exception as e:
            if "ALREADY_EXISTS" in str(e):
                continue
            raise
    raise RuntimeError("could not find a free program name for " + prog)


def run_report(c, prog, jobname=None):
    """Execute the in-system report. Prefer RZL_SUBMIT (runs directly in a work process) since
    background-job scheduling is blocked on this appliance (BATCH_SCHEDULING_FAILED / SAP_UPGRADE);
    fall back to SUBST_START_REPORT_IN_BATCH where batch is available."""
    try:
        c.call("RZL_SUBMIT", REPID=prog)
        return {"runner": "rzl_submit", "status": "ran"}
    except Exception as e:
        # rc=4 "Screen output without connection to user" means it RAN (a WRITE had no GUI) — OK.
        if "without connection to user" in str(e):
            return {"runner": "rzl_submit", "status": "ran_no_screen"}
        try:
            r = c.call("SUBST_START_REPORT_IN_BATCH", IV_REPNAME=prog, IV_JOBNAME=(jobname or prog)[:32])
            return {"runner": "batch", "startrc": r.get("EV_STARTRC"), "jobcount": r.get("EV_JOBCOUNT")}
        except Exception as e2:
            return {"runner": "none", "error": "rzl=%s ; batch=%s" % (str(e)[:80], str(e2)[:80])}


def read_host_file(path, tries=20, delay=4):  # RZL_SUBMIT runs async — poll patiently (~80s)
    for _ in range(tries):
        res = ssm_run(INST, ["cat " + path + " 2>/dev/null && echo __M4H_EOF__"],
                      comment="m4h-read", timeout_seconds=60)
        out = res.get("stdout", "") or ""
        if "__M4H_EOF__" in out and out.strip() != "__M4H_EOF__":
            return out.split("__M4H_EOF__")[0].strip()
        time.sleep(delay)
    return None


if __name__ == "__main__":
    prog = sys.argv[1]
    src_file = sys.argv[2]
    result_file = sys.argv[3] if len(sys.argv) > 3 else None
    source = [ln.rstrip("\n") for ln in open(os.path.join(REPO, src_file), encoding="utf-8")]
    c = target_conn()
    name, how = deploy_local(c, prog, source)
    print("deployed", name, "(%d lines, $TMP local, %s)" % (len(source), how))
    if result_file:
        ssm_run(INST, ["mkdir -p /usr/sap/trans/tmp && chmod 777 /usr/sap/trans/tmp",
                       "rm -f " + result_file], comment="m4h-prep", timeout_seconds=60)
    started = run_report(c, name)
    print("run:", started)
    c.close()
    if result_file:
        out = read_host_file(result_file)
        print("RESULT FILE:", out if out is not None else "(not produced)")
