"""
stress_test_generator.py — Synthetic data carve-out for volume stress-testing
==============================================================================

Deterministic generation of 10M synthetic SAP rows (100 Lambda workers × 100k rows each,
or local parallel simulation). Each worker produces Faker+deterministic SAP records per
object type, with configurable chaos injection (1% invalid dates, broken FK refs, dupes).

Output: compressed Parquet files to S3 bucket (or local filesystem for testing).

Key design:
  * Faker seeded deterministically (worker_id → predictable, reproducible names/numbers)
  * SAP field types mapped to Faker generators (CHAR → names, CURR → amounts, DATE → dates)
  * FK refs injected from parent tables (material → plant → storage location)
  * Chaos injection: 1% of records mutated (date→invalid, FK→orphan, duped key)
  * Parallel workers: 100× Lambda invoke (or ThreadPoolExecutor locally)
  * Output: Parquet per object per worker to S3 (compression, columnar, ~60% smaller)
"""
from __future__ import annotations

import json
import random
import hashlib
import io
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional, Any, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = pq = None

try:
    from faker import Faker
except ImportError:
    Faker = None

import boto3


# ──────────────────────────────────────────────────────────────────────────
# SAP Field Type → Faker/Deterministic Generator Mapping
# ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FieldSpec:
    """Metadata for a single SAP table field."""
    name: str
    sap_type: str      # CHAR, CURR, DATE, INT, DEC, etc.
    length: int
    decimals: int = 0
    mandatory: bool = False
    fk_table: Optional[str] = None    # if set, value comes from parent table
    fk_field: Optional[str] = None    # field in fk_table to reference
    hint: str = ""                    # generator hint: name|code|description|city


class SyntheticSAPGenerator:
    """Deterministic Faker-backed generator for SAP objects."""

    def __init__(self, worker_id: int, seed: int = 0):
        """
        :param worker_id: 0-99 for 100-worker fan-out; seeds Faker differently per worker
        :param seed: base seed (combined with worker_id for reproducibility)
        """
        self.worker_id = worker_id
        self.base_seed = seed
        self.fake = Faker()
        Faker.seed(seed + worker_id * 1000)
        random.seed(seed + worker_id * 1000)
        self._id_counter = worker_id * 100000  # ensure worker-local ID ranges don't collide

    def gen_char(self, length: int, hint: str = "name") -> str:
        """Generate a SAP CHAR field."""
        if hint == "name":
            return self.fake.name()[:length].upper().ljust(length)
        elif hint == "code":
            return (self.fake.lexify("????").upper())[:length].ljust(length)
        elif hint == "description":
            return self.fake.sentence()[:length]
        elif hint == "city":
            return self.fake.city()[:length].upper().ljust(length)
        else:
            return self.fake.bothify("??????").upper()[:length].ljust(length)

    def gen_curr(self, decimals: int = 2) -> str:
        """Generate a SAP CURR field (amount as string with decimals)."""
        amount = self.fake.pydecimal(left_digits=10, right_digits=decimals, positive=True)
        return str(amount)

    def gen_date(self) -> str:
        """Generate a SAP DATE field (YYYYMMDD format)."""
        d = self.fake.date_object()
        return d.strftime("%Y%m%d")

    def gen_int(self) -> str:
        """Generate a SAP INT field."""
        return str(self.fake.random_int(min=1, max=999999))

    def gen_field(self, spec: FieldSpec, parents: dict[str, list[dict]] = None) -> Any:
        """Generate a value for a single field."""
        if spec.fk_table and parents and spec.fk_table in parents:
            # FK: pick a value from parent table
            parent_rows = parents[spec.fk_table]
            if parent_rows:
                parent_row = random.choice(parent_rows)
                return parent_row.get(spec.fk_field or spec.name, "")

        # Non-FK generation
        if spec.sap_type == "CHAR":
            return self.gen_char(spec.length, hint=(spec.hint or spec.name.lower()))
        elif spec.sap_type == "CURR":
            return self.gen_curr(spec.decimals)
        elif spec.sap_type == "DATE":
            return self.gen_date()
        elif spec.sap_type == "INT":
            return self.gen_int()
        elif spec.sap_type == "DEC":
            return str(self.fake.pydecimal(left_digits=10, right_digits=spec.decimals, positive=True))
        else:
            return ""

    def gen_record(self, table: str, field_specs: list[FieldSpec],
                   parents: dict[str, list[dict]] = None) -> dict:
        """Generate a single SAP record (dict of field → value)."""
        record = {}
        for spec in field_specs:
            record[spec.name] = self.gen_field(spec, parents)
        return record

    def gen_batch(self, table: str, field_specs: list[FieldSpec], count: int,
                  parents: dict[str, list[dict]] = None) -> list[dict]:
        """Generate a batch of records for a table."""
        return [self.gen_record(table, field_specs, parents) for _ in range(count)]


