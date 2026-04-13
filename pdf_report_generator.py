"""
Migrate4HANA â€” PDF Report Generator
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
        report_data: dict â€” the post_migration_report section
        output_path: str â€” where to save the PDF
    """
    ss = _styles()
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )

    story = []
    page_w = A4[0] - 40 * mm  # usable width

    # â”€â”€â”€ COVER PAGE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Spacer(1, 40 * mm))

    es = report_data.get("executive_summary", {})
    meta = report_data.get("report_metadata", {})

    story.append(Paragraph("Post-Migration Report", ss["CoverTitle"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"SAP ECC â†’ S/4HANA System Conversion", ss["CoverSub"]
    ))
    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(width="40%", thickness=2, color=BLUE))
    story.append(Spacer(1, 10 * mm))

    cover_data = [
        ["Client", es.get("client", "â€”")],
        ["Source System", es.get("source_system", "â€”")],
        ["Target System", es.get("target_system", "â€”")],
        ["Migration Approach", es.get("migration_approach", "â€”")],
        ["Status", es.get("overall_status", "â€”")],
        ["Generated", meta.get("generated", "â€”")],
        ["Classification", meta.get("classification", "â€”")],
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
    grade = gls.get("grade", "â€”")
    score = gls.get("score", "â€”")
    rec = es.get("recommendation", "â€”")

    grade_color = {"A": GREEN, "B": AMBER, "C": colors.HexColor("#f97316"), "D": RED}.get(grade, BLUE)
    story.append(Paragraph(
        f'<font color="{grade_color.hexval()}" size="36"><b>Grade {grade}</b></font>',
        ParagraphStyle("tmp", alignment=TA_CENTER, fontSize=36, leading=42)
    ))
    story.append(Paragraph(
        f'<font color="{GRAY.hexval()}" size="12">{score} â€” {rec}</font>',
        ParagraphStyle("tmp2", alignment=TA_CENTER, fontSize=12, leading=16, spaceAfter=4)
    ))

    story.append(PageBreak())

    # â”€â”€â”€ 1. EXECUTIVE SUMMARY â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Paragraph("1. Executive Summary", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=BLUE))
    story.append(Spacer(1, 4 * mm))

    ssa = report_data.get("source_system_assessment", {})
    summary_bullets = [
        f"<b>Client:</b> {es.get('client', 'â€”')}",
        f"<b>Source:</b> {es.get('source_system', 'â€”')} â€” {ssa.get('total_custom_programs', 0)} custom programs, "
        f"{ssa.get('total_custom_tables', 0)} tables, {ssa.get('function_modules', 0)} function modules",
        f"<b>Target:</b> {es.get('target_system', 'â€”')}",
        f"<b>Approach:</b> {es.get('migration_approach', 'â€”')}",
        f"<b>Org Scope:</b> {ssa.get('company_codes', 0)} company codes, "
        f"{ssa.get('plants', 0)} plants, {ssa.get('sales_organizations', 0)} sales orgs",
        f"<b>Users:</b> {ssa.get('total_users', 0):,} across {ssa.get('total_roles', 0)} roles",
        f"<b>Blocking Issues:</b> {ssa.get('blocking_issues_identified', 0)} identified and addressed",
    ]
    for b in summary_bullets:
        story.append(Paragraph(f"â€¢ {b}", ss["MBullet"]))

    story.append(Spacer(1, 6 * mm))

    # â”€â”€â”€ 2. CODE REMEDIATION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        story.append(Paragraph(f"â€¢ {t}", ss["MBullet"]))

    # Manual review
    manual = cr_sum.get("remaining_manual_review", 0)
    if manual > 0:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(f"<b>Manual Review Required:</b> {manual} items", ss["Body"]))
        for item in cr.get("manual_review_items", []):
            story.append(Paragraph(f"  â€” {item}", ss["MBullet"]))

    story.append(PageBreak())

    # â”€â”€â”€ 3. DATA MIGRATION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Paragraph("3. Data Migration", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=GREEN))
    story.append(Spacer(1, 4 * mm))

    dm = report_data.get("data_migration") or {}
    fin = dm.get("finance") or {}
    bp = dm.get("business_partner_conversion") or {}
    ct = dm.get("custom_tables") or {}

    story.append(Paragraph("Financial Data (BKPF/BSEG â†’ ACDOCA)", ss["SubH"]))
    fin_data = [
        ["Metric", "Value"],
        ["Source Documents (BKPF)", f"{fin.get('source_documents_bkpf', 0):,}"],
        ["Source Line Items (BSEG)", f"{fin.get('source_line_items_bseg', 0):,}"],
        ["Target ACDOCA Records", f"{fin.get('target_acdoca_records', 0):,}"],
        ["Reconciliation", fin.get("reconciliation", "â€”")],
    ]
    ft = Table(fin_data, colWidths=[page_w * 0.55, page_w * 0.45])
    ft.setStyle(_table_style_base())
    story.append(ft)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Business Partner Conversion (KNA1/LFA1 â†’ BUT000)", ss["SubH"]))
    bp_data = [
        ["Metric", "Value"],
        ["Customers Migrated", f"{bp.get('customers_migrated', 0):,}"],
        ["Vendors Migrated", f"{bp.get('vendors_migrated', 0):,}"],
        ["Business Partners Created", f"{bp.get('business_partners_created', 0):,}"],
        ["Duplicates Merged", str(bp.get("duplicates_merged", 0))],
        ["CVI Synchronization", bp.get("cvi_synchronization", "â€”")],
    ]
    bpt = Table(bp_data, colWidths=[page_w * 0.55, page_w * 0.45])
    bpt.setStyle(_table_style_base())
    story.append(bpt)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Custom Tables", ss["SubH"]))
    story.append(Paragraph(
        f"â€¢ {ct.get('tables_migrated', 0)} tables migrated, "
        f"{ct.get('total_rows_transferred', 0):,} total rows transferred",
        ss["MBullet"]
    ))

    story.append(Spacer(1, 6 * mm))

    # â”€â”€â”€ 4. CONFIGURATION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        story.append(Paragraph(f"â€¢ {b}", ss["MBullet"]))

    story.append(PageBreak())

    # â”€â”€â”€ 5. ROLES & AUTHORIZATIONS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    story.append(Paragraph("Key T-code â†’ Fiori Mappings", ss["SubH"]))
    for m in ra.get("key_mappings", []):
        story.append(Paragraph(f"â€¢ {m}", ss["MBullet"]))

    story.append(Spacer(1, 6 * mm))

    # â”€â”€â”€ 6. INTEGRATIONS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Paragraph("6. Integrations", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=RED))
    story.append(Spacer(1, 4 * mm))

    integ = report_data.get("integrations", {})
    integ_data = [
        ["Metric", "Value"],
        ["RFC Destinations Total", str(integ.get("rfc_destinations_total", 0))],
        ["Auto-Migrated", str(integ.get("auto_migrated", 0))],
        ["Manual Review Needed", str(integ.get("manual_review_needed", 0))],
        ["Automation Rate", integ.get("automation_rate", "â€”")],
    ]
    it = Table(integ_data, colWidths=[page_w * 0.55, page_w * 0.45])
    it.setStyle(_table_style_base())
    story.append(it)
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Critical India Integrations", ss["SubH"]))
    for ci in integ.get("critical_integrations", []):
        story.append(Paragraph(f"â€¢ {ci}", ss["MBullet"]))

    story.append(PageBreak())

    # â”€â”€â”€ 7. GO-LIVE SCORECARD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Paragraph("7. GO-LIVE Scorecard", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=GREEN))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph(
        f'<font color="{grade_color.hexval()}" size="24"><b>Grade {grade} â€” {score}</b></font>',
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

    # â”€â”€â”€ 8. RISK ASSESSMENT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Paragraph("8. Risk Assessment", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=AMBER))
    story.append(Spacer(1, 4 * mm))

    risk = report_data.get("risk_assessment", {})
    overall = risk.get("overall_risk", "â€”")
    oc = _severity_color(overall)
    story.append(Paragraph(
        f'Overall Risk: <font color="{oc.hexval()}"><b>{overall}</b></font>', ss["Body"]
    ))
    story.append(Spacer(1, 3 * mm))

    for r in risk.get("risks", []):
        sc = _severity_color(r.get("severity", ""))
        story.append(Paragraph(
            f'<font color="{sc.hexval()}"><b>[{r.get("severity", "")}]</b></font> '
            f'<b>{r.get("area", "")}</b> â€” {r.get("description", "")}',
            ss["Body"]
        ))
        story.append(Paragraph(
            f'<i>Mitigation:</i> {r.get("mitigation", "")}', ss["MBullet"]
        ))
        story.append(Spacer(1, 2 * mm))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Recommendations", ss["SubH"]))
    for rec in risk.get("recommendations", []):
        story.append(Paragraph(f"â€¢ {rec}", ss["MBullet"]))

    story.append(PageBreak())

    # â”€â”€â”€ 9. POST GO-LIVE ROADMAP â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Paragraph("9. Post Go-Live Roadmap", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=PURPLE))
    story.append(Spacer(1, 4 * mm))

    for phase in report_data.get("post_golive_roadmap", []):
        story.append(Paragraph(f'<b>{phase.get("phase", "")}</b>', ss["SubH"]))
        for act in phase.get("activities", []):
            story.append(Paragraph(f"â€¢ {act}", ss["MBullet"]))
        story.append(Spacer(1, 3 * mm))

    story.append(Spacer(1, 6 * mm))

    # â”€â”€â”€ 10. TECHNICAL METRICS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Paragraph("10. Technical Metrics", ss["SectionH"]))
    story.append(HRFlowable(width="100%", thickness=1, color=GRAY))
    story.append(Spacer(1, 4 * mm))

    tm = report_data.get("technical_metrics", {})
    tm_data = [
        ["Metric", "Value"],
        ["RFC Calls Executed", f"{tm.get('rfc_calls_executed', 0):,}"],
        ["Pipeline Duration", f"{tm.get('pipeline_duration_seconds', 0)}s"],
        ["Programs Deployed", str(tm.get("programs_deployed", 0))],
        ["Transport Request", tm.get("transport_request", "â€”")],
    ]
    tmt = Table(tm_data, colWidths=[page_w * 0.55, page_w * 0.45])
    tmt.setStyle(_table_style_base())
    story.append(tmt)

    # â”€â”€â”€ FOOTER â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    story.append(Spacer(1, 20 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"Generated by Migrate4HANA v2.0 â€” {meta.get('generated', datetime.now().isoformat())}",
        ss["Small"]
    ))
    story.append(Paragraph(meta.get("classification", "CONFIDENTIAL"), ss["Small"]))

    # Build PDF
    doc.build(story)
    return output_path


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
