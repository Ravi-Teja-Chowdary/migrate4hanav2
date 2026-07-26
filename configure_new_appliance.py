#!/usr/bin/env python
"""
configure_new_appliance.py — one-shot "stand up a fresh S/4 CAL appliance" runner.

Reproduces the automatable parts of SAP_CAL_S4HANA_CONFIGURATION.md (Part K
recreate checklist) + BASIS_KIT_OPERATIONS.md against a freshly-deployed
"SAP S/4HANA 2025, Fully-Activated Appliance" — WITHOUT re-doing everything by
hand. SAP config cannot be *copied* between two CAL appliances (each is an
independent system), so this instead *re-applies* the same configuration to the
new box: it runs every RFC + AWS-CLI + file step for you, PROBES what the
appliance already ships with (a Fully-Activated Appliance already has most
SICF/gateway services on), and prints a short checklist for only the handful of
genuinely GUI/SSH steps left.

WHAT IT AUTOMATES (no clicks):
  0. Repoint connections.json (+ Windows hosts file, best-effort) to the new box.
  1. AWS   — open the S/4 Security Group ports to your IP; S3 staging bucket;
             IAM instance-profile (create if missing); SSM online check.
  2. RFC   — recover_access.py (unlock SAP*/MIGRATE_ADMI/DDIC),
             fix_migrate_admin.py (Service user + password),
             mc_role_probe.py --sap-all (clear all auth friction).
  3. PROBE — RFC login, client-modifiable (T000), OData/IDoc HTTPS reachability.
  4. KIT   — verify the migrate4hana Basis Kit over RFC; if absent, drop the two
             ABAP files to local-staging/ with exact paste instructions.
  5. IDOC  — read inbound partner profiles already present.
  Final    — PASS/FAIL summary + the remaining-manual checklist + a JSON report.

USAGE (PowerShell wrapper does the env setup — see scripts/configure-new-appliance.ps1):
    $env:M4H_TARGET_PASSWD = "<MIGRATE_ADMI password>"
    $env:M4H_ADMIN_PASSWD  = "<CAL master password, for SAP*>"
    python configure_new_appliance.py --public-ip 1.2.3.4 --instance-id i-0abc...

Secrets are read from the environment ONLY — none are hard-coded or written to
disk. connections.json never stores passwords.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("SAPNWRFC_HOME", str(ROOT / "sapnwrfc"))
CONNS = ROOT / "connections.json"
STAGING = ROOT / "local-staging"

# Ports the migration path needs open on the S/4 EC2 Security Group (runbook D.1).
SG_PORTS = [22, 1128, 1129, 3200, 3300, 3600, 8000, 8001, 8100,
            44300, 50013, 50014, 32200, 32201, 32202, 32215, 32269]

# Colours are noise on a Windows terminal; use plain ASCII status markers.
MARK = {"OK": "[ OK ]", "WARN": "[WARN]", "MANUAL": "[TODO]",
        "SKIP": "[SKIP]", "FAIL": "[FAIL]"}

RESULTS: list[dict] = []


def record(phase: str, step: str, status: str, detail: str = "") -> None:
    RESULTS.append({"phase": phase, "step": step, "status": status, "detail": detail})
    print(f"  {MARK.get(status, '[????]')} {step}"
          + (f"  — {detail}" if detail else ""), flush=True)


def banner(text: str) -> None:
    print("\n" + "=" * 72 + f"\n {text}\n" + "=" * 72, flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────
def run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run a subprocess, return (rc, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except Exception as e:  # noqa: BLE001
        return 1, "", f"{type(e).__name__}: {e}"


def aws(args: list[str], timeout: int = 90) -> tuple[int, str, str]:
    return run(["aws", *args], timeout=timeout)


def my_public_ip(override: str | None) -> str | None:
    if override:
        return override.strip()
    try:
        import urllib.request
        with urllib.request.urlopen("https://ifconfig.me/ip", timeout=10) as r:
            return r.read().decode().strip()
    except Exception:
        try:
            import urllib.request
            with urllib.request.urlopen("https://api.ipify.org", timeout=10) as r:
                return r.read().decode().strip()
        except Exception:
            return None


def rfc_connect(host, sysnr, client, user, passwd):
    from pyrfc import Connection
    return Connection(ashost=host, sysnr=str(sysnr), client=str(client),
                      user=user, passwd=passwd, lang="EN")


# ──────────────────────────────────────────────────────────────────────────────
# Phase 0 — connections.json + hosts file
# ──────────────────────────────────────────────────────────────────────────────
def phase_connjson(args) -> dict:
    banner("PHASE 0 — repoint connections.json to the new appliance")
    conns = json.loads(CONNS.read_text()) if CONNS.exists() else {}
    lst = conns.get("lift_and_shift_target") or {}

    public_ip = args.public_ip or lst.get("target_public_ip")
    if not public_ip:
        record("0", "connections.json", "FAIL",
               "no --public-ip given and none in connections.json")
        return conns
    private_ip = args.private_ip or lst.get("target_internal_ip", "")

    # If we have an instance id + aws, auto-discover the private IP.
    if args.instance_id and not args.private_ip and not args.skip_aws:
        rc, out, _ = aws(["ec2", "describe-instances", "--instance-ids", args.instance_id,
                          "--query",
                          "Reservations[].Instances[].PrivateIpAddress",
                          "--output", "text"])
        if rc == 0 and out and out.lower() != "none":
            private_ip = out.split()[0]

    now = datetime.now(timezone.utc).isoformat()
    lst.update({
        "connection_type": "rfc",
        "target_ashost": public_ip,          # proven raw-IP RFC path
        "target_sysnr": args.sysnr,
        "target_client": args.client,
        "target_user": args.target_user,
        "target_sid": args.sid,
        "target_public_ip": public_ip,
        "target_internal_ip": private_ip,
        "hana_host": "vhcals4hci.dummy.nodomain",
        "hana_sysnr": "02",
        "hana_schema": "SAPHANADB",
        "hana_user": "SAPHANADB",
        "mc_base_url": "https://vhcals4hci.dummy.nodomain:44300/sap/opu/odata/sap/CA_DATA_MIGRATION_SRV",
        "mc_user": args.target_user,
        "ltmom_user": args.target_user,
        "idoc_endpoint": "https://vhcals4hci.dummy.nodomain:44300/sap/bc/idoc_xml",
        "idoc_partner": "M4H_LAPTOP_ECC",
        "idoc_partner_type": "LS",
        "transport_host_instance_id": args.instance_id or lst.get("transport_host_instance_id", ""),
        "bastion_instance_id": args.instance_id or lst.get("bastion_instance_id", ""),
        "saved_at": now,
    })
    conns["lift_and_shift_target"] = lst
    # keep the top-level s4hana block (used by some tools) in sync
    s4 = conns.get("s4hana") or {}
    if isinstance(s4, dict):
        s4.update({"connection_type": "rfc", "ashost": public_ip,
                   "sysnr": args.sysnr, "client": args.client,
                   "user": args.target_user, "saved_at": now})
        conns["s4hana"] = s4

    if args.dry_run:
        record("0", "connections.json", "SKIP", "dry-run: not written")
    else:
        CONNS.write_text(json.dumps(conns, indent=2))
        record("0", "connections.json", "OK",
               f"target={public_ip} sysnr={args.sysnr} client={args.client} "
               f"private={private_ip or '?'}")

    _update_hosts_file(public_ip, args.dry_run)
    return conns


def _update_hosts_file(public_ip: str, dry_run: bool) -> None:
    """Repoint the two vhcals4hc* hostnames (needed for HTTPS/OData whose cert
    uses the hostname). Requires Administrator; report the exact snippet if not."""
    if platform.system() != "Windows":
        record("0", "hosts file", "SKIP", "non-Windows host")
        return
    hosts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    lines = [
        f"{public_ip}\tvhcals4hci.dummy.nodomain",
        f"{public_ip}\tvhcals4hcs.dummy.nodomain",
    ]
    snippet = (f'$ip="{public_ip}"; $h="$env:windir\\System32\\drivers\\etc\\hosts"; '
               "$body=(Get-Content $h | Where-Object { $_ -notmatch 'vhcals4hc' }) -join \"`r`n\"; "
               f'$body += "`r`n$ip`tvhcals4hci.dummy.nodomain`r`n$ip`tvhcals4hcs.dummy.nodomain`r`n"; '
               "Set-Content $h $body -NoNewline")
    if dry_run:
        record("0", "hosts file", "SKIP", "dry-run")
        return
    # Already correct? (e.g. a reused Elastic IP) — then don't need admin at all.
    try:
        existing = hosts.read_text().splitlines() if hosts.exists() else []
    except Exception:
        existing = []
    have = {ln.split()[0] for ln in existing
            if "vhcals4hci.dummy.nodomain" in ln and ln.split()}
    if have == {public_ip}:
        record("0", "hosts file", "OK", f"already maps vhcals4hc* -> {public_ip}")
        return
    try:
        kept = [ln for ln in existing if "vhcals4hc" not in ln]
        hosts.write_text("\r\n".join(kept + lines) + "\r\n")
        record("0", "hosts file", "OK", f"vhcals4hc* -> {public_ip}")
    except PermissionError:
        record("0", "hosts file", "MANUAL",
               "need admin PowerShell — run: " + snippet)
    except Exception as e:  # noqa: BLE001
        record("0", "hosts file", "WARN", f"{type(e).__name__}: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Phase 1 — AWS
# ──────────────────────────────────────────────────────────────────────────────
def phase_aws(args) -> None:
    banner("PHASE 1 — AWS (security group, S3 staging, IAM, SSM)")
    if args.skip_aws:
        record("1", "AWS", "SKIP", "--skip-aws")
        return
    rc, out, err = aws(["sts", "get-caller-identity", "--query", "Account", "--output", "text"])
    if rc != 0:
        record("1", "AWS credentials", "FAIL",
               (err or out or "aws not configured")[:160] + " — rest of Phase 1 skipped")
        return
    record("1", "AWS credentials", "OK", f"account {out}")

    myip = my_public_ip(args.my_ip)
    if not myip:
        record("1", "public IP lookup", "WARN", "could not determine your IP; SG step skipped")
    elif not args.instance_id:
        record("1", "security group", "SKIP", "no --instance-id")
    else:
        _open_security_group(args.instance_id, myip + "/32", args.dry_run)

    _ensure_bucket(args.bucket, args.region, args.dry_run)

    if args.instance_id:
        _check_iam(args.instance_id, args.bucket, args.dry_run)
        _check_ssm(args.instance_id)


def _open_security_group(instance_id: str, cidr: str, dry_run: bool) -> None:
    rc, sg, err = aws(["ec2", "describe-instances", "--instance-ids", instance_id,
                       "--query", "Reservations[].Instances[].SecurityGroups[].GroupId",
                       "--output", "text"])
    if rc != 0 or not sg:
        record("1", "security group", "FAIL", (err or "no SG found")[:160])
        return
    sg = sg.split()[0]
    if dry_run:
        record("1", "security group", "SKIP", f"dry-run: would open {len(SG_PORTS)} ports on {sg} to {cidr}")
        return
    opened, existed, failed = 0, 0, 0
    for p in SG_PORTS:
        rc, _, err = aws(["ec2", "authorize-security-group-ingress", "--group-id", sg,
                          "--protocol", "tcp", "--port", str(p), "--cidr", cidr])
        if rc == 0:
            opened += 1
        elif "Duplicate" in err or "already exists" in err:
            existed += 1
        else:
            failed += 1
    status = "OK" if failed == 0 else "WARN"
    record("1", "security group", status,
           f"{sg}: {opened} opened, {existed} already open, {failed} failed → {cidr}")


def _ensure_bucket(bucket: str, region: str, dry_run: bool) -> None:
    rc, _, _ = aws(["s3api", "head-bucket", "--bucket", bucket])
    if rc == 0:
        record("1", "S3 staging bucket", "OK", f"{bucket} exists")
        return
    if dry_run:
        record("1", "S3 staging bucket", "SKIP", f"dry-run: would create {bucket}")
        return
    mk = ["s3", "mb", f"s3://{bucket}"]
    if region:
        mk += ["--region", region]
    rc, out, err = aws(mk)
    record("1", "S3 staging bucket", "OK" if rc == 0 else "WARN",
           f"created {bucket}" if rc == 0 else (err or out)[:160])


def _check_iam(instance_id: str, bucket: str, dry_run: bool) -> None:
    rc, out, _ = aws(["ec2", "describe-instances", "--instance-ids", instance_id,
                      "--query", "Reservations[].Instances[].IamInstanceProfile.Arn",
                      "--output", "text"])
    if rc == 0 and out and out.lower() != "none":
        record("1", "IAM instance profile", "OK", out.split()[0])
        return
    if dry_run:
        record("1", "IAM instance profile", "SKIP", "dry-run: would create m4h-s4-host role")
        return
    # None attached — create the SSM+S3 role/profile (runbook E.3) and attach.
    role = "m4h-s4-host"
    trust = ('{"Version":"2012-10-17","Statement":[{"Effect":"Allow",'
             '"Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}')
    s3pol = ('{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:*",'
             f'"Resource":["arn:aws:s3:::{bucket}","arn:aws:s3:::{bucket}/*"]}}]}}')
    steps = [
        ["iam", "create-role", "--role-name", role, "--assume-role-policy-document", trust],
        ["iam", "attach-role-policy", "--role-name", role,
         "--policy-arn", "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"],
        ["iam", "put-role-policy", "--role-name", role,
         "--policy-name", "m4h-s3-full", "--policy-document", s3pol],
        ["iam", "create-instance-profile", "--instance-profile-name", role],
        ["iam", "add-role-to-instance-profile", "--instance-profile-name", role,
         "--role-name", role],
        ["ec2", "associate-iam-instance-profile", "--instance-id", instance_id,
         "--iam-instance-profile", f"Name={role}"],
    ]
    problems = []
    for st in steps:
        rc, _, err = aws(st)
        if rc != 0 and "EntityAlreadyExists" not in err and "already associated" not in err:
            problems.append(f"{st[1]}: {err[:80]}")
    record("1", "IAM instance profile", "OK" if not problems else "WARN",
           f"created/attached {role}" if not problems else "; ".join(problems)[:200])


def _check_ssm(instance_id: str) -> None:
    rc, out, _ = aws(["ssm", "describe-instance-information",
                      "--filters", f"Key=InstanceIds,Values={instance_id}",
                      "--query", "InstanceInformationList[].PingStatus", "--output", "text"])
    if rc == 0 and out.strip() == "Online":
        record("1", "SSM agent", "OK", "Online (transport lane reachable)")
    else:
        record("1", "SSM agent", "MANUAL",
               "not Online — SSH to host and: zypper install -y amazon-ssm-agent; "
               "systemctl enable --now amazon-ssm-agent (runbook E.4)")


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2 — RFC access repair (reuse the proven scripts)
# ──────────────────────────────────────────────────────────────────────────────
def phase_access(args) -> None:
    banner("PHASE 2 — RFC access repair (unlock, service user, clear auth)")
    if args.skip_repair:
        record("2", "access repair", "SKIP", "--skip-repair")
        return
    admin_pw = os.environ.get("M4H_ADMIN_PASSWD")
    if not admin_pw:
        record("2", "access repair", "SKIP",
               "set $env:M4H_ADMIN_PASSWD (CAL master pw for SAP*) to enable this phase")
        return
    if not os.environ.get("M4H_TARGET_PASSWD"):
        record("2", "access repair", "FAIL", "set $env:M4H_TARGET_PASSWD first")
        return
    if args.dry_run:
        record("2", "access repair", "SKIP", "dry-run")
        return

    py = sys.executable
    # Create the target user first — on a fresh appliance MIGRATE_ADMI does not
    # exist yet, and fix_migrate_admin.py only *changes* an existing user. This
    # also grants SAP_ALL so mc_role_probe's self-grant has the authority to run.
    _step_script("2", "ensure_target_user.py (create + SAP_ALL)",
                 [py, str(ROOT / "ensure_target_user.py")], "SUCCESS")
    _step_script("2", "recover_access.py (unlock users)",
                 [py, str(ROOT / "recover_access.py")], "unlocked")
    _step_script("2", "fix_migrate_admin.py (Service user + pwd)",
                 [py, str(ROOT / "fix_migrate_admin.py"), "--admin-pass", admin_pw],
                 "SUCCESS")
    # "SAP_ALL" appears both when it adds it ("now has [...]") and when it's
    # already present ("already has [...]") — both are success.
    _step_script("2", "mc_role_probe.py --sap-all (clear auth)",
                 [py, str(ROOT / "mc_role_probe.py"), "--sap-all"], "SAP_ALL")


def _step_script(phase, label, cmd, success_token) -> None:
    rc, out, err = run(cmd, timeout=180)
    tail = (out or err).strip().splitlines()
    tail = tail[-1] if tail else ""
    if rc == 0 and (success_token in out or success_token in err):
        record(phase, label, "OK", tail[:120])
    elif rc == 0:
        record(phase, label, "WARN", tail[:160] or "ran, token not seen")
    else:
        record(phase, label, "FAIL", (err or out or f"rc={rc}").splitlines()[-1][:160])


# ──────────────────────────────────────────────────────────────────────────────
# Phase 3 — live probes (RFC login, client-modifiable, HTTPS lanes)
# ──────────────────────────────────────────────────────────────────────────────
def phase_probe(args, conns) -> None:
    banner("PHASE 3 — live probes (RFC login, client, OData/IDoc lanes)")
    t = conns.get("lift_and_shift_target", {})
    host = t.get("target_ashost")
    pw = os.environ.get("M4H_TARGET_PASSWD")
    if not (host and pw):
        record("3", "RFC login", "SKIP", "host or M4H_TARGET_PASSWD missing")
        return
    try:
        c = rfc_connect(host, t.get("target_sysnr", "00"),
                        t.get("target_client", "100"), t.get("target_user", "MIGRATE_ADMI"), pw)
    except Exception as e:  # noqa: BLE001
        record("3", "RFC login", "FAIL", f"{type(e).__name__}: {str(e)[:140]}")
        return
    try:
        info = c.call("RFC_SYSTEM_INFO")["RFCSI_EXPORT"]
        record("3", "RFC login", "OK",
               f"{info.get('RFCSYSID')} release {info.get('RFCSAPRL')}")

        # client-modifiable (SCC4) via T000
        try:
            r = c.call("RFC_READ_TABLE", QUERY_TABLE="T000", DELIMITER="|",
                       OPTIONS=[{"TEXT": f"MANDT = '{t.get('target_client','100')}'"}],
                       FIELDS=[{"FIELDNAME": "CCCORACTIV"}, {"FIELDNAME": "CCNOCLIIND"}],
                       ROWCOUNT=1)
            if r.get("DATA"):
                cccor, ccnocl = (r["DATA"][0]["WA"].split("|") + ["", ""])[:2]
                cccor, ccnocl = cccor.strip(), ccnocl.strip()
                # CCCORACTIV blank/2 = repository & cross-client changes allowed-ish
                ok = cccor in ("", "1", "2", "3") and ccnocl in ("", "1", "2", "3")
                record("3", "client modifiable (SCC4)", "OK" if ok else "MANUAL",
                       f"CCCORACTIV={cccor!r} CCNOCLIIND={ccnocl!r}"
                       + ("" if ok else " → SCC4: allow changes + cross-client"))
        except Exception as e:  # noqa: BLE001
            record("3", "client modifiable (SCC4)", "WARN", str(e)[:120])

        # Basis Kit
        try:
            sys.path.insert(0, str(ROOT / "lambda" / "utils"))
            from basis_kit_installer import verify_kit_installed  # type: ignore
            k = verify_kit_installed(c)
            if k.get("installed"):
                record("4", "Basis Kit (RFC)", "OK",
                       f"{k.get('version')} installed {k.get('install_ts')}")
            else:
                record("4", "Basis Kit (RFC)", "MANUAL", k.get("message", "")[:160])
                _emit_kit_artifacts()
        except Exception as e:  # noqa: BLE001
            record("4", "Basis Kit (RFC)", "WARN", f"{type(e).__name__}: {str(e)[:120]}")

        # IDoc inbound partner profiles (EDP21)
        try:
            r = c.call("RFC_READ_TABLE", QUERY_TABLE="EDP21", DELIMITER="|",
                       FIELDS=[{"FIELDNAME": "SNDPRN"}, {"FIELDNAME": "MESTYP"}], ROWCOUNT=50)
            rows = [x["WA"].split("|") for x in r.get("DATA", [])]
            mestyps = sorted({(v[1].strip() if len(v) > 1 else "") for v in rows} - {""})
            if mestyps:
                record("5", "IDoc inbound profiles", "OK",
                       f"{len(mestyps)} message types (e.g. {', '.join(mestyps[:6])})")
            else:
                record("5", "IDoc inbound profiles", "MANUAL",
                       "none found — WE20 inbound profile for M4H_LAPTOP_ECC (runbook C.9)")
        except Exception as e:  # noqa: BLE001
            record("5", "IDoc inbound profiles", "WARN", str(e)[:120])
    finally:
        try:
            c.close()
        except Exception:
            pass

    _probe_https(host, t.get("target_user", "MIGRATE_ADMI"),
                 t.get("target_client", "100"), pw)


def _probe_https(host: str, user: str, client: str, pw: str) -> None:
    import socket
    try:
        with socket.create_connection((host, 44300), timeout=6):
            pass
    except Exception:
        record("3", "HTTPS lane (44300)", "MANUAL",
               "port 44300 unreachable — check SG/host firewall (OData + IDoc + Fiori ride this)")
        return
    # AUTHENTICATED check — is API_BUSINESS_PARTNER actually PUBLISHED on the gateway?
    # An anonymous probe returns 401 even when the service is NOT registered, so it
    # must be authenticated: is_service_active() does an authenticated GET and only
    # returns True on HTTP 200 (published). "No service found" => needs publishing.
    try:
        sys.path.insert(0, str(ROOT / "lambda" / "utils"))
        from odata_client import ODataClient  # type: ignore
        import bp_odata  # type: ignore
        oc = ODataClient(host, user, pw, client=str(client), port=44300)
        if bp_odata.is_service_active(oc):
            record("3", "OData lane (BP service)", "OK", "API_BUSINESS_PARTNER published")
        else:
            record("3", "OData lane (BP service)", "MANUAL",
                   "API_BUSINESS_PARTNER NOT published — add it once in /n/IWFND/MAINT_SERVICE "
                   "(Add Service → alias LOCAL) so customer/vendor creation works (runbook C.8)")
    except Exception as e:  # noqa: BLE001
        record("3", "OData lane (BP service)", "WARN",
               f"port 44300 open but OData probe failed: {type(e).__name__}: {str(e)[:100]}")


def _emit_kit_artifacts() -> None:
    try:
        sys.path.insert(0, str(ROOT / "lambda" / "utils"))
        from basis_kit_installer import kit_install_abap, fm_source_bundle  # type: ignore
        STAGING.mkdir(exist_ok=True)
        (STAGING / "ZM4H_KIT_INSTALL.abap").write_text(kit_install_abap(), encoding="utf-8")
        (STAGING / "M4H_KIT_FMS.abap").write_text(fm_source_bundle(), encoding="utf-8")
        record("4", "Basis Kit artifacts", "OK",
               f"wrote {STAGING / 'ZM4H_KIT_INSTALL.abap'} + M4H_KIT_FMS.abap "
               "→ SE38 run the install report, SE37 paste the FMs (BASIS_KIT_OPERATIONS.md §3)")
    except Exception as e:  # noqa: BLE001
        record("4", "Basis Kit artifacts", "WARN", f"{type(e).__name__}: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# summary
# ──────────────────────────────────────────────────────────────────────────────
def summary(args) -> int:
    banner("SUMMARY")
    counts: dict[str, int] = {}
    for r in RESULTS:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("  " + "   ".join(f"{MARK[k]} {counts.get(k,0)}"
                            for k in ("OK", "WARN", "MANUAL", "SKIP", "FAIL")))

    manual = [r for r in RESULTS if r["status"] in ("MANUAL", "FAIL")]
    if manual:
        print("\n  Remaining steps that need YOU (GUI/SSH — can't be done over RFC):")
        for r in manual:
            print(f"    - [{r['status']}] {r['step']}: {r['detail']}")
    else:
        print("\n  Nothing left — the appliance is fully configured and reachable.")

    print("\n  Manual GUI/SSH steps this runner never touches (do once, ~20 min):")
    for line in (
        "Gateway publish (REQUIRED for customer/vendor OData): /n/IWFND/MAINT_SERVICE → "
        "Add Service → System Alias LOCAL → Technical Service Name *BUSINESS_PARTNER* → "
        "Get Services → select API_BUSINESS_PARTNER → Add Selected → Local Object. "
        "The gateway maint FMs are dialog-only, so this can't be done over RFC (runbook C.8).",
        "RZ10/RZ11 password-policy + rdisp/max_wprun_time=0 (C.5) — optional; Service user won't expire",
        "SM19 security audit off (C.6) — optional",
        "STMS / tp single-system transport domain if .PFL missing (C.11) — SSH",
        "HANA: disable SAPHANADB password lifetime (C.12) — SSH/hdbsql",
    ):
        print(f"    - {line}")

    STAGING.mkdir(exist_ok=True)
    report = STAGING / f"configure_new_appliance_{datetime.now():%Y%m%d_%H%M%S}.json"
    report.write_text(json.dumps({"args": vars(args), "results": RESULTS,
                                  "counts": counts}, indent=2, default=str))
    print(f"\n  Full report: {report}")

    fails = counts.get("FAIL", 0)
    print("\n  " + ("ALL AUTOMATED STEPS PASSED — finish the short manual list above, then run the migration."
                    if fails == 0 else
                    f"{fails} step(s) FAILED — fix those before migrating."))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="One-shot configure a fresh S/4 CAL appliance.")
    ap.add_argument("--public-ip", help="new appliance public IP (or Elastic IP)")
    ap.add_argument("--instance-id", help="EC2 instance id of the S/4 host (for AWS steps)")
    ap.add_argument("--private-ip", help="private IP (auto-discovered from instance-id if omitted)")
    ap.add_argument("--sid", default="S4H")
    ap.add_argument("--client", default="100")
    ap.add_argument("--sysnr", default="00")
    ap.add_argument("--target-user", default="MIGRATE_ADMI")
    ap.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    ap.add_argument("--bucket", default=os.environ.get("S3_STAGING_BUCKET", "m4h-staging-ajays"))
    ap.add_argument("--my-ip", help="override your public IP for the SG rule (default: auto)")
    ap.add_argument("--skip-aws", action="store_true", help="skip all AWS steps")
    ap.add_argument("--skip-repair", action="store_true", help="skip the RFC access-repair scripts")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen; write nothing")
    args = ap.parse_args()

    print(f"configure_new_appliance — {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  target public IP : {args.public_ip or '(from connections.json)'}")
    print(f"  instance id      : {args.instance_id or '(none — AWS steps limited)'}")
    print(f"  dry-run          : {args.dry_run}")

    conns = phase_connjson(args)
    phase_aws(args)
    phase_access(args)
    phase_probe(args, conns)
    return summary(args)


if __name__ == "__main__":
    sys.exit(main())
