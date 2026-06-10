"""
Migrate4HANA -- PDF Report Generator
=====================================
Generates a professional client-deliverable PDF from the
post-migration report JSON.
"""

import json
import os
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT


# Brand colors
NAVY = colors.HexColor("#0f172a")
BLUE = colors.HexColor("#3b82f6")
CYAN = colors.HexColor("#06b6d4")
GREEN = colors.HexColor("#10b981")
AMBER = colors.HexColor("#f59e0b")
RED = colors.HexColor("#ef4444")
PURPLE = colors.HexColor("#8b5cf6")
GRAY = colors.HexColor("#64748b")
LIGHT_GRAY = colors.HexColor("#f1f5f9")
WHITE = colors.white


# ── Unicode safety net ──────────────────────────────────────────────────────
# ReportLab's default Helvetica is Latin-1 only -- em-dashes, arrows, smart
# quotes, box-drawing chars, accented letters, and other Unicode characters in
# the report JSON render as missing glyphs (the "not a single word
# understandable" symptom). _safe() folds the common problem chars to readable
# ASCII before anything reaches the PDF; _safe_data() walks the JSON recursively.
_UNICODE_FALLBACK = {
    "—": "--",  "–": "-",
    "‘": "'",   "’": "'",
    "“": '"',   "”": '"',
    "•": "*",   "·": "*",
    "…": "...",
    "→": "->",  "←": "<-",
    "↑": "^",   "↓": "v",
    "─": "-",   "━": "-",
    "│": "|",   "┃": "|",
    " ": " ",
    "✅": "[OK]", "✓": "[OK]", "✔": "[OK]",
    "❌": "[X]",  "✗": "[X]",
    "⚠": "[!]",
}


def _safe(s):
    """Return ``s`` with Unicode chars Helvetica cannot render mapped to ASCII.
    Non-string inputs pass through unchanged; any remaining non-Latin-1 char is
    transliterated to '?' so rendering can never fail mid-page."""
    if s is None or not isinstance(s, str) or not s:
        return s
    for bad, good in _UNICODE_FALLBACK.items():
        if bad in s:
            s = s.replace(bad, good)
    try:
        s.encode("latin-1")
        return s
    except UnicodeEncodeError:
        return s.encode("ascii", errors="replace").decode("ascii")


def _safe_data(obj):
    """Recursively walk a JSON-like structure and _safe() every string."""
    if isinstance(obj, str):
        return _safe(obj)
    if isinstance(obj, list):
        return [_safe_data(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _safe_data(v) for k, v in obj.items()}
    return obj


def _styles():
    """Build custom paragraph styles."""
    ss = getSampleStyleSheet()

    ss.add(ParagraphStyle(
        "CoverTitle", parent=ss["Title"],
        fontSize=28, leading=34, textColor=NAVY,
        spaceAfter=6, alignment=TA_LEFT,
    ))
    ss.add(ParagraphStyle(
        "CoverSub", parent=ss["Normal"],
        fontSize=14, leading=18, textColor=GRAY,
        spaceAfter=4,
    ))
    ss.add(ParagraphStyle(
        "SectionH", parent=ss["Heading1"],
        fontSize=16, leading=20, textColor=NAVY,
        spaceBefore=18, spaceAfter=8,
        borderPadding=(0, 0, 4, 0),
    ))
    ss.add(ParagraphStyle(
        "SubH", parent=ss["Heading2"],
        fontSize=12, leading=15, textColor=BLUE,
        spaceBefore=10, spaceAfter=4,
    ))
    ss.add(ParagraphStyle(
        "Body", parent=ss["Normal"],
        fontSize=10, leading=14, textColor=NAVY,
        spaceAfter=4,
    ))
    ss.add(ParagraphStyle(
        "Small", parent=ss["Normal"],
        fontSize=8, leading=10, textColor=GRAY,
    ))
    ss.add(ParagraphStyle(
        "MBullet", parent=ss["Normal"],
        fontSize=10, leading=14, textColor=NAVY,
        leftIndent=18, bulletIndent=6, spaceAfter=2,
    ))
    ss.add(ParagraphStyle(
        "MetricLabel", parent=ss["Normal"],
        fontSize=9, textColor=GRAY, alignment=TA_CENTER,
    ))
    ss.add(ParagraphStyle(
        "MetricValue", parent=ss["Normal"],
        fontSize=18, leading=22, textColor=NAVY,
        alignment=TA_CENTER, fontName="Helvetica-Bold",
    ))
    ss.add(ParagraphStyle(
        "GradeStyle", parent=ss["Normal"],
        fontSize=36, leading=40, textColor=GREEN,
        alignment=TA_CENTER, fontName="Helvetica-Bold",
    ))
    return ss


def _metric_box(label, value, color=NAVY):
    """Create a small metric cell for tables."""
    ss = _styles()
    return [
        Paragraph(f'<font color="{color.hexval()}" size="16"><b>{value}</b></font>', ss["MetricValue"]),
        Paragraph(label, ss["MetricLabel"]),
    ]


def _severity_color(sev):
    return {"HIGH": RED, "MEDIUM": AMBER, "LOW": GREEN}.get(sev, GRAY)


def _table_style_base():
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ])