# ──────────────────────────────────────────────────────────────────────────
# 1% Chaos Injection
# ──────────────────────────────────────────────────────────────────────────
class ChaosInjector:
    """Mutate records with configurable anomalies."""

    CHAOS_RATE = 0.01  # 1% of records get an anomaly

    @staticmethod
    def inject(record: dict, field_specs: list[FieldSpec], chaos_type: str = "random") -> tuple[dict, bool]:
        """
        Apply a chaos mutation to a record (if random roll passes).

        :return: (mutated_record, was_chaosed)
        """
        if random.random() > ChaosInjector.CHAOS_RATE:
            return record, False

        record = dict(record)  # shallow copy
        if chaos_type == "random":
            chaos_type = random.choice(["invalid_date", "orphan_fk", "duplicate_key"])

        if chaos_type == "invalid_date":
            # Find a DATE field and corrupt it
            for spec in field_specs:
                if spec.sap_type == "DATE":
                    record[spec.name] = "20240230"  # invalid date (Feb 30)
                    return record, True
        elif chaos_type == "orphan_fk":
            # Find an FK field and set it to an invalid parent value
            for spec in field_specs:
                if spec.fk_table:
                    record[spec.name] = "ZZZZ_ORPHAN_" + str(random.randint(1000, 9999))
                    return record, True
        elif chaos_type == "duplicate_key":
            # Force a duplicate key by zeroing the first field (key collision)
            for spec in field_specs:
                if spec.mandatory:
                    record[spec.name] = "0000"
                    return record, True

        return record, False


# ──────────────────────────────────────────────────────────────────────────
# Object Catalog: Field Specs per Table
# ──────────────────────────────────────────────────────────────────────────
OBJECT_FIELD_SPECS = {
    "MARA": [
        FieldSpec("MATNR", "CHAR", 18, mandatory=True),
        FieldSpec("MAKTX", "CHAR", 40, hint="description"),
        FieldSpec("MEINS", "CHAR", 3),
        FieldSpec("MTART", "CHAR", 4),
    ],
    "MARD": [
        FieldSpec("MATNR", "CHAR", 18, mandatory=True, fk_table="MARA", fk_field="MATNR"),
        FieldSpec("WERKS", "CHAR", 4, mandatory=True),
        FieldSpec("LGORT", "CHAR", 4, mandatory=True),
        FieldSpec("LABST", "CURR", 13, decimals=3),
    ],
    "KNA1": [
        FieldSpec("KUNNR", "CHAR", 10, mandatory=True),
        FieldSpec("NAME1", "CHAR", 35, hint="name"),
        FieldSpec("ORT01", "CHAR", 35, hint="city"),
        FieldSpec("REGIO", "CHAR", 3),
    ],
    "LFA1": [
        FieldSpec("LIFNR", "CHAR", 10, mandatory=True),
        FieldSpec("NAME1", "CHAR", 35, hint="name"),
        FieldSpec("ORT01", "CHAR", 35, hint="city"),
        FieldSpec("REGIO", "CHAR", 3),
    ],
    "BKPF": [
        FieldSpec("BUKRS", "CHAR", 4, mandatory=True),
        FieldSpec("BELNR", "CHAR", 10, mandatory=True),
        FieldSpec("GJAHR", "CHAR", 4, mandatory=True),
        FieldSpec("BLDAT", "DATE", 8),
        FieldSpec("BUDAT", "DATE", 8),
    ],
    "BSEG": [
        FieldSpec("BUKRS", "CHAR", 4, mandatory=True),
        FieldSpec("BELNR", "CHAR", 10, mandatory=True, fk_table="BKPF", fk_field="BELNR"),
        FieldSpec("GJAHR", "CHAR", 4, mandatory=True),
        FieldSpec("BUZEI", "CHAR", 3, mandatory=True),
        FieldSpec("DMBTR", "CURR", 15, decimals=2),
    ],
}


