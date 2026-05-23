"""
Migrate4HANA — Stage 2: Code Analyzer
=======================================
Analyzes custom ABAP code for S/4HANA compatibility.

What this does (in DevOps terms):
Think of it like a linter that checks your code against a "breaking changes" list.
SAP publishes a "Simplification List" with every S/4HANA release — it's basically
a massive changelog of what's removed, changed, or deprecated.

This module:
1. Reads custom ABAP source code from ECC via RFC
2. Parses it for known incompatible patterns
3. Auto-remediates what it can (simple replacements)
4. Flags what needs manual review
5. Generates CDS view suggestions for old dictionary objects
"""

import json
import os
import re
import logging
import boto3
import sys

# Append path to load internal logic modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'utils')))
from abap_ast_engine import process_abap_file
from data_scrubber import mask_payload_for_infosec
from rule_router import get_simplification_rules

from logger import log_stage_event

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
secrets = boto3.client("secretsmanager")

STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")


def get_sap_connection():
    """RFC connection to the SOURCE ECC via Secrets Manager (or local shim).

    Mirrors discovery-engine.get_sap_connection. Reads creds from the secret
    pointed at by ECC_SECRETS_ARN (preferred) or falls back to SECRETS_ARN.
    """
    from pyrfc import Connection
    secret_id = (os.environ.get("ECC_SECRETS_ARN")
                 or os.environ.get("SOURCE_CREDS_ARN")
                 or os.environ.get("SECRETS_ARN"))
    if not secret_id:
        raise RuntimeError("No ECC secrets ARN configured (ECC_SECRETS_ARN / SECRETS_ARN)")
    payload = json.loads(secrets.get_secret_value(SecretId=secret_id)["SecretString"])
    host = payload.get("ashost") or payload.get("host")
    conn = Connection(
        ashost=host,
        sysnr=payload["sysnr"],
        client=payload["client"],
        user=payload["user"],
        passwd=payload["passwd"],
        lang="EN",
    )
    logger.info(f"code-analyzer RFC connection established to {host} client {payload['client']}")
    return conn


# =============================================================================
# SIMPLIFICATION LIST — S/4HANA 2023 FPS02
# =============================================================================
# These are the actual ABAP patterns that break in S/4HANA.
# Each rule has: pattern to find, fix suggestion, auto-fixable flag.