def generate_pdf(report_data, output_path):
    """
    Generate a professional PDF from a post-migration report dict.

    Args:
        report_data: dict -- the post_migration_report section
        output_path: str -- where to save the PDF
    """
    # Hard-delete stale cache files to prevent reading previous run data
    import os as _os
    _cache_files = ['assessment_summary.json', 'temp_metadata.db']
    _out_dir = _os.path.dirname(output_path) if output_path else '.'
    for _cf in _cache_files:
        for _sd in [_out_dir, '.', 'test-output']:
            _cp = _os.path.join(_sd, _cf)
            if _os.path.exists(_cp):
                try:
                    _os.remove(_cp)
                except OSError:
                    pass

    # Sanitize every string in the report so Helvetica can render it cleanly
    # (em-dashes, arrows, smart quotes, accents, box-drawing in source data
    # would otherwise show as missing-glyph squares).
    report_data = _safe_data(report_data)

    ss = _styles()
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )

    story = []
    page_w = A4[0] - 40 * mm  # usable width

    # --- COVER PAGE ---------------------------------------------
    story.append(Spacer(1, 40 * mm))

    es = report_data.get("executive_summary", {})
    meta = report_data.get("report_metadata", {})

    story.append(Paragraph("Post-Migration Report", ss["CoverTitle"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"SAP ECC -> S/4HANA System Conversion", ss["CoverSub"]
    ))
    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(width="40%", thickness=2, color=BLUE))
    story.append(Spacer(1, 10 * mm))

    cover_data = [
        ["Client", es.get("client", "--")],
        ["Source System", es.get("source_system", "--")],
        ["Target System", es.get("target_system", "--")],
        ["Migration Approach", es.get("migration_approach", "--")],
        ["Status", es.get("overall_status", "--")],
        ["Generated", meta.get("generated", "--")],
        ["Classification", meta.get("classification", "--")],
    ]
    cover_table = Table(cover_data, colWidths=[page_w * 0.35, page_w * 0.65])
    cover_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), GRAY),
        ("TEXTCOLOR", (1, 0), (1, -1), NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, colors.HexColor("#e2e8f0")),
    ]))
    story.append(cover_table)
    story.append(Spacer(1, 20 * mm))

    gls = report_data.get("go_live_scorecard", {})
    grade = gls.get("grade", "--")
    score = gls.get("score", "--")
    rec = es.get("recommendation", "--")

    grade_color = {"A": GREEN, "B": AMBER, "C": colors.HexColor("#f97316"), "D": RED}.get(grade, BLUE)
    story.append(Paragraph(
        f'<font color="{grade_color.hexval()}" size="36"><b>Grade {grade}</b></font>',
        ParagraphStyle("tmp", alignment=TA_CENTER, fontSize=36, leading=42)
    ))
    story.append(Paragraph(
        f'<font color="{GRAY.hexval()}" size="12">{score} -- {rec}</font>',
        ParagraphStyle("tmp2", alignment=TA_CENTER, fontSize=12, leading=16, spaceAfter=4)
    ))

    story.append(PageBreak())

    # --- 1. EXECUTIVE SUMMARY ----------------------------------
    story.append(Paragraph("1. Executive Summary", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=BLUE))
    story.append(Spacer(1, 4 * mm))

    ssa = report_data.get("source_system_assessment", {})
    summary_bullets = [
        f"<b>Client:</b> {es.get('client', '--')}",
        f"<b>Source:</b> {es.get('source_system', '--')} -- {ssa.get('total_custom_programs', 0)} custom programs, "
        f"{ssa.get('total_custom_tables', 0)} tables, {ssa.get('function_modules', 0)} function modules",
        f"<b>Target:</b> {es.get('target_system', '--')}",
        f"<b>Approach:</b> {es.get('migration_approach', '--')}",
        f"<b>Org Scope:</b> {ssa.get('company_codes', 0)} company codes, "
        f"{ssa.get('plants', 0)} plants, {ssa.get('sales_organizations', 0)} sales orgs",
        f"<b>Users:</b> {ssa.get('total_users', 0):,} across {ssa.get('total_roles', 0)} roles",
        f"<b>Blocking Issues:</b> {ssa.get('blocking_issues_identified', 0)} identified and addressed",
    ]
    for b in summary_bullets:
        story.append(Paragraph(f"* {b}", ss["MBullet"]))

    story.append(Spacer(1, 6 * mm))

    # --- 2. CODE REMEDIATION -----------------------------------
    story.append(Paragraph("2. Code Remediation", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=CYAN))
    story.append(Spacer(1, 4 * mm))

    cr = report_data.get("code_remediation", {})
    cr_sum = cr.get("summary", {})

    # Metrics row
    metrics = [
        [str(cr_sum.get("total_issues_detected", 0)), str(cr_sum.get("auto_remediated", 0)),
         str(cr_sum.get("total_fixes_applied", 0)), f"{cr_sum.get('fix_rate_percentage', 0)}%"],
        ["Issues Detected", "Auto-Remediated", "Fixes Applied", "Fix Rate"],
    ]
    mt = Table(metrics, colWidths=[page_w / 4] * 4)
    mt.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 18),
        ("FONTSIZE", (0, 1), (-1, 1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 1), (-1, 1), GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
    ]))
    story.append(mt)
    story.append(Spacer(1, 4 * mm))

    # Fix engine breakdown
    story.append(Paragraph("Fix Engine Breakdown", ss["SubH"]))
    fb = cr.get("fix_breakdown", {})
    if fb:
        fb_data = [["Engine", "Fixes Applied"]]
        for k, v in fb.items():
            fb_data.append([k.replace("_", " ").title(), str(v)])
        fbt = Table(fb_data, colWidths=[page_w * 0.6, page_w * 0.4])
        fbt.setStyle(_table_style_base())
        story.append(fbt)
        story.append(Spacer(1, 4 * mm))

    # Key transformations
    story.append(Paragraph("Key Transformations", ss["SubH"]))
    for t in cr.get("key_transformations", []):
        story.append(Paragraph(f"* {t}", ss["MBullet"]))

    # Manual review
    manual = cr_sum.get("remaining_manual_review", 0)
    if manual > 0:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(f"<b>Manual Review Required:</b> {manual} items", ss["Body"]))
        for item in cr.get("manual_review_items", []):
            story.append(Paragraph(f"  -- {item}", ss["MBullet"]))

    story.append(PageBreak())

    # --- 3. DATA MIGRATION -------------------------------------
    story.append(Paragraph("3. Data Migration", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=GREEN))
    story.append(Spacer(1, 4 * mm))

    dm = report_data.get("data_migration") or {}
    fin = dm.get("finance") or {}
    bp = dm.get("business_partner_conversion") or {}
    ct = dm.get("custom_tables") or {}

    story.append(Paragraph("Financial Data (BKPF/BSEG -> ACDOCA)", ss["SubH"]))
    fin_data = [
        ["Metric", "Value"],
        ["Source Documents (BKPF)", f"{fin.get('source_documents_bkpf', 0):,}"],
        ["Source Line Items (BSEG)", f"{fin.get('source_line_items_bseg', 0):,}"],
        ["Target ACDOCA Records", f"{fin.get('target_acdoca_records', 0):,}"],
        ["Reconciliation", fin.get("reconciliation", "--")],
    ]
    ft = Table(fin_data, colWidths=[page_w * 0.55, page_w * 0.45])
    ft.setStyle(_table_style_base())
    story.append(ft)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Business Partner Conversion (KNA1/LFA1 -> BUT000)", ss["SubH"]))
    bp_data = [
        ["Metric", "Value"],
        ["Customers Migrated", f"{bp.get('customers_migrated', 0):,}"],
        ["Vendors Migrated", f"{bp.get('vendors_migrated', 0):,}"],
        ["Business Partners Created", f"{bp.get('business_partners_created', 0):,}"],
        ["Duplicates Merged", str(bp.get("duplicates_merged", 0))],
        ["CVI Synchronization", bp.get("cvi_synchronization", "--")],
    ]
    bpt = Table(bp_data, colWidths=[page_w * 0.55, page_w * 0.45])
    bpt.setStyle(_table_style_base())
    story.append(bpt)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Custom Tables", ss["SubH"]))
    story.append(Paragraph(
        f"* {ct.get('tables_migrated', 0)} tables migrated, "
        f"{ct.get('total_rows_transferred', 0):,} total rows transferred",
        ss["MBullet"]
    ))

    # ── Dirty-Data Handling — the real "did the spine catch the garbage?" view
    ddh = dm.get("dirty_data_handling") or {}
    if ddh:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph("Dirty-Data Handling (Spine Orchestrators)", ss["SubH"]))
        story.append(Paragraph(
            f"<b>LOAD_TO_S4 path:</b> {'ENABLED' if ddh.get('load_to_s4_enabled') else 'OFF (extract-only)'}",
            ss["Body"]
        ))
        ddh_table = [
            ["Outcome", "Count", "Rate"],
            ["Attempted rows (cap = M4H_LOAD_MAX_ROWS env)", f"{ddh.get('total_attempted', 0):,}", "—"],
            ["Created in S/4 (BAPI succeeded)",              f"{ddh.get('total_created_in_s4', 0):,}", ddh.get('create_rate', 'n/a')],
            ["Matched existing (idempotency / ledger hit)",  f"{ddh.get('total_matched_existing', 0):,}", ddh.get('idempotency_hit_rate', 'n/a')],
            ["Dead-lettered (spine refused row)",            f"{ddh.get('total_dead_lettered', 0):,}", ddh.get('dead_letter_rate', 'n/a')],
        ]
        ddh_tbl = Table(ddh_table, colWidths=[page_w * 0.55, page_w * 0.20, page_w * 0.25])
        ddh_tbl.setStyle(_table_style_base())
        story.append(ddh_tbl)
        story.append(Spacer(1, 3 * mm))

        # Spine orchestrators per object
        sos = ddh.get("spine_orchestrators") or {}
        if sos:
            story.append(Paragraph("Spine Orchestrator Per Object", ss["SubH"]))
            so_table = [["Object", "Spine Used"]]
            for obj, sname in sos.items():
                so_table.append([obj, sname])
            so_tbl = Table(so_table, colWidths=[page_w * 0.30, page_w * 0.70])
            so_tbl.setStyle(_table_style_base())
            story.append(so_tbl)
            story.append(Spacer(1, 3 * mm))

        dlc = ddh.get("dead_letter_classes") or []
        if dlc:
            story.append(Paragraph(
                "<b>Dead-letter classes observed:</b> " + ", ".join(dlc),
                ss["Body"]
            ))
            story.append(Spacer(1, 2 * mm))

        samples_by = ddh.get("sample_outcomes") or {}
        if any(samples_by.values()):
            story.append(Paragraph("Sample Disposition Outcomes (per object)", ss["SubH"]))
            samp_rows = [["Object", "Status", "Disposition", "Source Key", "Target Key"]]
            for obj, samples in samples_by.items():
                for s in (samples or [])[:5]:
                    samp_rows.append([
                        obj,
                        s.get("status", "")[:24],
                        s.get("disposition", "")[:40],
                        str(s.get("source_key", "") or "")[:24],
                        str(s.get("target_key", "") or "")[:24],
                    ])
            if len(samp_rows) > 1:
                samp_tbl = Table(samp_rows, colWidths=[
                    page_w*0.16, page_w*0.18, page_w*0.30, page_w*0.18, page_w*0.18])
                samp_tbl.setStyle(_table_style_base())
                story.append(samp_tbl)

    story.append(Spacer(1, 6 * mm))

    # --- 4. CONFIGURATION --------------------------------------
    story.append(Paragraph("4. Configuration", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=AMBER))
    story.append(Spacer(1, 4 * mm))

    cfg = report_data.get("configuration", {})
    s4cfg = cfg.get("s4_specific_config", {})
    india = cfg.get("india_localization", {})

    story.append(Paragraph(
        f"<b>{cfg.get('checklist_items_applied', 0)}</b> configuration checklist items applied", ss["Body"]
    ))
    story.append(Spacer(1, 2 * mm))

    cfg_data = [
        ["S/4HANA Configuration", "Value"],
        ["Universal Journal Ledgers", str(s4cfg.get("universal_journal_ledgers", 0))],
        ["Number Ranges Created", str(s4cfg.get("number_ranges_created", 0))],
        ["BP Groups", str(s4cfg.get("business_partner_groups", 0))],
        ["Fiori Catalogs", str(s4cfg.get("fiori_catalogs_registered", 0))],
    ]
    ct2 = Table(cfg_data, colWidths=[page_w * 0.55, page_w * 0.45])
    ct2.setStyle(_table_style_base())
    story.append(ct2)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("India Localization", ss["SubH"]))
    india_bullets = [
        f"GST Registrations: {india.get('gst_registrations', 0)}",
        f"TDS Configured: {'Yes' if india.get('tds_configured') else 'No'}",
        f"E-Invoice Configured: {'Yes' if india.get('einvoice_configured') else 'No'}",
    ]
    for b in india_bullets:
        story.append(Paragraph(f"* {b}", ss["MBullet"]))

    story.append(PageBreak())

    # --- 5. ROLES & AUTHORIZATIONS -----------------------------
    story.append(Paragraph("5. Roles & Authorizations", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=PURPLE))
    story.append(Spacer(1, 4 * mm))

    ra = report_data.get("roles_and_authorizations", {})
    role_data = [
        ["Metric", "Value"],
        ["Source PFCG Roles", str(ra.get("source_roles", 0))],
        ["Fiori Apps Mapped", str(ra.get("fiori_apps_mapped", 0))],
        ["Single Roles Created", str(ra.get("single_roles_created", 0))],
        ["Composite Roles Created", str(ra.get("composite_roles_created", 0))],
        ["Users Assigned", str(ra.get("users_assigned", 0))],
    ]
    rt = Table(role_data, colWidths=[page_w * 0.55, page_w * 0.45])
    rt.setStyle(_table_style_base())
    story.append(rt)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Key T-code -> Fiori Mappings", ss["SubH"]))
    for m in ra.get("key_mappings", []):
        story.append(Paragraph(f"* {m}", ss["MBullet"]))

    story.append(Spacer(1, 6 * mm))

    # --- 6. INTEGRATIONS ---------------------------------------
    story.append(Paragraph("6. Integrations", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=RED))
    story.append(Spacer(1, 4 * mm))

    integ = report_data.get("integrations", {})
    integ_data = [
        ["Metric", "Value"],
        ["RFC Destinations Total", str(integ.get("rfc_destinations_total", 0))],
        ["Auto-Migrated", str(integ.get("auto_migrated", 0))],
        ["Manual Review Needed", str(integ.get("manual_review_needed", 0))],
        ["Automation Rate", integ.get("automation_rate", "--")],
    ]
    it = Table(integ_data, colWidths=[page_w * 0.55, page_w * 0.45])
    it.setStyle(_table_style_base())
    story.append(it)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Critical India Integrations", ss["SubH"]))
    for ci in integ.get("critical_integrations", []):
        story.append(Paragraph(f"* {ci}", ss["MBullet"]))

    story.append(PageBreak())

    # --- 7. GO-LIVE SCORECARD ----------------------------------
    story.append(Paragraph("7. GO-LIVE Scorecard", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=GREEN))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph(
        f'<font color="{grade_color.hexval()}" size="24"><b>Grade {grade} -- {score}</b></font>',
        ParagraphStyle("grade_inline", alignment=TA_CENTER, fontSize=24, leading=30, spaceAfter=8)
    ))

    bd = gls.get("breakdown", {})
    if bd:
        sc_data = [["Category", "Checked", "Passed"]]
        for cat, vals in bd.items():
            sc_data.append([
                cat.replace("_", " ").title(),
                str(vals.get("checked", 0)),
                str(vals.get("passed", 0)),
            ])
        sc_data.append(["Total", str(gls.get("total_checks", 0)), str(gls.get("passed", 0))])
        sct = Table(sc_data, colWidths=[page_w * 0.5, page_w * 0.25, page_w * 0.25])
        style = _table_style_base()
        style.add("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")
        style.add("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ecfdf5"))
        sct.setStyle(style)
        story.append(sct)

    story.append(Spacer(1, 6 * mm))

    # --- 8. RISK ASSESSMENT ------------------------------------
    story.append(Paragraph("8. Risk Assessment", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=AMBER))
    story.append(Spacer(1, 4 * mm))

    risk = report_data.get("risk_assessment", {})
    overall = risk.get("overall_risk", "--")
    oc = _severity_color(overall)
    story.append(Paragraph(
        f'Overall Risk: <font color="{oc.hexval()}"><b>{overall}</b></font>', ss["Body"]
    ))
    story.append(Spacer(1, 3 * mm))

    for r in risk.get("risks", []):
        sc = _severity_color(r.get("severity", ""))
        story.append(Paragraph(
            f'<font color="{sc.hexval()}"><b>[{r.get("severity", "")}]</b></font> '
            f'<b>{r.get("area", "")}</b> -- {r.get("description", "")}',
            ss["Body"]
        ))
        story.append(Paragraph(
            f'<i>Mitigation:</i> {r.get("mitigation", "")}', ss["MBullet"]
        ))
        story.append(Spacer(1, 2 * mm))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Recommendations", ss["SubH"]))
    for rec in risk.get("recommendations", []):
        story.append(Paragraph(f"* {rec}", ss["MBullet"]))

    story.append(PageBreak())

    # --- 9. POST GO-LIVE ROADMAP -------------------------------
    story.append(Paragraph("9. Post Go-Live Roadmap", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=PURPLE))
    story.append(Spacer(1, 4 * mm))

    for phase in report_data.get("post_golive_roadmap", []):
        story.append(Paragraph(f'<b>{phase.get("phase", "")}</b>', ss["SubH"]))
        for act in phase.get("activities", []):
            story.append(Paragraph(f"* {act}", ss["MBullet"]))
        story.append(Spacer(1, 3 * mm))

    story.append(Spacer(1, 6 * mm))

    # --- 10. TECHNICAL METRICS ---------------------------------
    story.append(Paragraph("10. Technical Metrics", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=GRAY))
    story.append(Spacer(1, 4 * mm))

    tm = report_data.get("technical_metrics", {})
    tm_data = [
        ["Metric", "Value"],
        ["RFC Calls Executed", f"{tm.get('rfc_calls_executed', 0):,}"],
        ["Pipeline Duration", f"{tm.get('pipeline_duration_seconds', 0)}s"],
        ["Programs Deployed", str(tm.get("programs_deployed", 0))],
        ["Transport Request", tm.get("transport_request", "--")],
    ]
    tmt = Table(tm_data, colWidths=[page_w * 0.55, page_w * 0.45])
    tmt.setStyle(_table_style_base())
    story.append(tmt)

    # --- APPENDIX A: STAGE-BY-STAGE DEEP DIVE -------------------
    # Walks every artifact in stages[] and renders its payload as readable
    # tables. The 34 MB report_input.json holds the full per-stage detail —
    # this section folds it into the PDF so the report is self-contained
    # production-grade evidence rather than a summary brief.
    stages_list = report_data.get("stages", []) or []
    if stages_list:
        story.append(PageBreak())
        story.append(Paragraph("Appendix A — Stage-by-Stage Detail", ss["SectionH"]))
        story.append(HRFlowable(width="100%", thickness=1, color=NAVY))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(
            f"Source: report_input.json ({report_data.get('stage_count', len(stages_list))} artifacts, "
            f"{sum(s.get('size_bytes', 0) for s in stages_list):,} bytes). Each subsection is one "
            f"artifact emitted by the pipeline; the payload is rendered as nested key/value "
            f"tables. Long lists are truncated to the first 25 items with a count footer.",
            ss["Body"]
        ))
        story.append(Spacer(1, 4 * mm))

        # Group by section for readable navigation
        from collections import defaultdict
        by_section = defaultdict(list)
        for s in stages_list:
            by_section[s.get("section", "other")].append(s)

        # Stable, business-meaningful ordering
        section_order = [
            "discovery", "sizing-advisor", "object-router", "target-provisioner",
            "basis-validator", "code-analysis", "transports", "config", "bc-sets",
            "data-migrator", "execution",
        ]
        ordered_sections = [s for s in section_order if s in by_section]
        ordered_sections += [s for s in sorted(by_section.keys()) if s not in section_order]

        for section in ordered_sections:
            artifacts = by_section[section]
            story.append(Paragraph(
                f"A.{ordered_sections.index(section) + 1} {section.replace('-', ' ').title()}",
                ss["SectionH"]
            ))
            story.append(HRFlowable(width="100%", thickness=0.7, color=BLUE))
            story.append(Spacer(1, 2 * mm))
            for a in artifacts:
                story.append(Paragraph(
                    f"<b>{a.get('artifact', '?')}</b> "
                    f"<font color='{GRAY.hexval()}' size='8'>"
                    f"({a.get('size_bytes', 0):,} bytes)</font>",
                    ss["SubH"]
                ))
                _render_payload(story, ss, a.get("payload"), page_w)
                story.append(Spacer(1, 3 * mm))

    # --- FOOTER -------------------------------------------------
    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"Generated by Migrate4HANA v2.0 -- {meta.get('generated', datetime.now().isoformat())}",
        ss["Small"]
    ))
    story.append(Paragraph(meta.get("classification", "CONFIDENTIAL"), ss["Small"]))

    # Build PDF
    doc.build(story)
    return output_path