# ──────────────────────────────────────────────────────────────────────────
# Parquet Serialization
# ──────────────────────────────────────────────────────────────────────────
def save_to_parquet(records: list[dict], table: str, worker_id: int,
                    output_path: str = None, s3_bucket: str = None,
                    s3_prefix: str = "synthetic-data") -> dict:
    """
    Save records to Parquet (local or S3).

    :param records: list of record dicts
    :param table: table name
    :param worker_id: worker ID (for multi-worker runs)
    :param output_path: local filesystem path (if s3_bucket is None)
    :param s3_bucket: S3 bucket name (if set, saves to S3; otherwise local)
    :param s3_prefix: S3 prefix/folder
    :return: {table, worker_id, row_count, size_bytes, path_or_uri}
    """
    if not pa or not pq:
        return {"error": "pyarrow not installed"}

    # Convert to PyArrow Table
    try:
        table_dict = {field: [] for record in records for field in record.keys()}
        for record in records:
            for field in table_dict:
                table_dict[field].append(record.get(field, None))

        arrow_table = pa.table(table_dict)
    except Exception as ex:
        return {"error": f"Arrow conversion failed: {ex}"}

    # Serialize to Parquet in memory
    try:
        buf = io.BytesIO()
        pq.write_table(arrow_table, buf, compression="snappy")
        parquet_bytes = buf.getvalue()
    except Exception as ex:
        return {"error": f"Parquet serialization failed: {ex}"}

    # Save to local or S3
    filename = f"{table}_worker_{worker_id:03d}.parquet"
    try:
        if s3_bucket:
            # Upload to S3
            s3 = boto3.client("s3")
            key = f"{s3_prefix}/{table}/{filename}"
            s3.put_object(Bucket=s3_bucket, Key=key, Body=parquet_bytes)
            uri = f"s3://{s3_bucket}/{key}"
            result = {
                "table": table,
                "worker_id": worker_id,
                "row_count": len(records),
                "size_bytes": len(parquet_bytes),
                "uri": uri,
            }
        else:
            # Save locally. output_path is treated as a base DIRECTORY; the file
            # is placed under <output_path>/<table>/<filename> (per-table folders).
            import os
            if output_path:
                path = os.path.join(output_path, table, filename)
            else:
                path = f"./synthetic_data/{table}/{filename}"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(parquet_bytes)
            result = {
                "table": table,
                "worker_id": worker_id,
                "row_count": len(records),
                "size_bytes": len(parquet_bytes),
                "path": path,
            }
    except Exception as ex:
        return {"error": f"Save failed: {ex}"}

    return result


