"""
Tests for Migrate4HANA 17-stage, 5-phase SAP Activate pipeline.
Run with: python -m pytest tests/ -v
"""

import sys
import os
import json
import importlib
from unittest.mock import MagicMock, patch
import pytest

# Add project paths
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "mock-ecc"))

from mock_data_generator import generate_complete_ecc_dataset, MockRFCConnection


@pytest.fixture(scope="module")
def mock_env():
    """Shared mock environment for all tests."""
    dataset = generate_complete_ecc_dataset()
    conn = MockRFCConnection(dataset)
    return {"dataset": dataset, "conn": conn}


def _load_handler(stage_dir):
    """Load a Lambda handler module with boto3/pyrfc mocked."""
    handler_path = os.path.join(PROJECT_DIR, "lambda", stage_dir)
    sys.path.insert(0, handler_path)
    module_name = f"handler_{stage_dir.replace('-', '_')}"

    # Mock boto3 at module level so imports don't fail
    mock_s3 = MagicMock()
    mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: b'{"test": true}')}
    mock_s3.put_object.return_value = {}

    mock_secrets = MagicMock()
    mock_secrets.get_secret_value.return_value = {
        "SecretString": json.dumps({"host": "mock", "sysnr": "00", "client": "100", "user": "RFC", "passwd": "x"})
    }

    mock_boto3 = MagicMock()
    mock_boto3.client.side_effect = lambda svc, **kw: mock_s3 if svc == "s3" else mock_secrets

    with patch.dict("sys.modules", {}):
        # Clear cached handler modules
        for key in list(sys.modules.keys()):
            if key == "handler":
                del sys.modules[key]

    import handler
    importlib.reload(handler)

    # Patch the module-level s3 client
    if hasattr(handler, "s3"):
        handler.s3 = mock_s3
    if hasattr(handler, "secrets"):
        handler.secrets = mock_secrets

    return handler, mock_s3


# =============================================================================
# Stage 2: Maintenance Planner
# =============================================================================
class TestMaintenancePlanner:
    def test_maintenance_planner_basic(self):
        """Test maintenance planner validation returns correct structure."""
        # Since the Lambda handler may not exist yet, test the local runner
        sys.path.insert(0, PROJECT_DIR)
        from run_local_pipeline import run_stage_2_maintenance_planner

        dataset = generate_complete_ecc_dataset()
        conn = MockRFCConnection(dataset)
        discovery_result = {"status": "success", "summary": {"total_programs": 100}}

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_stage_2_maintenance_planner(conn, discovery_result, tmpdir)

        assert result["status"] == "success"
        assert result["stack_components"] > 0
        assert result["prereqs_passed"] > 0
        assert result["conversion_path"] == "SUM/DMO Brownfield"

    def test_maintenance_planner_target_release(self):
        """Ensure target release is S/4HANA 2023 FPS02."""
        sys.path.insert(0, PROJECT_DIR)
        from run_local_pipeline import run_stage_2_maintenance_planner

        dataset = generate_complete_ecc_dataset()
        conn = MockRFCConnection(dataset)
        discovery_result = {"status": "success", "summary": {}}

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_stage_2_maintenance_planner(conn, discovery_result, tmpdir)

        assert result["target_release"] == "S/4HANA 2023 FPS02"


# =============================================================================
# Stage 3: Readiness Check
# =============================================================================
class TestReadinessCheck:
    def test_readiness_check_basic(self):
        """Test SAP readiness check returns valid results."""
        sys.path.insert(0, PROJECT_DIR)
        from run_local_pipeline import run_stage_3_readiness_check

        dataset = generate_complete_ecc_dataset()
        conn = MockRFCConnection(dataset)
        discovery_result = {"status": "success", "summary": {"total_programs": 100, "total_tables": 50}}

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_stage_3_readiness_check(conn, discovery_result, tmpdir)

        assert result["status"] == "success"
        assert result["readiness_score_pct"] > 0
        assert result["total_checks"] > 0
        assert result["passed_checks"] <= result["total_checks"]

    def test_readiness_check_has_business_functions(self):
        """Ensure business function compatibility is checked."""
        sys.path.insert(0, PROJECT_DIR)
        from run_local_pipeline import run_stage_3_readiness_check

        dataset = generate_complete_ecc_dataset()
        conn = MockRFCConnection(dataset)
        discovery_result = {"status": "success", "summary": {}}

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_stage_3_readiness_check(conn, discovery_result, tmpdir)

        assert result["compatible_business_functions"] > 0
        assert result["total_business_functions"] > 0