# ── Appendix renderer helpers ───────────────────────────────────────────────
# These walk a JSON-like payload (dict/list/scalar) and emit ReportLab
# flowables. The PDF generator is pure-Python and stateless so each call gets
# a fresh _styles() inside; depth caps protect against runaway nesting.

_MAX_LIST_ITEMS = 25       # truncate long lists to keep PDF readable
_MAX_DICT_DEPTH = 4        # cap nesting; deeper structures rendered as JSON
_MAX_CELL_CHARS = 220      # truncate single cell values
_MAX_TABLE_ROWS = 60       # cap rows per single payload table


def _truncate(s, limit=_MAX_CELL_CHARS):
    s = "" if s is None else str(s)
    return s if len(s) <= limit else (s[: limit - 3] + "...")


def _format_value(v, depth=0):
    """Convert a leaf value into a render-safe string."""
    if v is None:
        return "--"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return f"{v:,}" if isinstance(v, int) and abs(v) >= 1000 else str(v)
    if isinstance(v, str):
        return _truncate(_safe(v))
    if isinstance(v, list):
        if not v:
            return "(empty)"
        if all(isinstance(x, (str, int, float, bool)) for x in v[:5]):
            preview = ", ".join(_truncate(_safe(str(x)), 60) for x in v[:5])
            return _truncate(f"[{len(v)}] {preview}{'...' if len(v) > 5 else ''}", 220)
        return f"[list × {len(v)}]"
    if isinstance(v, dict):
        return f"{{dict × {len(v)} keys}}"
    return _truncate(_safe(str(v)))