SIMPLIFICATION_RULES = [
    # ── Obsolete ABAP Statements ──
    {
        "id": "ABAP-001",
        "category": "obsolete_statement",
        "pattern": r"\bOCCURS\s+\d+\b",
        "description": "OCCURS is obsolete — use standard internal tables",
        "severity": "high",
        "auto_fix": True,
        "fix_pattern": r"OCCURS\s+\d+",
        "fix_replacement": "INITIAL SIZE 0",
        "s4_note": "Obsolete since ABAP 7.40 — must use TYPE STANDARD TABLE",
    },
    {
        "id": "ABAP-002",
        "category": "obsolete_statement",
        "pattern": r"\bHEADER\s+LINE\b",
        "description": "HEADER LINE tables are obsolete",
        "severity": "high",
        "auto_fix": False,
        "fix_suggestion": "Separate work area from internal table",
        "s4_note": "Must refactor to use explicit work areas",
    },
    {
        "id": "ABAP-003",
        "category": "obsolete_statement",
        "pattern": r"\bMOVE\s+.*\s+TO\s+",
        "description": "MOVE...TO is obsolete — use assignment operator",
        "severity": "medium",
        "auto_fix": True,
        "fix_pattern": r"MOVE\s+(\S+)\s+TO\s+(\S+)",
        "fix_replacement": r"\2 = \1",
        "s4_note": "Replace with '=' operator",
    },
    {
        "id": "ABAP-004",
        "category": "obsolete_statement",
        "pattern": r"\bCOMPUTE\s+",
        "description": "COMPUTE keyword is obsolete",
        "severity": "low",
        "auto_fix": True,
        "fix_pattern": r"COMPUTE\s+",
        "fix_replacement": "",
        "s4_note": "Simply remove the COMPUTE keyword",
    },
    {
        "id": "ABAP-005",
        "category": "obsolete_statement",
        "pattern": r"\bMULTIPLY\s+.*\s+BY\s+",
        "description": "MULTIPLY...BY is obsolete — use * operator",
        "severity": "low",
        "auto_fix": False,
        "fix_suggestion": "Use arithmetic expression: var = var * factor",
    },
    {
        "id": "ABAP-006",
        "category": "obsolete_statement",
        "pattern": r"\bDIVIDE\s+.*\s+BY\s+",
        "description": "DIVIDE...BY is obsolete — use / operator",
        "severity": "low",
        "auto_fix": False,
        "fix_suggestion": "Use arithmetic expression: var = var / divisor",
    },

    # ── Deprecated Table References ──
    {
        "id": "TABLE-001",
        "category": "deprecated_table",
        "pattern": r"\bBSEG\b",
        "description": "BSEG table replaced by ACDOCA (Universal Journal)",
        "severity": "critical",
        "auto_fix": False,
        "fix_suggestion": "Replace SELECT from BSEG with ACDOCA. Use CDS views for reporting.",
        "s4_note": "Finance data model completely restructured in S/4HANA",
    },
    {
        "id": "TABLE-002",
        "category": "deprecated_table",
        "pattern": r"\b(BSID|BSAD|BSIK|BSAK|BSIS|BSAS)\b",
        "description": "Secondary index tables replaced by ACDOCA views",
        "severity": "critical",
        "auto_fix": False,
        "fix_suggestion": "Use ACDOCA with appropriate WHERE conditions instead",
    },
    {
        "id": "TABLE-003",
        "category": "deprecated_table",
        "pattern": r"\b(GLT0|GLPCA)\b",
        "description": "GL totals tables replaced by ACDOCA aggregation",
        "severity": "critical",
        "auto_fix": False,
        "fix_suggestion": "Use ACDOCA aggregate views or CDS views",
    },
    {
        "id": "TABLE-004",
        "category": "deprecated_table",
        "pattern": r"\b(MKPF|MSEG)\b",
        "description": "Material document tables replaced by MATDOC",
        "severity": "critical",
        "auto_fix": False,
        "fix_suggestion": "Replace with MATDOC (single table replaces both)",
    },
    {
        "id": "TABLE-005",
        "category": "deprecated_table",
        "pattern": r"\b(KNA1|KNB1)\b",
        "description": "Customer master replaced by Business Partner (BUT000)",
        "severity": "critical",
        "auto_fix": False,
        "fix_suggestion": "Use Business Partner tables (BUT000, BUT0BK, etc.) via CDS views",
    },
    {
        "id": "TABLE-006",
        "category": "deprecated_table",
        "pattern": r"\b(LFA1|LFB1)\b",
        "description": "Vendor master replaced by Business Partner (BUT000)",
        "severity": "critical",
        "auto_fix": False,
        "fix_suggestion": "Use Business Partner tables via CDS views",
    },

    # ── Obsolete Function Modules ──
    {
        "id": "FM-001",
        "category": "deprecated_function",
        "pattern": r"CALL\s+FUNCTION\s+['\"]REUSE_ALV_GRID_DISPLAY['\"]",
        "description": "Classic ALV replaced by CL_SALV_TABLE in S/4HANA",
        "severity": "medium",
        "auto_fix": False,
        "fix_suggestion": "Migrate to CL_SALV_TABLE or Fiori elements list report",
    },
    {
        "id": "FM-002",
        "category": "deprecated_function",
        "pattern": r"CALL\s+FUNCTION\s+['\"]POPUP_TO_CONFIRM_STEP['\"]",
        "description": "Deprecated popup FM — use POPUP_TO_CONFIRM instead",
        "severity": "low",
        "auto_fix": True,
        "fix_pattern": r"POPUP_TO_CONFIRM_STEP",
        "fix_replacement": "POPUP_TO_CONFIRM",
    },

    # ── SQL Patterns That Need Modernization ──
    {
        "id": "SQL-001",
        "category": "sql_modernization",
        "pattern": r"SELECT\s+.*\s+INTO\s+CORRESPONDING\s+FIELDS\s+OF\s+TABLE",
        "description": "Consider using new Open SQL syntax with inline declarations",
        "severity": "info",
        "auto_fix": False,
        "fix_suggestion": "Use: SELECT ... INTO TABLE @DATA(lt_result)",
    },
    {
        "id": "SQL-002",
        "category": "sql_modernization",
        "pattern": r"SELECT\s+SINGLE\s+\*\s+FROM",
        "description": "SELECT SINGLE * is inefficient — select specific fields",
        "severity": "info",
        "auto_fix": False,
        "fix_suggestion": "Select only needed fields for performance",
    },
]


