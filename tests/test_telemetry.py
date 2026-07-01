"""Unit tests for lambda/utils/telemetry.py.

Every test writes a temporary run directory with hand-crafted artefacts, calls
the aggregation function, and asserts against the JSON shape the frontend
expects. No FastAPI, no network, no real SAP.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lambda" / "utils"))
from telemetry import (  # noqa: E402
    aggregate_run_telemetry,
    bucket_errors,
    failed_records_csv,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture helpers
# ─────────────────────────────────────────────────────────────────────────────
def _write_summary(run_dir: Path, **kwargs) -> None:
    p = run_dir / "data-migrator" / "summary.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(kwargs), encoding="utf-8")


def _write_dead_letter(run_dir: Path, records) -> None:
    p = run_dir / "data-migrator" / "dead-letter" / "failed_records.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(records), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# aggregate_run_telemetry
# ─────────────────────────────────────────────────────────────────────────────
class TestAggregateTelemetry:
    def test_idle_when_no_artefacts_and_no_active_state(self, tmp_path):
        out = aggregate_run_telemetry(tmp_path)
        assert out == {
            "status": "Idle",
            "percentage_complete": 0.0,
            "total_records": 0,
            "processed_successfully": 0,
            "failed_records": 0,
            "runtime_elapsed_seconds": 0,
        }

    def test_shape_is_frozen(self, tmp_path):
        """The frontend depends on these six keys and nothing else. If someone
        adds a field, this test forces a UI update to accompany it."""
        out = aggregate_run_telemetry(tmp_path)
        assert set(out.keys()) == {
            "status",
            "percentage_complete",
            "total_records",
            "processed_successfully",
            "failed_records",
            "runtime_elapsed_seconds",
        }

    def test_extract_only_run_counts_all_staged_rows(self, tmp_path):
        _write_summary(
            tmp_path,
            load_to_s4_enabled=False,
            results=[
                {"object": "Customer", "row_count": 100, "status": "ok"},
                {"object": "Vendor",   "row_count":  50, "status": "ok"},
                {"object": "Material", "row_count":  10, "status": "partial"},
                {"object": "Skipped",  "row_count":   0, "status": "skipped"},
            ],
            data_quality={"total_attempted": 0, "total_dead_letter": 0},
        )
        out = aggregate_run_telemetry(tmp_path, active_state={"status": "completed"})
        assert out["total_records"] == 160
        assert out["processed_successfully"] == 160  # includes partial
        assert out["failed_records"] == 0
        assert out["percentage_complete"] == 100.0
        assert out["status"] == "Completed"

    def test_live_load_run_reports_bapi_successes(self, tmp_path):
        _write_summary(
            tmp_path,
            load_to_s4_enabled=True,
            objects_created_in_s4=25,
            results=[{"object": "Customer", "row_count": 30, "status": "ok"}],
            data_quality={"total_attempted": 30, "total_dead_letter": 5},
        )
        out = aggregate_run_telemetry(tmp_path, active_state={"status": "completed"})
        assert out["total_records"] == 30
        assert out["processed_successfully"] == 25
        assert out["failed_records"] == 5
        assert out["percentage_complete"] == 100.0  # 25+5 of 30

    def test_percentage_clamped_between_zero_and_one_hundred(self, tmp_path):
        _write_summary(
            tmp_path,
            load_to_s4_enabled=True,
            objects_created_in_s4=999,
            data_quality={"total_attempted": 10, "total_dead_letter": 0},
        )
        out = aggregate_run_telemetry(tmp_path, active_state={"status": "completed"})
        assert 0 <= out["percentage_complete"] <= 100

    def test_status_simulating_when_flag_set(self, tmp_path):
        out = aggregate_run_telemetry(
            tmp_path,
            active_state={"status": "running", "simulation_mode": True},
        )
        assert out["status"] == "Simulating"

    def test_status_processing_when_running_normally(self, tmp_path):
        out = aggregate_run_telemetry(
            tmp_path,
            active_state={"status": "running", "simulation_mode": False},
        )
        assert out["status"] == "Processing"

    def test_elapsed_computed_from_started_epoch(self, tmp_path):
        out = aggregate_run_telemetry(
            tmp_path,
            active_state={"status": "running", "started": time.time() - 12.3},
        )
        # Not strict (test may pause), but must be >=12 and small
        assert 12 <= out["runtime_elapsed_seconds"] < 20


# ─────────────────────────────────────────────────────────────────────────────
# bucket_errors
# ─────────────────────────────────────────────────────────────────────────────
class TestBucketErrors:
    def test_empty_when_no_dead_letter_file(self, tmp_path):
        assert bucket_errors(tmp_path) == []

    def test_identical_signatures_collapse_into_one_bucket(self, tmp_path):
        _write_dead_letter(tmp_path, [
            {"object": "BusinessPartner", "code": "DATA_QUALITY_REJECTION",
             "messages": ["NAME is required"]},
            {"object": "BusinessPartner", "code": "DATA_QUALITY_REJECTION",
             "messages": ["NAME is required"]},
            {"object": "BusinessPartner", "code": "DATA_QUALITY_REJECTION",
             "messages": ["NAME is required"]},
        ])
        buckets = bucket_errors(tmp_path)
        assert len(buckets) == 1
        assert buckets[0]["count"] == 3
        assert buckets[0]["error"] == "NAME is required"
        assert buckets[0]["objects"] == ["BusinessPartner"]

    def test_distinct_errors_produce_distinct_buckets(self, tmp_path):
        _write_dead_letter(tmp_path, [
            {"object": "OpenAR", "code": "DATA_QUALITY_REJECTION", "source_key": "1800000001",
             "messages": ["cc_org missing: COMP_CODE,CLEARING"]},
            {"object": "OpenAR", "code": "DATA_QUALITY_REJECTION", "source_key": "1800000002",
             "messages": ["cc_org missing: COMP_CODE,CLEARING"]},
            {"object": "ExchangeRates", "code": "BAPI_FAILURE",
             "messages": ["rate type 001 not defined in target (TCURV)"]},
        ])
        buckets = bucket_errors(tmp_path)
        assert len(buckets) == 2
        # Higher-count bucket first
        assert buckets[0]["count"] == 2
        assert "cc_org missing" in buckets[0]["error"]
        assert buckets[1]["count"] == 1

    def test_sample_source_keys_capped(self, tmp_path):
        _write_dead_letter(tmp_path, [
            {"object": "X", "code": "C", "source_key": f"k{i}", "messages": ["m"]}
            for i in range(10)
        ])
        buckets = bucket_errors(tmp_path, sample_size=3)
        assert len(buckets) == 1
        assert len(buckets[0]["sample_source_keys"]) == 3

    def test_remediation_is_populated_for_known_signatures(self, tmp_path):
        _write_dead_letter(tmp_path, [
            {"object": "BusinessPartner", "code": "DATA_QUALITY_REJECTION",
             "messages": ["NAME is required"]},
            {"object": "ExchangeRates", "code": "BAPI_FAILURE",
             "messages": ["rate type 001 not defined in target (TCURV)"]},
        ])
        buckets = bucket_errors(tmp_path)
        # Signatures are known - the hint should be the specific one, not the fallback
        for b in buckets:
            assert b["remediation"]
            assert "Review the failed-records CSV" not in b["remediation"]

    def test_unknown_signature_falls_back_to_generic_hint(self, tmp_path):
        _write_dead_letter(tmp_path, [
            {"object": "X", "code": "SOMETHING_NEW", "messages": ["fresh unknown thing"]},
        ])
        buckets = bucket_errors(tmp_path)
        assert "Review the failed-records CSV" in buckets[0]["remediation"]


# ─────────────────────────────────────────────────────────────────────────────
# failed_records_csv
# ─────────────────────────────────────────────────────────────────────────────
class TestFailedRecordsCsv:
    def test_empty_run_yields_header_only(self, tmp_path):
        out = failed_records_csv(tmp_path)
        text = out.decode("utf-8").splitlines()
        assert len(text) == 1  # header only
        assert text[0] == "object,source_key,code,messages,lane"

    def test_multiline_messages_joined_semicolon(self, tmp_path):
        _write_dead_letter(tmp_path, [
            {"object": "OpenAR", "source_key": "1800000001",
             "code": "DATA_QUALITY_REJECTION",
             "messages": ["cc_org missing: COMP_CODE", "second detail"],
             "lane": "MC"},
        ])
        out = failed_records_csv(tmp_path).decode("utf-8")
        reader = list(csv.DictReader(io.StringIO(out)))
        assert len(reader) == 1
        assert reader[0]["messages"] == "cc_org missing: COMP_CODE; second detail"
        assert reader[0]["object"] == "OpenAR"
        assert reader[0]["source_key"] == "1800000001"

    def test_ignores_non_dict_entries(self, tmp_path):
        _write_dead_letter(tmp_path, [
            "junk",
            {"object": "X", "source_key": "k", "code": "C", "messages": ["m"]},
            42,
        ])
        out = failed_records_csv(tmp_path).decode("utf-8")
        lines = out.splitlines()
        assert len(lines) == 2  # header + 1 valid row
