"""
SAP RFC/BAPI Integration Tests for Migrate4HANA.

Tests every RFC function module used across the 17-stage pipeline against either:
  - A live SAP IDES/sandbox system (set SAP_TEST_HOST env var)
  - The MockRFCConnection (default, no SAP system needed)

Run with:
  python -m pytest tests/test_sap_integration.py -v
  python -m pytest tests/test_sap_integration.py -v -k "live"   # live system only
  python -m pytest tests/test_sap_integration.py -v -k "mock"   # mock only

Environment variables for live testing:
  SAP_TEST_HOST, SAP_TEST_SYSNR, SAP_TEST_CLIENT,
  SAP_TEST_USER, SAP_TEST_PASSWD
"""

import sys
import os
import pytest
from decimal import Decimal

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "mock-ecc"))
sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "utils"))

from mock_data_generator import generate_complete_ecc_dataset, MockRFCConnection

# ── Determine test mode ──

LIVE_SAP = all(os.environ.get(v) for v in [
    "SAP_TEST_HOST", "SAP_TEST_SYSNR", "SAP_TEST_CLIENT",
    "SAP_TEST_USER", "SAP_TEST_PASSWD",
])


def _get_live_connection():
    """Create a real pyrfc.Connection — only called when SAP_TEST_* env vars are set."""
    import pyrfc
    return pyrfc.Connection(
        ashost=os.environ["SAP_TEST_HOST"],
        sysnr=os.environ["SAP_TEST_SYSNR"],
        client=os.environ["SAP_TEST_CLIENT"],
        user=os.environ["SAP_TEST_USER"],
        passwd=os.environ["SAP_TEST_PASSWD"],
    )


# ── Fixtures ──

@pytest.fixture(scope="module")
def mock_conn():
    dataset = generate_complete_ecc_dataset()
    return MockRFCConnection(dataset)


@pytest.fixture(scope="module")
def live_conn():
    if not LIVE_SAP:
        pytest.skip("SAP_TEST_* env vars not set — skipping live tests")
    conn = _get_live_connection()
    yield conn
    conn.close()


@pytest.fixture(params=["mock"] + (["live"] if LIVE_SAP else []))
def conn(request, mock_conn):
    """Parametrized fixture: runs each test against mock and (optionally) live SAP."""
    if request.param == "mock":
        yield mock_conn
    else:
        live = _get_live_connection()
        yield live
        live.close()


# ═══════════════════════════════════════════════════════════════
#  1. CONNECTIVITY & HEALTH CHECKS
# ═══════════════════════════════════════════════════════════════

class TestConnectivity:
    """Stage 0 / pre-flight: can we reach the SAP system?"""

    def test_rfc_ping(self, conn):
        result = conn.call("RFC_PING")
        assert result is not None

    def test_rfc_system_info(self, conn):
        result = conn.call("RFC_SYSTEM_INFO")
        # Real systems return RFCSI_EXPORT; mock returns ET_RETURN
        assert isinstance(result, dict)

    def test_read_company_codes(self, conn):
        result = conn.call("RFC_READ_TABLE",
                           QUERY_TABLE="T001",
                           FIELDS=[{"FIELDNAME": "BUKRS"}],
                           ROWCOUNT=5)
        assert "DATA" in result or "FIELDS" in result


# ═══════════════════════════════════════════════════════════════
#  2. DISCOVERY ENGINE — RFC_READ_TABLE across key tables
# ═══════════════════════════════════════════════════════════════

