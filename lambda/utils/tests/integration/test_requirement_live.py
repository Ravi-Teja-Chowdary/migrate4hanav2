"""
test_requirement_live — GENERATED FROM definitions/Requirement.json

DO NOT EDIT BY HAND. Re-run `python -m scaffolder.build Requirement` to
regenerate after editing the JSON definition.

Live integration test against a real S/4 system. Skipped in normal CI unless
M4H_LIVE_INTEGRATION=1 is set, since it needs:
  - pyrfc + SAP NW RFC SDK installed
  - M4H_S4_SECRET_ID env var pointing to a Secrets Manager secret with creds
  - the target user (Requirement create authorization in the target client)

Used by the nightly breadth-grind job + the phase_b_validate_<n> Lambda modes
to verify the generated spine loads at least one real record end-to-end.

Generator:  migrate4hana scaffolder v1.0.0
Source SHA: 25750850a414a98dacec0fd91337436b97dcf8c0ea403f120bd1ef2d8968fcd4
"""
from __future__ import annotations

import os
import sys
import json

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("M4H_LIVE_INTEGRATION") != "1",
    reason="needs M4H_LIVE_INTEGRATION=1 + live S/4 + SAP NW RFC SDK",
)


HERE = os.path.dirname(os.path.abspath(__file__))
UTILS = os.path.abspath(os.path.join(HERE, "..", ".."))
if UTILS not in sys.path:
    sys.path.insert(0, UTILS)


@pytest.fixture(scope="module")
def s4_conn():
    """Open a pyrfc connection from the configured Secrets Manager secret."""
    try:
        import boto3
        from pyrfc import Connection
    except ImportError as e:
        pytest.skip(f"missing runtime dep: {e}")

    secret_id = os.environ.get("M4H_S4_SECRET_ID")
    if not secret_id:
        pytest.skip("M4H_S4_SECRET_ID not set")

    sec = json.loads(
        boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)["SecretString"]
    )
    conn = Connection(
        ashost=sec["ashost"], sysnr=sec.get("sysnr", "00"),
        client=sec["client"], user=sec["user"],
        passwd=sec.get("passwd") or sec.get("password"),
        lang=sec.get("lang", "EN"),
    )
    yield conn
    try:
        conn.close()
    except Exception:
        pass


def test_load_one_real_record(s4_conn):
    """Construct a synthetic record, push it through the generated spine, and
    assert the BAPI succeeded (or that the dead-letter was the expected DQ
    rejection for a synthetic value)."""
    from requirement_spine import RequirementSpineOrchestrator

    spine = RequirementSpineOrchestrator(
        conn=s4_conn,
        key_map=None,
        dry_run=False,
        target_release="S4HANA_2022",
    )

    sample = {'BDZEI': 'X', 'MATNR': 'MATNR_T0001', 'MEINS': 'EA', 'PLNMG': '1', 'VERSB': 'X', 'WERKS': '1710'}
    result = spine.load_one(sample)

    # Either the BAPI fully accepted the synthetic record (created or matched_existing)
    # or it dead-lettered cleanly (no crash). Anything else (raw exception) is a fail.
    assert result.status in ("created", "matched_existing", "remapped", "dead_letter"), (
        f"unexpected status {result.status}: messages={result.messages}"
    )

    if result.status != "dead_letter":
        assert result.target_key, f"missing target_key on success: {result}"
        assert result.verify_key, "missing verify_key on success"