# =============================================================================
# Stage 4: Simplification Check
# =============================================================================
class TestSimplificationCheck:
    def test_simplification_check_basic(self):
        """Test simplification item check returns valid results."""
        sys.path.insert(0, PROJECT_DIR)
        from run_local_pipeline import run_stage_4_simplification_check

        dataset = generate_complete_ecc_dataset()
        conn = MockRFCConnection(dataset)
        discovery_result = {"status": "success", "summary": {}}

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_stage_4_simplification_check(conn, discovery_result, tmpdir)

        assert result["status"] == "success"
        assert result["total_items"] > 0
        assert result["critical_items"] > 0
        assert "programs_affected" in result

    def test_simplification_check_critical_items(self):
        """Ensure critical simplification items are identified."""
        sys.path.insert(0, PROJECT_DIR)
        from run_local_pipeline import run_stage_4_simplification_check

        dataset = generate_complete_ecc_dataset()
        conn = MockRFCConnection(dataset)
        discovery_result = {"status": "success", "summary": {}}

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_stage_4_simplification_check(conn, discovery_result, tmpdir)

        # Should have critical items for BP conversion, ACDOCA, and Material Ledger
        assert result["critical_items"] >= 3


# =============================================================================
# Stage 10: SUM/DMO Orchestrator
# =============================================================================
class TestSUMOrchestrator:
    def test_sum_dmo_basic(self):
        """Test SUM/DMO orchestrator returns valid results."""
        sys.path.insert(0, PROJECT_DIR)
        from run_local_pipeline import run_stage_10_sum_dmo

        dataset = generate_complete_ecc_dataset()
        conn = MockRFCConnection(dataset)
        results = {"cutover": {"go_no_go": "GO"}}

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "execution"), exist_ok=True)
            result = run_stage_10_sum_dmo(conn, results, tmpdir)

        assert result["status"] == "success"
        assert result["conversion_method"] == "SUM/DMO"
        assert result["phases_completed"] > 0
        assert len(result["tables_converted"]) > 0

    def test_sum_dmo_tables_converted(self):
        """Ensure the key tables are in the conversion list."""
        sys.path.insert(0, PROJECT_DIR)
        from run_local_pipeline import run_stage_10_sum_dmo

        dataset = generate_complete_ecc_dataset()
        conn = MockRFCConnection(dataset)
        results = {"cutover": {"go_no_go": "GO"}}

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "execution"), exist_ok=True)
            result = run_stage_10_sum_dmo(conn, results, tmpdir)

        tables = result["tables_converted"]
        assert any("ACDOCA" in t for t in tables)
        assert any("BUT000" in t for t in tables)
        assert any("MATDOC" in t for t in tables)

    def test_sum_dmo_duration(self):
        """Ensure simulated duration is reported."""
        sys.path.insert(0, PROJECT_DIR)
        from run_local_pipeline import run_stage_10_sum_dmo

        dataset = generate_complete_ecc_dataset()
        conn = MockRFCConnection(dataset)
        results = {}

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "execution"), exist_ok=True)
            result = run_stage_10_sum_dmo(conn, results, tmpdir)

        assert result["total_duration_simulated"] > 0


# =============================================================================
# Stage 9: Pre-Conversion Cutover Gate (formerly Stage 7)
# =============================================================================
class TestCutoverOrchestrator:
    def test_go_decision_with_all_stages_passed(self):
        with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}):
            handler, mock_s3 = _load_handler("cutover-orchestrator")

        event = {
            "metadata": {"run_id": "test-001", "input": {"dry_run": False}},
            "discovery": {"status": "success"},
            "code_analysis": {"status": "success"},
            "data_migration": {"status": "success"},
            "config": {"status": "success"},
            "roles": {"status": "success"},
            "integrations": {"status": "success"},
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] == "success"
        go = result.get("go_no_go", "").upper()
        assert go == "GO"

    def test_dry_run_mode(self):
        with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}):
            handler, _ = _load_handler("cutover-orchestrator")

        event = {
            "metadata": {"run_id": "test-dry", "input": {"dry_run": True}},
            "discovery": {"status": "success"},
            "code_analysis": {"status": "success"},
            "data_migration": {"status": "success"},
            "config": {"status": "success"},
            "roles": {"status": "success"},
            "integrations": {"status": "success"},
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] == "success"