# =============================================================================
# CODE ANALYZER
# =============================================================================
def analyze_program(program_name, source_code):
    """
    Analyze a single ABAP program against the dynamic simplification rules.
    Returns list of issues found.
    """
    issues = []
    lines = source_code.split("\n")
    
    # 1. Fetch Dynamic Rules via rule_router
    dynamic_rules = get_simplification_rules()

    for rule in dynamic_rules:
        # Fallback mappings for old hardcoded structure
        pattern = rule.get("pattern", rule.get("ecc_pattern"))
        if not pattern:
            continue
            
        for line_num, line in enumerate(lines, 1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("*") or stripped.startswith('"'):
                continue

            if re.search(pattern, line, re.IGNORECASE):
                issue = {
                    "rule_id": rule.get("id", rule.get("rule_id", "UNKNOWN")),
                    "program": program_name,
                    "line": line_num,
                    "line_content": line.strip()[:120],
                    "category": rule.get("category", "syntax"),
                    "description": rule.get("description", ""),
                    "severity": rule.get("severity", "medium"),
                    "auto_fixable": rule.get("auto_fix", True), # Assume AST can fix most
                }
                issues.append(issue)

    return issues


def auto_remediate_with_ast_engine(source_code):
    """
    Apply AST-based structural fixes via the AST Engine.

    The AST engine operates on the *raw* ABAP source so that string literals,
    function-module names, dictionary identifiers, and other syntactically
    significant tokens survive into the on-disk remediated file.

    PII scrubbing is performed ONLY for payloads dispatched to external LLMs
    (see genai_router.route_analysis). It must never run before code is
    persisted to disk — doing so would mask `'LH'`, `APPEND ... TO itab`,
    function-module names, etc. and produce uncompilable output.
    """
    dynamic_rules = get_simplification_rules()
    try:
        result = process_abap_file(source_code, {"rules": dynamic_rules})
        if isinstance(result, dict):
            fixed_ast_code = result.get("transformed_code", source_code)
            engine_changes = result.get("changes", [])
            changes = engine_changes if engine_changes else (
                [{"rule_id": "AST-GEN", "description": "Structurally updated via ABAP AST Engine."}]
                if fixed_ast_code != source_code else []
            )
        else:
            fixed_ast_code = result
            changes = [{"rule_id": "AST-GEN", "description": "Structurally updated via ABAP AST Engine."}]
        return fixed_ast_code, changes
    except Exception as e:
        logger.error(f"AST Remediation failed. {e}")
        return source_code, []


# =============================================================================
# ATC (ABAP Test Cockpit) INTEGRATION
# =============================================================================
# ATC is SAP's official code analysis tool. We integrate with it to provide
# SAP-official validation alongside our AST-based analysis engine.

def run_atc_check(connection, programs):
    """
    Execute SAP-official static analysis (ATC or its ECC predecessors) via RFC.

    Tries the following FM/variant combinations in order until one works:
      1. /SDF/ATC_RUN_API  with variant S4HANA_READINESS_2023  (target S/4 7.55+)
      2. /SDF/ATC_RUN_API  with variant S4HANA_READINESS       (target S/4 7.5x)
      3. /SDF/SCAN_API     with variant DEFAULT                (source ECC 7.40+)
      4. /SDF/SCAN_RUN_PROG (per-program loop)                 (source ECC 7.31+)

    Returns a list of ATC-shaped issue dicts plus a metadata dict on the last
    element describing which backend was used. Caller decides what to do.
    """
    atc_issues = []
    object_set = [{"OBJECT_TYPE": "PROG", "OBJECT_NAME": p} for p in programs[:200]]

    backends = [
        ("/SDF/ATC_RUN_API", {"VARIANT": "S4HANA_READINESS_2023",
                              "OBJECT_SET": object_set, "EXECUTE_CHECKS": "X"}),
        ("/SDF/ATC_RUN_API", {"VARIANT": "S4HANA_READINESS",
                              "OBJECT_SET": object_set, "EXECUTE_CHECKS": "X"}),
        ("/SDF/SCAN_API",    {"VARIANT": "DEFAULT",
                              "OBJECT_SET": object_set}),
    ]

    chosen_backend = None
    last_err = None
    findings = []
    for fm, params in backends:
        try:
            result = connection.call(fm, **params)
            findings = result.get("FINDINGS") or result.get("ET_FINDINGS") or []
            chosen_backend = f"{fm}/{params.get('VARIANT', '')}".rstrip("/")
            logger.info(f"ATC backend '{chosen_backend}' returned {len(findings)} findings")
            break
        except Exception as e:
            last_err = f"{fm}: {type(e).__name__}: {str(e)[:120]}"
            logger.debug(f"ATC backend {fm} unavailable — {last_err}")
            continue

    # Last resort: per-program /SDF/SCAN_RUN_PROG
    if chosen_backend is None:
        try:
            for p in programs[:50]:  # cap to avoid runaway loop
                try:
                    res = connection.call("/SDF/SCAN_RUN_PROG", I_PROGRAM=p)
                    for f in (res.get("ET_RESULT") or []):
                        f["OBJECT_NAME"] = p
                        findings.append(f)
                except Exception:
                    continue
            if findings:
                chosen_backend = "/SDF/SCAN_RUN_PROG"
                logger.info(f"ATC fallback /SDF/SCAN_RUN_PROG returned {len(findings)} findings")
        except Exception as e:
            last_err = f"/SDF/SCAN_RUN_PROG: {e}"

    if chosen_backend is None:
        logger.warning(
            f"ATC integration unavailable on this system — none of the supported "
            f"check FMs are callable. Last error: {last_err}. AST results still valid."
        )
        return []

    for finding in findings:
        atc_issues.append({
            "rule_id": f"ATC-{finding.get('CHECK_ID') or finding.get('CHECK_CATEGORY') or 'UNKNOWN'}",
            "program": finding.get("OBJECT_NAME", ""),
            "line": int(finding.get("LINE") or finding.get("LINE_NUMBER") or 0),
            "line_content": (finding.get("FINDING_TEXT") or finding.get("CHECK_MESSAGE") or "")[:120],
            "category": finding.get("CHECK_CATEGORY", "atc_finding"),
            "description": finding.get("FINDING_TEXT") or finding.get("CHECK_MESSAGE", ""),
            "severity": _map_atc_priority_to_severity(finding.get("PRIORITY") or finding.get("SEVERITY", "3")),
            "auto_fixable": False,
            "source": chosen_backend,
            "atc_message_id": finding.get("MESSAGE_ID", ""),
        })

    logger.info(f"ATC check completed via {chosen_backend}: {len(atc_issues)} findings from {len(programs)} programs")
    return atc_issues


def _map_atc_priority_to_severity(priority):
    """Map ATC priority levels (1-3) to our severity scale."""
    mapping = {
        "1": "critical",
        "2": "high",
        "3": "medium",
    }
    return mapping.get(str(priority), "medium")


def merge_atc_with_ast_results(ast_issues, atc_issues):
    """
    Combine results from both AST and ATC engines, deduplicating overlapping findings.

    AST results take priority for auto-fix capabilities (our engine can auto-remediate).
    ATC results add SAP-official validation and may catch issues our rules don't cover.

    Deduplication key: (program, line_number) — if both engines flag the same line,
    we keep the AST issue (richer metadata + auto-fix) and annotate it with ATC confirmation.
    """
    # Build lookup of AST issues by (program, line)
    ast_lookup = {}
    for issue in ast_issues:
        key = (issue.get("program", ""), issue.get("line", 0))
        ast_lookup[key] = issue

    merged = list(ast_issues)  # Start with all AST issues
    atc_only = []

    for atc_issue in atc_issues:
        key = (atc_issue.get("program", ""), atc_issue.get("line", 0))
        if key in ast_lookup:
            # Both engines found the same issue — annotate AST issue with ATC confirmation
            ast_lookup[key]["atc_confirmed"] = True
            ast_lookup[key]["atc_message_id"] = atc_issue.get("atc_message_id", "")
        else:
            # ATC-only finding — add to merged results
            atc_only.append(atc_issue)

    merged.extend(atc_only)

    logger.info(
        f"Merged results: {len(ast_issues)} AST + {len(atc_issues)} ATC = "
        f"{len(merged)} total ({len(atc_issues) - len(atc_only)} deduplicated)"
    )

    return merged


def generate_atc_quick_fixes(atc_findings):
    """
    Auto-generate Quick Fix suggestions for common ATC errors.

    Maps known ATC check IDs to remediation suggestions that can be
    applied by the AST engine or presented to the developer for manual review.
    """
    quick_fix_map = {
        "OBSOLETE_STATEMENT": {
            "suggestion": "Replace obsolete ABAP statement with modern equivalent",
            "auto_fixable": True,
        },
        "DEPRECATED_TABLE": {
            "suggestion": "Replace deprecated table access with S/4HANA CDS view equivalent",
            "auto_fixable": False,
        },
        "IMPLICIT_DATA": {
            "suggestion": "Use inline declarations: DATA(lv_var) or FIELD-SYMBOL(<fs>)",
            "auto_fixable": True,
        },
        "OBSOLETE_FM": {
            "suggestion": "Replace obsolete function module with successor API",
            "auto_fixable": False,
        },
        "KEY_WORD_USAGE": {
            "suggestion": "Replace obsolete keyword with modern ABAP syntax",
            "auto_fixable": True,
        },
        "SQL_PERFORMANCE": {
            "suggestion": "Optimize SQL for HANA — use JOINs instead of nested SELECTs",
            "auto_fixable": False,
        },
    }

    quick_fixes = []
    for finding in atc_findings:
        check_category = finding.get("category", "").upper()
        check_id = finding.get("rule_id", "").replace("ATC-", "").upper()

        # Match against known quick fix patterns
        fix_info = None
        for pattern_key, fix_template in quick_fix_map.items():
            if pattern_key in check_category or pattern_key in check_id:
                fix_info = fix_template
                break

        if fix_info:
            quick_fixes.append({
                "rule_id": finding.get("rule_id", ""),
                "program": finding.get("program", ""),
                "line": finding.get("line", 0),
                "suggestion": fix_info["suggestion"],
                "auto_fixable": fix_info["auto_fixable"],
                "source": "ATC_QUICK_FIX",
            })

    logger.info(f"Generated {len(quick_fixes)} ATC quick fix suggestions")
    return quick_fixes


def read_abap_source(conn, program_name):
    """
    Read ABAP source code from ECC via RFC.

    Uses RFC_READ_TABLE on REPOSRC (repository source table)
    or the BAPI RPY_PROGRAM_READ.
    """
    try:
        result = conn.call(
            "RPY_PROGRAM_READ",
            PROGRAM_NAME=program_name,
            WITH_LOWERCASE="X",
            WITH_INCLUDELIST="",
            ONLY_SOURCE="X",
        )
        # ECC 7.40 returns the body in SOURCE_EXTENDED; older systems used
        # SOURCE or PROG_SOURCE. Try them in priority order.
        for tbl in ("SOURCE_EXTENDED", "SOURCE", "PROG_SOURCE"):
            rows = result.get(tbl) or []
            if rows:
                return "\n".join(line.get("LINE", "") for line in rows)
        return ""
    except Exception as e:
        logger.warning(f"Could not read source for {program_name}: {e}")
        return None


# =============================================================================
# CDS VIEW GENERATOR
# =============================================================================
def suggest_cds_views(tables):
    """
    For custom tables that reference deprecated SAP tables,
    suggest CDS view replacements.

    CDS (Core Data Services) views are the S/4HANA way of defining
    data models. Think of them like SQL views but with built-in
    annotations for OData, Fiori, and analytics.
    """
    suggestions = []

    # Map old tables to their S/4HANA CDS view equivalents
    cds_replacements = {
        "BSEG": "I_JournalEntry",
        "BKPF": "I_JournalEntry",
        "BSID": "I_JournalEntryItem",
        "BSAD": "I_JournalEntryItem",
        "BSIK": "I_JournalEntryItem",
        "BSAK": "I_JournalEntryItem",
        "GLT0": "I_GLAccountBalanceCube",
        "GLPCA": "I_ProfitCenterBalanceCube",
        "MKPF": "I_MaterialDocumentHeader",
        "MSEG": "I_MaterialDocumentItem",
        "KNA1": "I_Customer",
        "LFA1": "I_Supplier",
        "KNB1": "I_CustomerCompany",
        "LFB1": "I_SupplierCompany",
        "KONV": "I_PricingConditionRecord",
        "EKKO": "I_PurchaseOrderAPI01",
        "EKPO": "I_PurchaseOrderItemAPI01",
        "VBAK": "I_SalesOrder",
        "VBAP": "I_SalesOrderItem",
    }

    for table_ref in tables:
        table_name = table_ref if isinstance(table_ref, str) else table_ref.get("name", "")
        if table_name.upper() in cds_replacements:
            suggestions.append({
                "old_table": table_name.upper(),
                "new_cds_view": cds_replacements[table_name.upper()],
                "action": f"Replace direct table access to {table_name} with CDS view {cds_replacements[table_name.upper()]}",
            })

    return suggestions


# =============================================================================
# MAIN HANDLER
# =============================================================================
def lambda_handler(event, context):
    """
    Main entry point for Code Analyzer.

    Receives discovery results from Stage 1 and analyzes all custom code.
    """
    logger.info(f"Code Analyzer started: {json.dumps(event, default=str)[:500]}")
    log_stage_event("code-analyzer", "Pipeline Start", "IN_PROGRESS", {"stage": 2})
    _stage_start = __import__('time').time()

    run_id = event.get("metadata", {}).get("run_id", "manual-run")
    discovery = event.get("discovery", {})

    # Fallback: if upstream stage didn't pass discovery inline, load it from
    # the staging bucket / local-staging directly. This makes code-analyzer
    # runnable standalone.
    if not discovery:
        try:
            obj = s3.get_object(Bucket=STAGING_BUCKET,
                                Key=f"migrations/{run_id}/discovery/full-scan.json")
            discovery = json.loads(obj["Body"].read())
            logger.info(f"Loaded discovery for {run_id}: {len(discovery.get('programs', []))} programs")
        except Exception as ex:
            logger.warning(f"No discovery payload available — running degraded ({ex})")

    try:
        # Try to establish SAP connection for reading source code
        try:
            conn = get_sap_connection()
            has_rfc = True
        except Exception as ex:
            has_rfc = False
            logger.warning(f"No RFC connection — analyzing based on discovery metadata only ({ex})")

        programs = discovery.get("summary", {}).get("total_programs", 0)
        all_issues = []
        remediated_count = 0
        manual_review_count = 0
        cds_suggestions = []
        # Program cap: env-controlled. 0 = unlimited (safe on ECS Fargate / local
        # mode where there is no 15-min Lambda timeout). Lambda deploys that keep
        # this stage on Lambda should set CODE_ANALYZER_MAX_PROGRAMS to a bounded
        # value (e.g. 200) to stay under the timeout.
        max_programs = int(os.environ.get("CODE_ANALYZER_MAX_PROGRAMS", "0"))
        programs_scanned = 0
        programs_read = 0
        programs_no_source = 0

        if has_rfc and discovery.get("programs"):
            prog_list = discovery["programs"]
            if max_programs > 0:
                prog_list = prog_list[:max_programs]
            programs_scanned = len(prog_list)
            # Remediation scope:
            #   default            -> remediate programs the issue-detector flagged
            #                         (fix what breaks S/4; minimal change)
            #   AST_REMEDIATE_ALL=1 -> run the AST engine on every readable program
            #                         (full modernization; matches standalone scan)
            remediate_all = os.environ.get("AST_REMEDIATE_ALL", "0") == "1"
            logger.info(f"Analyzing {programs_scanned} programs "
                        f"(cap={max_programs or 'none'}, remediate_all={remediate_all})...")
            for idx, prog in enumerate(prog_list, 1):
                source = read_abap_source(conn, prog["name"])
                if source:
                    programs_read += 1
                    issues = analyze_program(prog["name"], source)
                    all_issues.extend(issues)

                    do_ast = remediate_all or any(i["auto_fixable"] for i in issues)
                    fixed = False
                    if do_ast:
                        fixed_source, changes = auto_remediate_with_ast_engine(source)
                        if changes:
                            remediated_count += 1
                            # Save remediated source (sanitize name for namespaced/odd programs)
                            safe_name = re.sub(r"[^A-Za-z0-9_=.\-]", "_", prog["name"])[:120]
                            s3.put_object(
                                Bucket=STAGING_BUCKET,
                                Key=f"migrations/{run_id}/code-analysis/remediated/{safe_name}.abap",
                                Body=fixed_source,
                            )
                            fixed = True
                    if issues and not fixed:
                        manual_review_count += 1
                else:
                    programs_no_source += 1

                if idx % 1000 == 0:
                    logger.info(f"  code-analyzer progress: {idx}/{programs_scanned} "
                                f"read={programs_read} remediated={remediated_count}")
        else:
            # No RFC — generate estimated analysis from discovery stats
            logger.info("Generating estimated code analysis from discovery stats...")
            estimated_issues_rate = 0.15  # ~15% of programs typically have issues
            estimated_critical = int(programs * 0.05)
            estimated_warnings = int(programs * 0.10)

            all_issues = [{
                "rule_id": "ESTIMATE",
                "description": f"Estimated {estimated_critical} critical + {estimated_warnings} warning issues based on {programs} programs",
                "severity": "info",
                "auto_fixable": False,
            }]

        # ── ATC Integration ──
        # After running our AST-based analysis, attempt ATC integration for SAP-official validation
        atc_integration = False
        sap_official_validation = False
        atc_results = []
        atc_quick_fixes = []

        if has_rfc and discovery.get("programs"):
            try:
                _atc_src = discovery["programs"] if max_programs == 0 else discovery["programs"][:max_programs]
                program_names = [prog["name"] for prog in _atc_src]
                atc_results = run_atc_check(conn, program_names)
                if atc_results:
                    atc_integration = True
                    sap_official_validation = True
                    atc_quick_fixes = generate_atc_quick_fixes(atc_results)
                    # Merge ATC results with AST results, deduplicating overlaps
                    all_issues = merge_atc_with_ast_results(all_issues, atc_results)
            except Exception as e:
                logger.warning(f"ATC integration skipped: {e}")

        # Severity summary
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for issue in all_issues:
            sev = issue.get("severity", "medium")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        # CDS view suggestions
        if discovery.get("tables"):
            cds_suggestions = suggest_cds_views(discovery["tables"])

        # Build result
        analysis_result = {
            "total_issues": len(all_issues),
            "severity_breakdown": severity_counts,
            "auto_remediated": remediated_count,
            "manual_review_needed": manual_review_count,
            "cds_suggestions": len(cds_suggestions),
            "issues": all_issues[:500],  # Cap for payload size
            "cds_view_suggestions": cds_suggestions,
            "remediation_rate": (
                f"{(remediated_count / max(manual_review_count + remediated_count, 1)) * 100:.1f}%"
            ),
            "atc_integration": atc_integration,
            "sap_official_validation": sap_official_validation,
            "atc_results": atc_results[:200],  # Cap for payload size
            "atc_quick_fixes": atc_quick_fixes[:200],
            "coverage": {
                "total_custom_programs": programs or programs_scanned,
                "programs_scanned": programs_scanned,
                "programs_with_source": programs_read,
                "programs_no_source": programs_no_source,
                "programs_remediated": remediated_count,
                "cap": max_programs or "unlimited",
                "remediate_all": os.environ.get("AST_REMEDIATE_ALL", "0") == "1",
            },
        }

        # Save to S3
        s3_key = f"migrations/{run_id}/code-analysis/analysis-report.json"
        s3.put_object(
            Bucket=STAGING_BUCKET,
            Key=s3_key,
            Body=json.dumps(analysis_result, indent=2, default=str),
            ContentType="application/json",
        )

        logger.info(
            f"Code analysis complete: {len(all_issues)} issues, {remediated_count} auto-fixed, "
            f"ATC integration={'active' if atc_integration else 'inactive'}"
        )
        log_stage_event("code-analyzer", "Analysis Complete", "SUCCESS", {
            "issues": len(all_issues), "auto_fixed": remediated_count,
            "atc_integration": atc_integration, "atc_findings": len(atc_results),
        }, (__import__('time').time() - _stage_start) * 1000)

        return {
            "status": "success",
            "total_issues": len(all_issues),
            "critical_issues": severity_counts.get("critical", 0),
            "auto_remediated": remediated_count,
            "manual_review": manual_review_count,
            "cds_suggestions": len(cds_suggestions),
            "atc_integration": atc_integration,
            "sap_official_validation": sap_official_validation,
            "atc_findings": len(atc_results),
            "atc_quick_fixes": len(atc_quick_fixes),
            "s3_key": s3_key,
            "run_id": run_id,
        }

    except Exception as e:
        logger.error(f"Code analysis failed: {str(e)}")
        log_stage_event("code-analyzer", "Analysis Failed", "ERROR", str(e))
        raise