def _render_payload(story, ss, payload, page_w, depth=0):
    """Recursively render a payload — dict → key/value table, list → enumerated
    sub-payloads, scalar → paragraph. Returns nothing; appends to story."""
    if payload is None:
        story.append(Paragraph("(no payload)", ss["Small"]))
        return

    if isinstance(payload, dict):
        if not payload:
            story.append(Paragraph("(empty)", ss["Small"]))
            return
        # split scalar/leaf keys (render in a table) from nested keys (recurse)
        scalar_rows = []
        nested = []
        for k, v in payload.items():
            if isinstance(v, dict) and v:
                nested.append((k, v))
            elif isinstance(v, list) and v and any(isinstance(x, dict) for x in v):
                nested.append((k, v))
            else:
                scalar_rows.append([_safe(str(k)), _format_value(v)])

        if scalar_rows:
            scalar_rows = scalar_rows[:_MAX_TABLE_ROWS]
            tbl = Table([["Field", "Value"]] + scalar_rows,
                        colWidths=[page_w * 0.35, page_w * 0.65])
            tbl.setStyle(_table_style_base())
            story.append(tbl)
            if len(payload) > _MAX_TABLE_ROWS:
                story.append(Paragraph(
                    f"(...{len(payload) - _MAX_TABLE_ROWS} more fields truncated)",
                    ss["Small"]
                ))
            story.append(Spacer(1, 2 * mm))

        if depth >= _MAX_DICT_DEPTH:
            if nested:
                story.append(Paragraph(
                    f"(depth cap reached — {len(nested)} nested key(s) omitted from PDF; "
                    f"see report_input.json for full detail)",
                    ss["Small"]
                ))
            return

        for k, v in nested:
            story.append(Paragraph(
                f"<i>{_safe(str(k))}</i>",
                ParagraphStyle("nestedh", parent=ss["Body"],
                                fontSize=10, textColor=PURPLE,
                                spaceBefore=4, spaceAfter=2)
            ))
            _render_payload(story, ss, v, page_w, depth=depth + 1)
        return

    if isinstance(payload, list):
        if not payload:
            story.append(Paragraph("(empty list)", ss["Small"]))
            return
        # Tabular if all items are dicts with consistent keys
        if all(isinstance(x, dict) for x in payload):
            keys: list = []
            seen = set()
            for row in payload[:5]:
                for k in row.keys():
                    if k not in seen and len(keys) < 6:
                        keys.append(k); seen.add(k)
            data = [[_safe(str(k)) for k in keys]]
            for row in payload[:_MAX_LIST_ITEMS]:
                data.append([_format_value(row.get(k)) for k in keys])
            col_w = page_w / max(len(keys), 1)
            tbl = Table(data, colWidths=[col_w] * len(keys))
            tbl.setStyle(_table_style_base())
            story.append(tbl)
            if len(payload) > _MAX_LIST_ITEMS:
                story.append(Paragraph(
                    f"(...{len(payload) - _MAX_LIST_ITEMS} more rows truncated; "
                    f"total {len(payload):,})",
                    ss["Small"]
                ))
            story.append(Spacer(1, 2 * mm))
            return

        # Otherwise enumerated bullets
        for i, item in enumerate(payload[:_MAX_LIST_ITEMS]):
            story.append(Paragraph(
                f"<b>[{i + 1}]</b> {_format_value(item)}",
                ss["MBullet"]
            ))
        if len(payload) > _MAX_LIST_ITEMS:
            story.append(Paragraph(
                f"(...{len(payload) - _MAX_LIST_ITEMS} more items truncated; total {len(payload):,})",
                ss["Small"]
            ))
        return

    # Scalar
    story.append(Paragraph(_format_value(payload), ss["Body"]))


def generate_pdf_from_file(json_path, output_path=None):
    """Load a JSON report file and generate PDF."""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: {json_path} is not valid JSON: {e}")
        return None

    if output_path is None:
        output_path = json_path.replace(".json", ".pdf")

    return generate_pdf(data, output_path)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        pdf_path = generate_pdf_from_file(sys.argv[1])
        print(f"PDF generated: {pdf_path}")
    else:
        print("Usage: python pdf_report_generator.py <report.json>")