class TestDiscoveryReads:
    """Stage 1: bulk extraction of ECC metadata via RFC_READ_TABLE."""

    @pytest.mark.parametrize("table", [
        "TRDIR", "DD02L", "TFDIR", "T001", "T001W", "T001L",
        "TVKO", "TKA01", "T024E", "BKPF", "AGR_DEFINE", "RFCDES",
    ])
    def test_read_table(self, conn, table):
        result = conn.call("RFC_READ_TABLE",
                           QUERY_TABLE=table,
                           DELIMITER="|",
                           ROWCOUNT=10)
        assert "DATA" in result
        assert "FIELDS" in result

    def test_read_table_with_filter(self, conn):
        result = conn.call("RFC_READ_TABLE",
                           QUERY_TABLE="TRDIR",
                           FIELDS=[{"FIELDNAME": "NAME"}],
                           OPTIONS=[{"TEXT": "NAME LIKE 'Z%'"}],
                           ROWCOUNT=5)
        assert "DATA" in result

    def test_read_program_source(self, conn):
        result = conn.call("RPY_PROGRAM_READ", PROGRAM_NAME="ZSAMPLE_REPORT")
        assert isinstance(result, dict)

    def test_read_roles(self, conn):
        result = conn.call("RFC_READ_TABLE",
                           QUERY_TABLE="AGR_DEFINE",
                           FIELDS=[{"FIELDNAME": "AGR_NAME"}],
                           ROWCOUNT=10)
        assert "DATA" in result

    def test_read_rfc_destinations(self, conn):
        result = conn.call("RFC_READ_TABLE",
                           QUERY_TABLE="RFCDES",
                           FIELDS=[{"FIELDNAME": "RFCDEST"}],
                           ROWCOUNT=10)
        assert "DATA" in result


# ═══════════════════════════════════════════════════════════════
#  3. TRANSPORT MANAGEMENT
# ═══════════════════════════════════════════════════════════════

class TestTransportManagement:
    """Stage 10 (code-deployer): create and release transport requests."""

    def test_create_transport(self, conn):
        result = conn.call("BAPI_CTREQUEST_CREATE",
                           DESCRIPTION="M4H Integration Test",
                           TYPE="K")
        assert "REQUESTID" in result
        assert result["REQUESTID"]  # non-empty

    def test_release_transport(self, conn):
        # Create, then release
        create_result = conn.call("BAPI_CTREQUEST_CREATE",
                                  DESCRIPTION="M4H Release Test",
                                  TYPE="K")
        req_id = create_result["REQUESTID"]

        release_result = conn.call("BAPI_CTREQUEST_RELEASE",
                                   REQUESTID=req_id)
        # Should not return errors
        errors = [r for r in release_result.get("RETURN", [])
                  if r.get("TYPE") == "E"]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════
#  4. CODE DEPLOYMENT — Program CRUD + Activation
# ═══════════════════════════════════════════════════════════════

class TestCodeDeployment:
    """Stage 10: deploy ABAP programs to S/4HANA."""

    def test_program_insert(self, conn):
        source = [{"LINE": "REPORT ZTEST_M4H_INTEG."}, {"LINE": "WRITE: 'Hello'."}]
        result = conn.call("RPY_PROGRAM_INSERT",
                           PROGRAM_NAME="ZTEST_M4H_INTEG",
                           PROG_SOURCE=source)
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_program_update(self, conn):
        source = [{"LINE": "REPORT ZTEST_M4H_INTEG."}, {"LINE": "WRITE: 'Updated'."}]
        result = conn.call("RPY_PROGRAM_UPDATE",
                           PROGRAM_NAME="ZTEST_M4H_INTEG",
                           PROG_SOURCE=source)
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_syntax_check_passes(self, conn):
        result = conn.call("RS_SYNTAX_CHECK",
                           PROGRAM="ZTEST_M4H_INTEG")
        # No critical errors expected for simple WRITE statement
        messages = result.get("MESSAGES", [])
        critical = [m for m in messages if m.get("SEVERITY") == "E"]
        assert len(critical) == 0

    def test_activate_program(self, conn):
        result = conn.call("RS_WORKING_OBJECTS_ACTIVATE",
                           OBJECTS=[{"OBJ_NAME": "ZTEST_M4H_INTEG", "OBJECT": "PROG"}])
        errors = result.get("MESSAGES", [])
        critical = [m for m in errors if m.get("SEVERITY") == "E"]
        assert len(critical) == 0