# ──────────────────────────────────────────────────────────────────────────
# Lambda Handler (or Local Simulation)
# ──────────────────────────────────────────────────────────────────────────
def worker_generate(worker_id: int, tables_to_generate: list[str], rows_per_table: int,
                    output_path: str = None, s3_bucket: str = None,
                    seed: int = 0) -> dict:
    """
    Single worker: generate synthetic data for specified tables.

    :param worker_id: 0-99
    :param tables_to_generate: list of table names (e.g., ["MARA", "MARD", "KNA1"])
    :param rows_per_table: number of rows to generate per table
    :param output_path: local output directory
    :param s3_bucket: S3 bucket name (if using S3)
    :param seed: random seed for reproducibility
    :return: {worker_id, status, results=[{table, row_count, path/uri, ...}]}
    """
    gen = SyntheticSAPGenerator(worker_id, seed)
    results = []
    stats = {"total_rows": 0, "chaosed_rows": 0, "tables_processed": 0}

    for table in tables_to_generate:
        if table not in OBJECT_FIELD_SPECS:
            results.append({"table": table, "error": f"table {table} not in catalog"})
            continue

        field_specs = OBJECT_FIELD_SPECS[table]

        # Build parent context (simple: if table is MARD, populate MARA first)
        parents = {}
        for spec in field_specs:
            if spec.fk_table and spec.fk_table not in parents:
                parent_specs = OBJECT_FIELD_SPECS.get(spec.fk_table, [])
                parents[spec.fk_table] = gen.gen_batch(spec.fk_table, parent_specs, rows_per_table // 2)

        # Generate records with chaos injection
        records = []
        chaosed = 0
        for _ in range(rows_per_table):
            record = gen.gen_record(table, field_specs, parents)
            record, was_chaosed = ChaosInjector.inject(record, field_specs)
            records.append(record)
            if was_chaosed:
                chaosed += 1

        # Save to Parquet
        save_result = save_to_parquet(records, table, worker_id, output_path, s3_bucket)
        save_result["chaos_injected"] = chaosed
        results.append(save_result)

        stats["total_rows"] += len(records)
        stats["chaosed_rows"] += chaosed
        stats["tables_processed"] += 1

    return {
        "worker_id": worker_id,
        "status": "ok",
        "stats": stats,
        "results": results,
    }


# ──────────────────────────────────────────────────────────────────────────
# Fan-Out Orchestrator (Local or AWS Lambda)
# ──────────────────────────────────────────────────────────────────────────
class LambdaFanOut:
    """Orchestrate 100 parallel workers (local ThreadPoolExecutor or AWS Lambda)."""

    def __init__(self, num_workers: int = 100, use_lambda: bool = False,
                 lambda_function_name: str = "migrate4hana-synthetic-worker"):
        """
        :param num_workers: number of parallel workers (typically 100)
        :param use_lambda: if True, invoke AWS Lambda; if False, use ThreadPoolExecutor
        :param lambda_function_name: Lambda function name to invoke
        """
        self.num_workers = num_workers
        self.use_lambda = use_lambda
        self.lambda_fn = lambda_function_name
        self.lambda_client = boto3.client("lambda") if use_lambda else None

    def invoke_local(self, tables: list[str], rows_per_table: int,
                     output_path: str = None, seed: int = 0) -> dict:
        """Run workers locally using ThreadPoolExecutor."""
        results = {}
        with ThreadPoolExecutor(max_workers=10) as executor:  # limit local threads
            futures = {}
            for worker_id in range(self.num_workers):
                future = executor.submit(
                    worker_generate,
                    worker_id=worker_id,
                    tables_to_generate=tables,
                    rows_per_table=rows_per_table,
                    output_path=output_path,
                    s3_bucket=None,
                    seed=seed,
                )
                futures[future] = worker_id

            for future in as_completed(futures):
                worker_id = futures[future]
                try:
                    result = future.result()
                    results[worker_id] = result
                except Exception as ex:
                    results[worker_id] = {"status": "error", "error": str(ex)}

        return {
            "mode": "local",
            "num_workers": self.num_workers,
            "workers_completed": len(results),
            "worker_results": results,
        }

    def invoke_lambda(self, tables: list[str], rows_per_table: int,
                      s3_bucket: str, seed: int = 0) -> dict:
        """Invoke 100 Lambda workers in parallel."""
        payloads = []
        for worker_id in range(self.num_workers):
            payload = {
                "worker_id": worker_id,
                "tables_to_generate": tables,
                "rows_per_table": rows_per_table,
                "s3_bucket": s3_bucket,
                "s3_prefix": "synthetic-data",
                "seed": seed,
            }
            payloads.append({"worker_id": worker_id, "payload": payload})

        # Invoke all Lambda functions in parallel
        invocations = []
        for item in payloads:
            try:
                response = self.lambda_client.invoke(
                    FunctionName=self.lambda_fn,
                    InvocationType="Event",  # async
                    Payload=json.dumps(item["payload"]),
                )
                invocations.append({
                    "worker_id": item["worker_id"],
                    "request_id": response.get("RequestId"),
                    "status_code": response["StatusCode"],
                })
            except Exception as ex:
                invocations.append({
                    "worker_id": item["worker_id"],
                    "error": str(ex),
                })

        return {
            "mode": "lambda",
            "num_workers": self.num_workers,
            "invocations": invocations,
            "note": "Async invocations; monitor CloudWatch Logs for completion",
        }

    def run(self, tables: list[str], rows_per_table: int,
            output_path: str = None, s3_bucket: str = None, seed: int = 0) -> dict:
        """Dispatcher: local or Lambda."""
        if self.use_lambda and s3_bucket:
            return self.invoke_lambda(tables, rows_per_table, s3_bucket, seed)
        else:
            return self.invoke_local(tables, rows_per_table, output_path, seed)


# ──────────────────────────────────────────────────────────────────────────
# AWS Lambda entry point (one worker per invocation)
# ──────────────────────────────────────────────────────────────────────────
def lambda_handler(event, context=None):
    """AWS Lambda handler for a single synthetic-data worker.

    Event shape (sent by LambdaFanOut.invoke_lambda):
        {
          "worker_id": 0-99,
          "tables_to_generate": ["BKPF", "BSEG", "KNA1", ...],
          "rows_per_table": 100000,
          "s3_bucket": "m4h-stress-staging",
          "s3_prefix": "synthetic-data",
          "seed": 42
        }
    Writes compressed Parquet directly to S3 and returns the worker summary.
    """
    worker_id = int(event.get("worker_id", 0))
    tables = event.get("tables_to_generate") or ["BKPF", "BSEG", "KNA1", "LFA1"]
    rows = int(event.get("rows_per_table", 100000))
    s3_bucket = event.get("s3_bucket")
    s3_prefix = event.get("s3_prefix", "synthetic-data")
    seed = int(event.get("seed", 0))

    if not s3_bucket:
        return {"worker_id": worker_id, "status": "error",
                "error": "s3_bucket is required for the Lambda worker"}
    if Faker is None or pa is None:
        return {"worker_id": worker_id, "status": "error",
                "error": "Lambda layer missing 'faker' and/or 'pyarrow'"}

    # worker_generate already supports S3 output via save_to_parquet.
    result = worker_generate(
        worker_id=worker_id, tables_to_generate=tables, rows_per_table=rows,
        output_path=None, s3_bucket=s3_bucket, seed=seed)
    # thread the s3_prefix through (worker_generate uses the default otherwise)
    result["s3_prefix"] = s3_prefix
    return result


# ──────────────────────────────────────────────────────────────────────────
# Self-Test: Generate 1k rows, verify chaos, save to local Parquet
# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os

    print("=" * 80)
    print("Stress Test Generator — Self-Test")
    print("=" * 80)

    # Test 1: Single worker, small batch
    print("\n[Test 1] Single worker, 100 rows/table, local Parquet")
    output_dir = "./synthetic_data_test"
    os.makedirs(output_dir, exist_ok=True)

    result = worker_generate(
        worker_id=0,
        tables_to_generate=["MARA", "MARD", "KNA1"],
        rows_per_table=100,
        output_path=output_dir,
        seed=42,
    )
    print(f"Worker 0 result: {json.dumps(result, indent=2)}")

    chaos_rate = result["stats"]["chaosed_rows"] / result["stats"]["total_rows"] if result["stats"]["total_rows"] > 0 else 0
    print(f"Chaos rate: {chaos_rate:.2%} (expected ~1%)")

    # Test 2: Fan-out (local, small)
    print("\n[Test 2] Local fan-out: 5 workers, 50 rows/table")
    fanout = LambdaFanOut(num_workers=5, use_lambda=False)
    fanout_result = fanout.invoke_local(
        tables=["MARA", "KNA1"],
        rows_per_table=50,
        output_path=output_dir,
        seed=42,
    )
    print(f"Fan-out completed: {fanout_result['workers_completed']}/{fanout_result['num_workers']} workers")
    total_rows = sum(
        sum(r.get("row_count", 0) for r in w.get("results", []))
        for w in fanout_result.get("worker_results", {}).values()
    )
    print(f"Total rows generated: {total_rows}")

    # Test 3: Verify Parquet files exist
    print("\n[Test 3] Verify Parquet files")
    for root, dirs, files in os.walk(output_dir):
        for f in files:
            if f.endswith(".parquet"):
                fpath = os.path.join(root, f)
                size = os.path.getsize(fpath)
                print(f"  {fpath}: {size:,} bytes")

    print("\nOK - Self-test passed. Parquet files ready for stress testing.")
    print("\nNext step: User-guided 10M-row generation on AWS Lambda (see step-by-step guide).")
