"""
F1 Phase B integration test - PersistentKeyMap against REAL DynamoDB.

Unlike test_persistent_key_map.py (which uses an in-process mock), this hits the
actual migrate4hana-key-map-prod table to prove:

  1. The class can talk to real AWS (credentials, region, table name)
  2. Conditional writes work end-to-end (idempotency)
  3. The schema we write matches the schema the table expects (hash=object, range=source_key)
  4. resolve() can find what we just wrote
  5. The full item payload (run_id, written_at, target_release) is round-trip clean

Cleans up after itself. Safe to run repeatedly.

Run:
    python tests/integration_test_persistent_key_map.py
"""
from __future__ import annotations
import os
import sys
import uuid
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "utils"))

# Real AWS
import boto3   # type: ignore
from key_map import PersistentKeyMap   # type: ignore


REGION     = os.environ.get("AWS_REGION", "us-east-1")
TABLE_NAME = os.environ.get("M4H_KEYMAP_TABLE", "migrate4hana-key-map-prod")
RUN_ID     = f"phase-b-test-{int(time.time())}-{uuid.uuid4().hex[:6]}"

# Use a distinct object name so we never collide with real production keys
TEST_OBJECT = "_F1PhaseBTest"


def main() -> None:
    print("=" * 70)
    print("F1 Phase B - PersistentKeyMap vs real DynamoDB")
    print("=" * 70)
    print(f"  table:   {TABLE_NAME}")
    print(f"  region:  {REGION}")
    print(f"  run_id:  {RUN_ID}")
    print(f"  object:  {TEST_OBJECT} (test-scoped, won't collide)")
    print()

    ddb = boto3.client("dynamodb", region_name=REGION)
    pk = PersistentKeyMap(
        table_name=TABLE_NAME,
        dynamodb_client=ddb,
        run_id=RUN_ID,
        target_release="S4HANA-2023",
    )

    # ── 1. Write a few mappings ─────────────────────────────────────────────────
    print("[1/5] Writing 3 mappings via PersistentKeyMap.add()")
    pk.add(TEST_OBJECT, "SRC_001", "TGT_AAA", "created")
    pk.add(TEST_OBJECT, "SRC_002", "TGT_BBB", "matched_existing")
    pk.add(TEST_OBJECT, "SRC_003", "TGT_CCC", "remapped")
    print(f"      writes: {pk.persistence_stats()['writes']}/3")
    assert pk.persistence_stats()["writes"] == 3, "not all 3 writes landed"

    # ── 2. Read them back via resolve() (hits in-memory cache first) ────────────
    print("[2/5] Reading mappings back via PersistentKeyMap.resolve()")
    assert pk.resolve(TEST_OBJECT, "SRC_001") == "TGT_AAA"
    assert pk.resolve(TEST_OBJECT, "SRC_002") == "TGT_BBB"
    assert pk.resolve(TEST_OBJECT, "SRC_003") == "TGT_CCC"
    print("      in-memory cache resolves: OK (3/3)")

    # ── 3. Verify DDB really has them with the right item payload ───────────────
    print("[3/5] Reading raw items from DynamoDB to verify schema")
    for src in ["SRC_001", "SRC_002", "SRC_003"]:
        resp = ddb.get_item(
            TableName=TABLE_NAME,
            Key={"object": {"S": TEST_OBJECT}, "source_key": {"S": src}},
            ConsistentRead=True,
        )
        item = resp.get("Item")
        assert item is not None, f"item for {src} not found in DDB"
        assert item["object"]["S"] == TEST_OBJECT
        assert item["source_key"]["S"] == src
        assert item["target_key"]["S"].startswith("TGT_")
        assert item["disposition"]["S"] in ("created", "matched_existing", "remapped")
        assert item["run_id"]["S"] == RUN_ID
        assert item["target_release"]["S"] == "S4HANA-2023"
        assert item["written_at"]["S"].endswith("Z")   # ISO-8601 UTC
        print(f"      {src}: target={item['target_key']['S']}, "
              f"disp={item['disposition']['S']}, written_at={item['written_at']['S']}")

    # ── 4. Idempotency - re-adding the same key should NOT overwrite ────────────
    print("[4/5] Idempotency check - re-add same source_key with different target")
    pk2 = PersistentKeyMap(table_name=TABLE_NAME, dynamodb_client=ddb,
                           run_id=RUN_ID + "-second")
    pk2.add(TEST_OBJECT, "SRC_001", "TGT_SHOULD_NOT_WIN", "created")
    # original value should still be in DDB (first-writer-wins)
    resp = ddb.get_item(
        TableName=TABLE_NAME,
        Key={"object": {"S": TEST_OBJECT}, "source_key": {"S": "SRC_001"}},
        ConsistentRead=True,
    )
    assert resp["Item"]["target_key"]["S"] == "TGT_AAA", \
        "first-writer-wins violated - ConditionExpression broken"
    cs = pk2.persistence_stats()["conditional_skips"]
    print(f"      first-writer-wins preserved (conditional_skips: {cs})")

    # ── 5. Cold-cache resolve - DDB GetItem on miss ─────────────────────────────
    print("[5/5] Cold-cache resolve fall-through to DDB")
    pk_cold = PersistentKeyMap(table_name=TABLE_NAME, dynamodb_client=ddb)
    # in-memory cache is empty - this MUST hit DDB
    result = pk_cold.resolve(TEST_OBJECT, "SRC_002")
    assert result == "TGT_BBB", f"expected TGT_BBB, got {result}"
    assert pk_cold.persistence_stats()["ddb_gets"] == 1, "DDB get not counted"
    assert pk_cold.persistence_stats()["ddb_hits"] == 1, "DDB hit not counted"
    print(f"      cold resolve: TGT_BBB found via DDB GetItem")

    # ── Cleanup ─────────────────────────────────────────────────────────────────
    print("\n[cleanup] Removing test items from DDB")
    for src in ["SRC_001", "SRC_002", "SRC_003"]:
        ddb.delete_item(
            TableName=TABLE_NAME,
            Key={"object": {"S": TEST_OBJECT}, "source_key": {"S": src}},
        )
    print("           done")

    print("\n" + "=" * 70)
    print("F1 PHASE B: PASS")
    print("=" * 70)
    print("PersistentKeyMap works end-to-end against real DynamoDB.")
    print("Conditional writes preserve first-writer-wins. Schema round-trips.")
    print("Cold-cache resolve falls through to DDB and hydrates correctly.")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)
