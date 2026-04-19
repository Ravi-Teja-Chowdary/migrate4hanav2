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
import sys

# Append path to load internal logic modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'utils')))
from abap_ast_engine import process_abap_file
from data_scrubber import mask_payload_for_infosec
from rule_router import get_simplification_rules
from genai_router import route_analysis

from logger import log_stage_event
from storage_client import put_object

logger = logging.getLogger()
logger.setLevel(logging.INFO)

STAGING_CONTAINER = os.environ.get("AZURE_STORAGE_CONTAINER", "staging")


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
    Apply AST-based structural fixes directly via the new Engine.
    Also incorporates PII Scrubber prior to AST serialization.
    """
    
    # 1. InfoSec Scrubber
    scrubbed_code = mask_payload_for_infosec(source_code)
    
    # 2. Fetch AST mapping logic
    dynamic_rules = get_simplification_rules()
    
    # 3. Process Code Structurally
    try:
        fixed_ast_code = process_abap_file(scrubbed_code, {"rules": dynamic_rules})
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
    Execute ATC (ABAP Test Cockpit) check via RFC call to /SDF/ATC_RUN_API
    with the S/4HANA readiness check variant.

    ATC is SAP's built-in static analysis tool. Running it via RFC gives us
    SAP-official findings that complement our AST engine's pattern matching.

    Returns list of ATC findings in the same issue format as the AST analyzer.
    """
    atc_issues = []
    try:
        # Prepare the object set for ATC — list of programs to check
        object_set = [{"OBJECT_TYPE": "PROG", "OBJECT_NAME": p} for p in programs[:200]]

        result = connection.call("/SDF/ATC_RUN_API", **{
            "VARIANT": "S4HANA_READINESS",  # S/4HANA readiness check variant
            "OBJECT_SET": object_set,
            "EXECUTE_CHECKS": "X",
        })

        findings = result.get("FINDINGS", [])
        for finding in findings:
            atc_issues.append({
                "rule_id": f"ATC-{finding.get('CHECK_ID', 'UNKNOWN')}",
                "program": finding.get("OBJECT_NAME", ""),
                "line": int(finding.get("LINE", 0)),
                "line_content": finding.get("FINDING_TEXT", "")[:120],
                "category": finding.get("CHECK_CATEGORY", "atc_finding"),
                "description": finding.get("FINDING_TEXT", ""),
                "severity": _map_atc_priority_to_severity(finding.get("PRIORITY", "3")),
                "auto_fixable": False,
                "source": "ATC",
                "atc_message_id": finding.get("MESSAGE_ID", ""),
            })

        logger.info(f"ATC check completed: {len(atc_issues)} findings from {len(programs)} programs")

    except Exception as e:
        logger.warning(f"ATC integration failed (non-fatal, AST results still valid): {e}")

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
        )
        # Source lines are in the PROG_SOURCE table
        source_lines = [line.get("LINE", "") for line in result.get("PROG_SOURCE", [])]
        return "\n".join(source_lines)
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
def main(event, context):
    """
    Main entry point for Code Analyzer.

    Receives discovery results from Stage 1 and analyzes all custom code.
    """
    logger.info(f"Code Analyzer started: {json.dumps(event, default=str)[:500]}")
    log_stage_event("code-analyzer", "Pipeline Start", "IN_PROGRESS", {"stage": 2})
    _stage_start = __import__('time').time()

    run_id = event.get("metadata", {}).get("run_id", "manual-run")
    discovery = event.get("discovery", {})

    try:
        # Try to establish SAP connection for reading source code
        try:
            from pyrfc import Connection
            from handler import get_sap_connection  # noqa
            conn = get_sap_connection()
            has_rfc = True
        except (ImportError, Exception):
            has_rfc = False
            logger.warning("No RFC connection — analyzing based on discovery metadata only")

        programs = discovery.get("summary", {}).get("total_programs", 0)
        all_issues = []
        remediated_count = 0
        manual_review_count = 0
        cds_suggestions = []
        genai_enhanced_count = 0

        if has_rfc and discovery.get("programs"):
            # Full analysis — read and analyze each program
            for prog in discovery["programs"][:200]:  # Limit for Lambda timeout
                source = read_abap_source(conn, prog["name"])
                if source:
                    issues = analyze_program(prog["name"], source)
                    all_issues.extend(issues)

                    # Attempt auto-remediation via AST
                    if any(i["auto_fixable"] for i in issues):
                        fixed_source, changes = auto_remediate_with_ast_engine(source)
                        if changes:
                            remediated_count += 1
                            # Save remediated source to storage
                            put_object(
                                STAGING_CONTAINER,
                                f"migrations/{run_id}/code-analysis/remediated/{prog['name']}.abap",
                                fixed_source,
                                content_type="text/plain",
                            )
                    else:
                        if issues:
                            manual_review_count += 1

                    # Escalate to GenAI for deeper semantic analysis
                    try:
                        genai_result = route_analysis(source, context={"program": prog["name"]})
                        if genai_result.get("genai_result"):
                            genai_enhanced_count += 1
                            genai_issues = genai_result["genai_result"].get("issues", [])
                            for gi in genai_issues:
                                gi["source"] = genai_result["backend_used"]
                            all_issues.extend(genai_issues)
                    except Exception as e:
                        logger.warning(f"GenAI routing skipped for {prog['name']}: {e}")
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
                program_names = [prog["name"] for prog in discovery["programs"][:200]]
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
        }

        # Save to storage
        s3_key = f"migrations/{run_id}/code-analysis/analysis-report.json"
        put_object(
            STAGING_CONTAINER,
            s3_key,
            json.dumps(analysis_result, indent=2, default=str),
            content_type="application/json",
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
            "genai_enhanced": genai_enhanced_count,
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
