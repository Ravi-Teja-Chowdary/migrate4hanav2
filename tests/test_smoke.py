"""
Minimal smoke tests replacing the former mock-ECC-driven integration suite.

The prior suites (test_execution_stages.py and test_sap_integration.py) relied
on the deleted `mock-ecc/` package. With mock mode removed, integration tests
that require a live SAP system are now opt-in via the SAP_TEST_* env vars, and
the module-level smoke tests below verify that key packages still import
cleanly without any mock fixtures.
"""

import importlib
import os
import sys

import pytest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for sub in ("", os.path.join("lambda", "code-analyzer"),
            os.path.join("lambda", "utils")):
    p = os.path.join(PROJECT_DIR, sub) if sub else PROJECT_DIR
    if p not in sys.path:
        sys.path.insert(0, p)


def test_run_local_pipeline_imports():
    """run_local_pipeline.py must import without mock-ecc."""
    mod = importlib.import_module("run_local_pipeline")
    assert hasattr(mod, "main")


def test_genai_router_imports():
    """genai_router must expose route_analysis after restoring Ollama path."""
    mod = importlib.import_module("genai_router")
    assert hasattr(mod, "route_analysis")


def test_ollama_engine_imports():
    """The air-gapped LLM engine module must import (no network required)."""
    mod = importlib.import_module("ollama_genai_engine")
    assert hasattr(mod, "invoke_ollama")


@pytest.mark.skipif(
    not all(os.environ.get(v) for v in
            ["SAP_TEST_HOST", "SAP_TEST_SYSNR", "SAP_TEST_CLIENT",
             "SAP_TEST_USER", "SAP_TEST_PASSWD"]),
    reason="SAP_TEST_* env vars not set — live SAP tests skipped",
)
def test_live_rfc_smoke():
    """Opt-in live-RFC smoke test (only runs when SAP_TEST_* env is set)."""
    import pyrfc  # noqa: F401
    from real_rfc_connection import RealRFCConnection

    conn = RealRFCConnection({
        "ashost": os.environ["SAP_TEST_HOST"],
        "sysnr": os.environ["SAP_TEST_SYSNR"],
        "client": os.environ["SAP_TEST_CLIENT"],
        "user": os.environ["SAP_TEST_USER"],
        "passwd": os.environ["SAP_TEST_PASSWD"],
    }, limit=5)
    assert "system_info" in conn.dataset
    conn.close()