# =============================================================================
# Stage 11: Code Deployer (formerly Stage 8)
# =============================================================================
class TestCodeDeployer:
    def test_deploy_programs_dry_run(self):
        handler, mock_s3 = _load_handler("code-deployer")

        event = {
            "metadata": {
                "run_id": "test-001",
                "input": {"s3_bucket": "test-bucket", "dry_run": True},
            },
            "results": {
                "stage_2": {
                    "status": "success",
                    "results": {"fixed_programs": {"ZTEST": "REPORT ZTEST.\nWRITE 'hello'."}},
                },
            },
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] == "success"


# =============================================================================
# Stage 12: Data Loader (formerly Stage 9)
# =============================================================================
class TestDataLoader:
    def test_data_loading_dry_run(self):
        handler, _ = _load_handler("data-loader")

        event = {
            "metadata": {
                "run_id": "test-001",
                "input": {"dry_run": True, "s3_bucket": "test"},
            },
            "results": {
                "stage_3": {
                    "status": "success",
                    "results": {"finance_lines": 100, "bp_created": 50},
                },
            },
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] == "success"


# =============================================================================
# Stage 13: Config Applier (formerly Stage 10)
# =============================================================================
class TestConfigApplier:
    def test_config_apply_dry_run(self):
        handler, _ = _load_handler("config-applier")

        event = {
            "metadata": {"run_id": "test-001", "input": {"dry_run": True}},
            "results": {
                "stage_4": {
                    "status": "success",
                    "results": {"config_areas": ["number_ranges", "ledgers"]},
                },
            },
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] in ("success", "validation_warnings")


# =============================================================================
# Stage 14: Role Provisioner (formerly Stage 11)
# =============================================================================
class TestRoleProvisioner:
    def test_role_provision_dry_run(self):
        handler, _ = _load_handler("role-provisioner")

        event = {
            "metadata": {"run_id": "test-001", "input": {"dry_run": True}},
            "results": {
                "stage_5": {
                    "status": "success",
                    "results": {"roles": [{"name": "Z_FI_001", "tcodes": ["FB01"]}]},
                },
            },
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] == "success"


# =============================================================================
# Stage 15: Integration Activator (formerly Stage 12)
# =============================================================================
class TestIntegrationActivator:
    def test_integration_activate_dry_run(self):
        handler, _ = _load_handler("integration-activator")

        event = {
            "metadata": {"run_id": "test-001", "input": {"dry_run": True}},
            "results": {
                "stage_6": {
                    "status": "success",
                    "results": {"rfc_total": 10, "automated": 8},
                },
            },
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] == "success"


# =============================================================================
# Stage 16: Migration Validator (formerly Stage 13)
# =============================================================================
class TestMigrationValidator:
    def test_validation_dry_run(self):
        handler, _ = _load_handler("migration-validator")

        event = {
            "metadata": {"run_id": "test-001", "input": {"dry_run": True}},
            "results": {
                "stage_8": {"status": "success", "results": {"deployed": 5}},
                "stage_9": {"status": "success", "results": {"loaded": 100}},
                "stage_10": {"status": "success"},
                "stage_11": {"status": "success"},
                "stage_12": {"status": "success"},
            },
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] == "success"