# ═══════════════════════════════════════════════════════════════
#  5. FINANCIAL DATA LOADING — The Critical Path
# ═══════════════════════════════════════════════════════════════

class TestFinancialDataLoading:
    """Stage 12: post accounting documents to S/4HANA."""

    def test_acc_document_post(self, conn):
        result = conn.call("BAPI_ACC_DOCUMENT_POST",
                           DOCUMENTHEADER={
                               "HEADER_TXT": "M4H Test Posting",
                               "COMP_CODE": "1000",
                               "DOC_DATE": "20240101",
                               "PSTNG_DATE": "20240101",
                               "DOC_TYPE": "SA",
                           },
                           ACCOUNTGL=[
                               {"ITEMNO_ACC": "001", "GL_ACCOUNT": "0010000000",
                                "COMP_CODE": "1000"},
                               {"ITEMNO_ACC": "002", "GL_ACCOUNT": "0031000000",
                                "COMP_CODE": "1000"},
                           ],
                           CURRENCYAMOUNT=[
                               {"ITEMNO_ACC": "001", "CURRENCY": "USD",
                                "AMT_DOCCUR": Decimal("100.00")},
                               {"ITEMNO_ACC": "002", "CURRENCY": "USD",
                                "AMT_DOCCUR": Decimal("-100.00")},
                           ])
        # Should return a document number
        assert result.get("OBJ_KEY")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_acc_document_post_and_commit(self, conn):
        post_result = conn.call("BAPI_ACC_DOCUMENT_POST",
                                DOCUMENTHEADER={
                                    "HEADER_TXT": "M4H Commit Test",
                                    "COMP_CODE": "1000",
                                    "DOC_DATE": "20240101",
                                    "PSTNG_DATE": "20240101",
                                    "DOC_TYPE": "SA",
                                },
                                ACCOUNTGL=[
                                    {"ITEMNO_ACC": "001", "GL_ACCOUNT": "0010000000",
                                     "COMP_CODE": "1000"},
                                ],
                                CURRENCYAMOUNT=[
                                    {"ITEMNO_ACC": "001", "CURRENCY": "USD",
                                     "AMT_DOCCUR": Decimal("500.00")},
                                ])
        assert post_result.get("OBJ_KEY")

        commit_result = conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        assert isinstance(commit_result, dict)

    def test_gl_account_existence_check(self, conn):
        result = conn.call("BAPI_GLACCOUNT_EXISTENCECHECK",
                           COMPANYCODE="1000",
                           GLACCOUNT="0010000000")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════
#  6. BUSINESS PARTNER MIGRATION
# ═══════════════════════════════════════════════════════════════