# =============================================================================
# Mock RFC Connection Tests
# =============================================================================
class TestMockRFCConnection:
    def test_write_bapi_transport_create(self, mock_env):
        conn = MockRFCConnection(mock_env["dataset"])
        result = conn.call("BAPI_CTREQUEST_CREATE", AUTHOR="TEST", TEXT="Test transport")
        assert "REQUESTID" in result

    def test_write_bapi_acc_doc_post(self, mock_env):
        conn = MockRFCConnection(mock_env["dataset"])
        result = conn.call("BAPI_ACC_DOCUMENT_POST",
                           DOCUMENTHEADER={"BUS_ACT": "RFBU", "DOC_TYPE": "SA"},
                           ACCOUNTGL=[], CURRENCYAMOUNT=[])
        assert "OBJ_KEY" in result

    def test_write_bapi_bp_create(self, mock_env):
        conn = MockRFCConnection(mock_env["dataset"])
        result = conn.call("BAPI_BUPA_CREATE_FROM_DATA",
                           PARTNERCATEGORY="2", PARTNERGROUP="BPCU",
                           CENTRALDATA={"NAME_ORG1": "Test Corp"},
                           CENTRALDATAORGANIZATION={}, ADDRESSDATA={})
        assert "BUSINESSPARTNER" in result

    def test_transaction_commit(self, mock_env):
        conn = MockRFCConnection(mock_env["dataset"])
        initial = conn._committed
        conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        assert conn._committed == initial + 1

    def test_call_count_increments(self, mock_env):
        conn = MockRFCConnection(mock_env["dataset"])
        assert conn._call_count == 0
        conn.call("RFC_READ_TABLE", QUERY_TABLE="TADIR", FIELDS=[{"FIELDNAME": "OBJ_NAME"}])
        assert conn._call_count == 1

    def test_read_table_returns_data(self, mock_env):
        conn = MockRFCConnection(mock_env["dataset"])
        result = conn.call("RFC_READ_TABLE", QUERY_TABLE="TADIR",
                           FIELDS=[{"FIELDNAME": "OBJ_NAME"}])
        assert "DATA" in result


# =============================================================================
# End-to-End Pipeline Test
# =============================================================================
class TestEndToEndPipeline:
    def test_mock_dataset_has_required_fields(self):
        dataset = generate_complete_ecc_dataset()

        assert "programs" in dataset
        assert "tables" in dataset
        assert "function_modules" in dataset
        assert "org_structure" in dataset
        assert "roles" in dataset
        assert "finance" in dataset
        assert "customers" in dataset
        assert "vendors" in dataset
        assert "abap_source" in dataset
        assert len(dataset["programs"]) > 100
        assert len(dataset["customers"]) > 100
        assert len(dataset["finance"]["bkpf"]) > 100

    def test_mock_connection_read_operations(self):
        dataset = generate_complete_ecc_dataset()
        conn = MockRFCConnection(dataset)

        # Discovery reads — use OPTIONS to filter for custom programs
        result = conn.call("RFC_READ_TABLE", QUERY_TABLE="TADIR",
                           FIELDS=[{"FIELDNAME": "OBJ_NAME"}],
                           OPTIONS=[{"TEXT": "DEVCLASS LIKE 'Z%'"}])
        # The mock should return data from the dataset
        assert "DATA" in result or "FIELDS" in result


# =============================================================================
# 17-Stage Pipeline Structure Test
# =============================================================================
class TestPipelineStructure:
    """Verify the 17-stage, 5-phase pipeline structure."""

    def test_pipeline_has_17_stages(self):
        """Verify the local runner has all 17 stages defined."""
        sys.path.insert(0, PROJECT_DIR)
        import run_local_pipeline as rlp
        # Check all stage runner functions exist
        stage_functions = [
            "run_stage_1_discovery",
            "run_stage_2_maintenance_planner",
            "run_stage_3_readiness_check",
            "run_stage_4_simplification_check",
            "run_stage_5_code_analysis",
            "run_stage_6_data_hygiene",
            "run_stage_7_data_assessment",
            "run_stage_8_config_assessment",
            "run_stage_9_pre_conversion_gate",
            "run_stage_10_sum_dmo",
            "run_stage_11_code_deploy",
            "run_stage_12_data_load",
            "run_stage_13_config_apply",
            "run_stage_14_role_provision",
            "run_stage_15_integration_activate",
            "run_stage_16_validate",
            "run_stage_17_test_generation",
        ]
        for func_name in stage_functions:
            assert hasattr(rlp, func_name), f"Missing stage function: {func_name}"

    def test_pipeline_phase_banner_exists(self):
        """Verify phase banner function exists."""
        sys.path.insert(0, PROJECT_DIR)
        import run_local_pipeline as rlp
        assert hasattr(rlp, "phase_banner")


# =============================================================================
# Rule Router Tests
# =============================================================================
class TestRuleRouter:
    def test_fallback_rules_count(self):
        """Verify fallback rules have at least 25 rules."""
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
        with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}):
            import importlib
            import rule_router
            importlib.reload(rule_router)
            rules = rule_router._get_fallback_rules()
        assert len(rules) >= 25, f"Expected >= 25 fallback rules, got {len(rules)}"

    def test_fallback_rules_category_filter(self):
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
        with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}):
            import importlib
            import rule_router
            importlib.reload(rule_router)
            syntax_rules = rule_router._get_fallback_rules(category="SYNTAX")
        assert all(r["category"] == "SYNTAX" for r in syntax_rules)
        assert len(syntax_rules) >= 5

    def test_fallback_rules_data_model(self):
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
        with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}):
            import importlib
            import rule_router
            importlib.reload(rule_router)
            db_rules = rule_router._get_fallback_rules(category="DATA_MODEL")
        assert len(db_rules) >= 8
        bseg_rule = [r for r in db_rules if "BSEG" in r.get("ecc_pattern", "")]
        assert len(bseg_rule) >= 1

    def test_fallback_rules_structure(self):
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))
        with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}):
            import importlib
            import rule_router
            importlib.reload(rule_router)
            for rule in rule_router._get_fallback_rules():
                assert "rule_id" in rule
                assert "category" in rule
                assert "ecc_pattern" in rule
                assert "s4_replacement" in rule
                assert "description" in rule


# =============================================================================
# ST03N Analyzer / Process Miner Tests
# =============================================================================
class TestST03NAnalyzer:
    def test_fiori_catalog_size(self):
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "process-miner"))
        from st03n_analyzer import ST03NAnalyzer
        analyzer = ST03NAnalyzer()
        assert len(analyzer.fiori_catalog) >= 25, f"Expected >= 25 Fiori mappings, got {len(analyzer.fiori_catalog)}"

    def test_fiori_mapping_for_common_tcodes(self):
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "process-miner"))
        from st03n_analyzer import ST03NAnalyzer
        analyzer = ST03NAnalyzer()
        required_tcodes = ["FB50", "FB60", "VA01", "ME21N", "BP", "MIGO", "VL01N", "VF01"]
        for tcode in required_tcodes:
            assert tcode in analyzer.fiori_catalog, f"Missing Fiori mapping for {tcode}"

    def test_analyze_usage_with_known_tcodes(self):
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "process-miner"))
        from st03n_analyzer import ST03NAnalyzer
        analyzer = ST03NAnalyzer()
        usage_data = [
            {"tcode": "FB50", "executions": 500},
            {"tcode": "VA01", "executions": 200},
            {"tcode": "ME21N", "executions": 100},
            {"tcode": "ZFI_CUSTOM", "executions": 0},
        ]
        result = analyzer.analyze_usage(usage_data)
        assert result["metrics"]["active_tcodes_count"] == 3
        assert result["metrics"]["unused_zprograms_count"] == 1
        assert result["metrics"]["fiori_mapped_count"] == 3

    def test_analyze_usage_with_unknown_tcode(self):
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "process-miner"))
        from st03n_analyzer import ST03NAnalyzer
        analyzer = ST03NAnalyzer()
        usage_data = [{"tcode": "XXXX_UNKNOWN", "executions": 100}]
        result = analyzer.analyze_usage(usage_data)
        assert result["metrics"]["active_tcodes_count"] == 1
        assert result["metrics"]["fiori_mapped_count"] == 0


# =============================================================================
# DITL Generator Tests
# =============================================================================
class TestDITLGenerator:
    def test_generates_runnable_scripts(self):
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "test-generator"))
        from ditl_generator import DITLTestGenerator
        gen = DITLTestGenerator()
        mappings = [
            {"tcode": "FB50", "fiori_app_id": "F0718", "fiori_name": "Post General Journal Entries"},
        ]
        tests = gen.process_workload_to_tests(mappings)
        # Should include test + support file
        assert len(tests) >= 2
        script = tests[0]["test_script"]
        assert "loginToS4HANA" in script
        assert "navToApp" in script
        assert "GeneralJournalEntry" in script

    def test_generates_support_commands(self):
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "test-generator"))
        from ditl_generator import DITLTestGenerator
        gen = DITLTestGenerator()
        support = gen.generate_support_file()
        assert "Cypress.Commands.add" in support
        assert "loginToS4HANA" in support
        assert "navToApp" in support

    def test_scripts_have_odata_intercepts(self):
        sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "test-generator"))
        from ditl_generator import DITLTestGenerator
        gen = DITLTestGenerator()
        script = gen.generate_cypress_script(
            "Test_FB50", "F0718", "Post Journal Entry",
            ["/sap/opu/odata/sap/API_JOURNALENTRYITEMBASIC_SRV"]
        )
        assert "intercept" in script
        assert "API_JOURNALENTRYITEMBASIC_SRV" in script