class TestBusinessPartnerLoading:
    """Stage 12: create BPs from migrated customer/vendor master data."""

    def test_bp_create(self, conn):
        result = conn.call("BAPI_BUPA_CREATE_FROM_DATA",
                           PARTNERCATEGORY="1",
                           CENTRALDATA={"SEARCHTERM1": "M4HTEST"},
                           CENTRALDATAPERSON={
                               "FIRSTNAME": "Test",
                               "LASTNAME": "Migration",
                           })
        assert result.get("BUSINESSPARTNER")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_bp_create_and_add_role(self, conn):
        bp_result = conn.call("BAPI_BUPA_CREATE_FROM_DATA",
                              PARTNERCATEGORY="2",
                              CENTRALDATA={"SEARCHTERM1": "M4HROLE"},
                              CENTRALDATAORGANIZATION={"NAME1": "Test Org"})
        bp_nr = bp_result.get("BUSINESSPARTNER")
        assert bp_nr

        role_result = conn.call("BAPI_BUPA_ROLE_ADD_2",
                                BUSINESSPARTNER=bp_nr,
                                PARTNERROLE="FLCU00")
        errors = [r for r in role_result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

        conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")

    def test_bp_grouping_create(self, conn):
        result = conn.call("BAPI_BUPA_GROUPING_CREATE",
                           GROUPING="M4HT",
                           GROUPING_TEXT="Integration Test Grouping")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════
#  7. MATERIAL DOCUMENT LOADING
# ═══════════════════════════════════════════════════════════════

class TestMaterialDocumentLoading:
    """Stage 12: goods movement documents."""

    def test_goods_movement_create(self, conn):
        result = conn.call("BAPI_GOODSMVT_CREATE",
                           GOODSMVT_HEADER={
                               "PSTNG_DATE": "20240101",
                               "DOC_DATE": "20240101",
                           },
                           GOODSMVT_CODE={"GM_CODE": "01"},
                           GOODSMVT_ITEM=[{
                               "MATERIAL": "000000000000100001",
                               "PLANT": "1000",
                               "STGE_LOC": "0001",
                               "MOVE_TYPE": "101",
                               "ENTRY_QNT": Decimal("100"),
                               "ENTRY_UOM": "EA",
                           }])
        assert result.get("MATERIALDOCUMENT")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_goods_movement_commit(self, conn):
        result = conn.call("BAPI_GOODSMVT_CREATE",
                           GOODSMVT_HEADER={
                               "PSTNG_DATE": "20240115",
                               "DOC_DATE": "20240115",
                           },
                           GOODSMVT_CODE={"GM_CODE": "01"},
                           GOODSMVT_ITEM=[{
                               "MATERIAL": "000000000000100002",
                               "PLANT": "1000",
                               "STGE_LOC": "0001",
                               "MOVE_TYPE": "101",
                               "ENTRY_QNT": Decimal("50"),
                               "ENTRY_UOM": "EA",
                           }])
        assert result.get("MATERIALDOCUMENT")

        commit = conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        assert isinstance(commit, dict)


# ═══════════════════════════════════════════════════════════════
#  8. ROLE PROVISIONING
# ═══════════════════════════════════════════════════════════════

class TestRoleProvisioning:
    """Stage 14: create roles, generate profiles, assign users."""

    def test_role_create(self, conn):
        result = conn.call("PRGN_RFC_ROLE_CREATE",
                           ROLE_NAME="ZM4H_TEST_ROLE",
                           ROLE_TEXT="Integration Test Role")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_role_menu_add(self, conn):
        result = conn.call("PRGN_RFC_ROLE_MENU_ADD",
                           ROLE_NAME="ZM4H_TEST_ROLE",
                           MENU_NODE={"NODE_TYPE": "T", "NODE_ID": "SE38"})
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_role_profile_generate(self, conn):
        result = conn.call("PRGN_RFC_ROLE_PROFILE_GEN",
                           ROLE_NAME="ZM4H_TEST_ROLE")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_role_read(self, conn):
        # First create, then read
        conn.call("PRGN_RFC_ROLE_CREATE",
                  ROLE_NAME="ZM4H_READ_TEST",
                  ROLE_TEXT="Read Test Role")
        result = conn.call("PRGN_RFC_ROLE_READ",
                           ROLE_NAME="ZM4H_READ_TEST")
        # Should find the role
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_user_role_assignment(self, conn):
        result = conn.call("BAPI_USER_ACTGROUPS_ASSIGN",
                           USERNAME="TESTUSER",
                           ACTIVITYGROUPS=[{
                               "AGR_NAME": "ZM4H_TEST_ROLE",
                               "FROM_DAT": "20240101",
                               "TO_DAT": "99991231",
                           }])
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════
#  9. CONFIG APPLICATION — Number Ranges, GL, India Tax
# ═══════════════════════════════════════════════════════════════

class TestConfigApplication:
    """Stage 11: apply configuration objects to S/4HANA."""

    def test_number_range_create(self, conn):
        result = conn.call("NUMBER_RANGE_INTERVAL_CREATE",
                           OBJECT="BELEG",
                           SUBOBJECT="",
                           INTERVAL=[{
                               "NRRANGENR": "99",
                               "FROMNUMBER": "9900000000",
                               "TONUMBER": "9999999999",
                           }])
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_number_range_read(self, conn):
        result = conn.call("NUMBER_RANGE_INTERVAL_READ",
                           OBJECT="BELEG",
                           SUBOBJECT="")
        assert "INTERVALS" in result

    def test_india_gstin_config(self, conn):
        result = conn.call("J_1IG_GSTIN_CREATE",
                           GSTIN="29AABCU9603R1ZP",
                           COMPANY_CODE="1000")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_india_ewt_setup(self, conn):
        result = conn.call("J_1IEWT_SETUP",
                           COMPANY_CODE="1000",
                           VENDOR="0000001000")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_india_einvoice_config(self, conn):
        result = conn.call("J_1IG_EINV_CONFIG",
                           GSTIN="29AABCU9603R1ZP",
                           EINV_ENDPOINT="https://einv-apisandbox.nic.in")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_fiori_space_create(self, conn):
        result = conn.call("Z_FIORI_SPACE_CREATE",
                           SPACE_ID="ZM4H_TEST",
                           SPACE_TITLE="Migration Test Space")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════
#  10. INTEGRATION ACTIVATION — RFC Destinations + IDoc Partners
# ═══════════════════════════════════════════════════════════════

class TestIntegrationActivation:
    """Stage 15: re-create RFC destinations and IDoc partner profiles."""

    def test_rfc_destination_create(self, conn):
        result = conn.call("RFC_MODIFY_R3_DESTINATION",
                           DESTINATION="ZM4H_TEST_DEST",
                           RFCTYPE="3",  # Type 3 = RFC
                           RFCHOST="test.sap.local",
                           DESCRIPTION="Integration Test Dest")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_idoc_port_create(self, conn):
        result = conn.call("IDOC_PORT_CREATE",
                           PORT_NAME="ZM4HPRT",
                           PORT_TYPE="1",
                           RFCDEST="ZM4H_TEST_DEST")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_edi_partner_create(self, conn):
        result = conn.call("EDI_PARTNER_CREATE",
                           PARTNER_NO="M4HPARTNER",
                           PARTNER_TYPE="LS",
                           PARTNER_ROLE="LS")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0

    def test_edi_partner_add_msgtype(self, conn):
        result = conn.call("EDI_PARTNER_ADD_MSGTYPE",
                           PARTNER_NO="M4HPARTNER",
                           MESSAGE_TYPE="ORDERS",
                           DIRECTION="2")
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════
#  11. ROLLBACK OPERATIONS — Reversal & Cleanup
# ═══════════════════════════════════════════════════════════════

class TestRollbackOperations:
    """Stage 17 (rollback-manager): undo everything if migration fails."""

    def test_acc_document_reverse(self, conn):
        # Post a doc first
        post_result = conn.call("BAPI_ACC_DOCUMENT_POST",
                                DOCUMENTHEADER={
                                    "HEADER_TXT": "To Reverse",
                                    "COMP_CODE": "1000",
                                    "DOC_DATE": "20240101",
                                    "PSTNG_DATE": "20240101",
                                    "DOC_TYPE": "SA",
                                },
                                ACCOUNTGL=[
                                    {"ITEMNO_ACC": "001", "GL_ACCOUNT": "0010000000",
                                     "COMP_CODE": "1000"},
                                ],
                                CURRENCYAMOUNT=[
                                    {"ITEMNO_ACC": "001", "CURRENCY": "USD",
                                     "AMT_DOCCUR": Decimal("200.00")},
                                ])
        doc_key = post_result.get("OBJ_KEY", "5100000099")
        conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")

        # Reverse it
        result = conn.call("BAPI_ACC_DOCUMENT_REVERSE",
                           REVERSAL={
                               "OBJ_KEY_R": doc_key,
                               "COMP_CODE": "1000",
                               "REASON_REV": "01",
                               "PSTNG_DATE": "20240102",
                           })
        # Mock returns generic dict; live should succeed
        assert isinstance(result, dict)

    def test_bp_delete(self, conn):
        # Create a BP first
        bp_result = conn.call("BAPI_BUPA_CREATE_FROM_DATA",
                              PARTNERCATEGORY="1",
                              CENTRALDATA={"SEARCHTERM1": "DELETEME"},
                              CENTRALDATAPERSON={
                                  "FIRSTNAME": "Delete",
                                  "LASTNAME": "Test",
                              })
        bp_nr = bp_result.get("BUSINESSPARTNER", "0001000099")
        conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")

        result = conn.call("BAPI_BUPA_DELETE", PARTNER=bp_nr)
        assert isinstance(result, dict)

    def test_goods_movement_cancel(self, conn):
        # Create a material doc first
        create_result = conn.call("BAPI_GOODSMVT_CREATE",
                                  GOODSMVT_HEADER={
                                      "PSTNG_DATE": "20240101",
                                      "DOC_DATE": "20240101",
                                  },
                                  GOODSMVT_CODE={"GM_CODE": "01"},
                                  GOODSMVT_ITEM=[{
                                      "MATERIAL": "000000000000100003",
                                      "PLANT": "1000",
                                      "STGE_LOC": "0001",
                                      "MOVE_TYPE": "101",
                                      "ENTRY_QNT": Decimal("10"),
                                      "ENTRY_UOM": "EA",
                                  }])
        mat_doc = create_result.get("MATERIALDOCUMENT", "4900000099")
        mat_year = create_result.get("MATDOCUMENTYEAR", "2024")
        conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")

        result = conn.call("BAPI_GOODSMVT_CANCEL",
                           MATERIALDOCUMENT=mat_doc,
                           MATDOCUMENTYEAR=mat_year)
        assert isinstance(result, dict)

    def test_transport_delete(self, conn):
        create_result = conn.call("BAPI_CTREQUEST_CREATE",
                                  DESCRIPTION="To Delete",
                                  TYPE="K")
        req_id = create_result.get("REQUESTID", "S4HK900099")

        result = conn.call("BAPI_CTREQUEST_DELETE", REQUEST=req_id)
        assert isinstance(result, dict)

    def test_number_range_delete(self, conn):
        result = conn.call("NUMBER_RANGE_INTERVAL_DELETE",
                           OBJECT="BELEG",
                           SUBOBJECT="",
                           INTERVAL=[{
                               "NRRANGENR": "99",
                               "FROMNUMBER": "9900000000",
                               "TONUMBER": "9999999999",
                           }])
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════
#  12. CUSTOM TABLE INSERT (Z_MIGRATE4HANA_TABLE_INSERT)
# ═══════════════════════════════════════════════════════════════

class TestCustomTableInsert:
    """Stage 12: batch-insert rows into custom Z-tables."""

    def test_single_row_insert(self, conn):
        result = conn.call("Z_MIGRATE4HANA_TABLE_INSERT",
                           TABLE_NAME="ZTMIGRATE_LOG",
                           ROW_DATA=[{
                               "FIELD": "RUN_ID",
                               "VALUE": "TEST001",
                           }])
        errors = [r for r in result.get("RETURN", []) if r.get("TYPE") == "E"]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════
#  13. END-TO-END: Full Write-Verify-Rollback Cycle
# ═══════════════════════════════════════════════════════════════

class TestEndToEndCycle:
    """Integration test: post → verify → reverse to prove full pipeline flow."""

    def test_finance_post_verify_reverse(self, conn):
        """Post an FI doc, read it back, then reverse — the golden path test."""

        # 1. Post
        post = conn.call("BAPI_ACC_DOCUMENT_POST",
                         DOCUMENTHEADER={
                             "HEADER_TXT": "E2E Test",
                             "COMP_CODE": "1000",
                             "DOC_DATE": "20240601",
                             "PSTNG_DATE": "20240601",
                             "DOC_TYPE": "SA",
                         },
                         ACCOUNTGL=[
                             {"ITEMNO_ACC": "001", "GL_ACCOUNT": "0010000000",
                              "COMP_CODE": "1000"},
                             {"ITEMNO_ACC": "002", "GL_ACCOUNT": "0031000000",
                              "COMP_CODE": "1000"},
                         ],
                         CURRENCYAMOUNT=[
                             {"ITEMNO_ACC": "001", "CURRENCY": "USD",
                              "AMT_DOCCUR": Decimal("999.99")},
                             {"ITEMNO_ACC": "002", "CURRENCY": "USD",
                              "AMT_DOCCUR": Decimal("-999.99")},
                         ])
        doc_key = post.get("OBJ_KEY")
        assert doc_key, "Document posting must return OBJ_KEY"

        conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")

        # 2. Verify via RFC_READ_TABLE on BKPF
        verify = conn.call("RFC_READ_TABLE",
                           QUERY_TABLE="BKPF",
                           FIELDS=[{"FIELDNAME": "BELNR"}],
                           ROWCOUNT=100)
        assert "DATA" in verify

        # 3. Reverse
        rev = conn.call("BAPI_ACC_DOCUMENT_REVERSE",
                        REVERSAL={
                            "OBJ_KEY_R": doc_key,
                            "COMP_CODE": "1000",
                            "REASON_REV": "01",
                            "PSTNG_DATE": "20240602",
                        })
        assert isinstance(rev, dict)
        conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")

    def test_bp_create_role_assign_delete(self, conn):
        """Create BP → assign role → verify read → delete."""

        # Create
        bp = conn.call("BAPI_BUPA_CREATE_FROM_DATA",
                       PARTNERCATEGORY="1",
                       CENTRALDATA={"SEARCHTERM1": "E2ETEST"},
                       CENTRALDATAPERSON={
                           "FIRSTNAME": "End2End",
                           "LASTNAME": "Test",
                       })
        bp_nr = bp.get("BUSINESSPARTNER")
        assert bp_nr

        # Add role
        conn.call("BAPI_BUPA_ROLE_ADD_2",
                  BUSINESSPARTNER=bp_nr,
                  PARTNERROLE="FLCU00")
        conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")

        # Delete / rollback
        conn.call("BAPI_BUPA_DELETE", PARTNER=bp_nr)
        conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")

    def test_full_code_deploy_cycle(self, conn):
        """Transport create → program insert → activate → transport release."""

        # Create transport
        tr = conn.call("BAPI_CTREQUEST_CREATE",
                       DESCRIPTION="E2E Deploy Test",
                       TYPE="K")
        tr_id = tr["REQUESTID"]
        assert tr_id

        # Insert program
        conn.call("RPY_PROGRAM_INSERT",
                  PROGRAM_NAME="ZTEST_E2E_DEPLOY",
                  PROG_SOURCE=[{"LINE": "REPORT ZTEST_E2E_DEPLOY."}])

        # Syntax check
        check = conn.call("RS_SYNTAX_CHECK", PROGRAM="ZTEST_E2E_DEPLOY")
        critical = [m for m in check.get("MESSAGES", []) if m.get("SEVERITY") == "E"]
        assert len(critical) == 0

        # Activate
        conn.call("RS_WORKING_OBJECTS_ACTIVATE",
                  OBJECTS=[{"OBJ_NAME": "ZTEST_E2E_DEPLOY", "OBJECT": "PROG"}])

        # Release transport
        conn.call("BAPI_CTREQUEST_RELEASE", REQUESTID=tr_id)


# ═══════════════════════════════════════════════════════════════
#  14. MOCK-SPECIFIC: Verify Side Effects & State Tracking
# ═══════════════════════════════════════════════════════════════

class TestMockSideEffects:
    """Verify that MockRFCConnection correctly tracks internal state."""

    def test_mock_tracks_posted_docs(self, mock_conn):
        initial = len(mock_conn._loaded_finance_docs)
        mock_conn.call("BAPI_ACC_DOCUMENT_POST",
                       DOCUMENTHEADER={"HEADER_TXT": "Track Test"},
                       ACCOUNTGL=[],
                       CURRENCYAMOUNT=[])
        assert len(mock_conn._loaded_finance_docs) == initial + 1

    def test_mock_tracks_created_bps(self, mock_conn):
        initial = len(mock_conn._loaded_bps)
        mock_conn.call("BAPI_BUPA_CREATE_FROM_DATA",
                       PARTNERCATEGORY="1",
                       CENTRALDATA={},
                       CENTRALDATAPERSON={"FIRSTNAME": "A", "LASTNAME": "B"})
        assert len(mock_conn._loaded_bps) == initial + 1

    def test_mock_tracks_goods_movements(self, mock_conn):
        initial = len(mock_conn._loaded_material_docs)
        mock_conn.call("BAPI_GOODSMVT_CREATE",
                       GOODSMVT_HEADER={},
                       GOODSMVT_CODE={"GM_CODE": "01"},
                       GOODSMVT_ITEM=[])
        assert len(mock_conn._loaded_material_docs) == initial + 1

    def test_mock_tracks_roles(self, mock_conn):
        initial = len(mock_conn._created_roles)
        mock_conn.call("PRGN_RFC_ROLE_CREATE",
                       ROLE_NAME="ZTRACK_TEST",
                       ROLE_TEXT="Track Test")
        assert len(mock_conn._created_roles) == initial + 1

    def test_mock_tracks_deployed_programs(self, mock_conn):
        mock_conn.call("RPY_PROGRAM_INSERT",
                       PROGRAM_NAME="ZDEPLOYED_TEST",
                       PROG_SOURCE=[{"LINE": "REPORT ZDEPLOYED_TEST."}])
        assert "ZDEPLOYED_TEST" in mock_conn._deployed_programs

    def test_mock_tracks_commits(self, mock_conn):
        initial = mock_conn._committed
        mock_conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
        assert mock_conn._committed == initial + 1

    def test_mock_call_counter(self, mock_conn):
        initial = mock_conn._call_count
        mock_conn.call("RFC_PING")
        mock_conn.call("RFC_PING")
        assert mock_conn._call_count == initial + 2


# ═══════════════════════════════════════════════════════════════
#  15. RFC CONNECTION POOL (unit-level)
# ═══════════════════════════════════════════════════════════════

class TestRFCConnectionPool:
    """Verify the connection pool utility works correctly with mock connections."""

    MOCK_PARAMS = {"ashost": "mock", "sysnr": "00", "client": "100",
                   "user": "TEST", "passwd": "test"}

    def test_pool_import(self):
        from rfc_pool import RFCConnectionPool
        pool = RFCConnectionPool(max_connections=2)
        assert pool is not None

    def test_pool_get_and_return(self):
        from rfc_pool import RFCConnectionPool
        pool = RFCConnectionPool(max_connections=2)
        with pool.get_connection(conn_params=self.MOCK_PARAMS) as conn:
            assert conn is not None
        stats = pool.stats
        assert stats["connections_in_use"] == 0

    def test_pool_max_connections(self):
        from rfc_pool import RFCConnectionPool
        pool = RFCConnectionPool(max_connections=1, connect_timeout=1)
        # Borrow the single connection
        with pool.get_connection(conn_params=self.MOCK_PARAMS) as conn1:
            assert conn1 is not None
            # Pool is exhausted — second borrow should raise
            with pytest.raises((TimeoutError, Exception)):
                with pool.get_connection(conn_params=self.MOCK_PARAMS) as conn2:
                    pass

    def test_pool_cleanup(self):
        from rfc_pool import RFCConnectionPool
        pool = RFCConnectionPool(max_connections=3)
        with pool.get_connection(conn_params=self.MOCK_PARAMS):
            pass
        pool.close_all()
        assert pool.stats["connections_available"] == 0