# =============================================================================
# Rollback Manager Tests
# =============================================================================
class TestRollbackManager:
    def test_rollback_dry_run(self):
        handler, mock_s3 = _load_handler("rollback-manager")
        event = {
            "run_id": "test-rollback-001",
            "error_context": {"failed_stage": "data-loader", "error": "Test error"},
            "documents_to_reverse": [
                {"doc_number": "1000000001", "company_code": "1000", "fiscal_year": "2026"},
            ],
            "transports_to_delete": [
                {"request_number": "NPLK900001"},
            ],
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] in ("ROLLBACK_COMPLETE", "ROLLBACK_PARTIAL")
        assert "summary" in result
        assert result["summary"]["total_items"] >= 2

    def test_rollback_includes_acdoca(self):
        handler, mock_s3 = _load_handler("rollback-manager")
        event = {
            "run_id": "test-acdoca-rollback",
            "error_context": {"failed_stage": "config-applier"},
            "acdoca_docs_to_reverse": [
                {"doc_number": "5000000001", "company_code": "1000", "fiscal_year": "2026", "ledger": "0L"},
            ],
        }
        result = handler.lambda_handler(event, None)
        assert "acdoca_reversals" in result.get("report", {})

    def test_rollback_includes_spro(self):
        handler, mock_s3 = _load_handler("rollback-manager")
        event = {
            "run_id": "test-spro-rollback",
            "error_context": {"failed_stage": "role-provisioner"},
            "spro_configs_to_rollback": [
                {"table": "T001", "key_fields": {"BUKRS": "1000"}, "description": "Company code config"},
            ],
        }
        result = handler.lambda_handler(event, None)
        assert "spro_rollbacks" in result.get("report", {})


# =============================================================================
# Config Applier Validation Tests
# =============================================================================
class TestConfigApplierValidation:
    def test_dry_run_validates_config(self):
        handler, _ = _load_handler("config-applier")
        event = {
            "metadata": {"run_id": "test-validate", "input": {"dry_run": True}},
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] in ("success", "validation_warnings")
        assert "validation_errors" in result.get("results", {})

    def test_dry_run_reports_summary(self):
        handler, _ = _load_handler("config-applier")
        event = {
            "metadata": {"run_id": "test-summary", "input": {"dry_run": True}},
        }
        result = handler.lambda_handler(event, None)
        summary = result.get("results", {}).get("summary", {})
        assert "number_ranges" in summary
        assert "ledgers" in summary
        assert "bp_groupings" in summary


# =============================================================================
# Negative / Error Handling Tests
# =============================================================================
class TestErrorHandling:
    def test_cutover_with_missing_stages(self):
        """Cutover should handle event with missing planning stage results."""
        with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}):
            handler, _ = _load_handler("cutover-orchestrator")
        event = {
            "metadata": {"run_id": "test-missing", "input": {"dry_run": False}},
            "discovery": {"status": "success"},
            # Missing other stages
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] in ("success", "failed", "blocked")

    def test_data_loader_with_empty_input(self):
        handler, _ = _load_handler("data-loader")
        event = {
            "metadata": {"run_id": "test-empty", "input": {"dry_run": True, "s3_bucket": "test"}},
            "results": {},
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] == "success"

    def test_validator_with_no_prior_stages(self):
        handler, _ = _load_handler("migration-validator")
        event = {
            "metadata": {"run_id": "test-noprev", "input": {"dry_run": True}},
            "results": {},
        }
        result = handler.lambda_handler(event, None)
        assert result["status"] == "success"
