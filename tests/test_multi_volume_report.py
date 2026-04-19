"""
Tests for the Multi-Volume PDF Report Generator (Stage 9.6).
"""

import os
import sys
import shutil
import tempfile
import unittest
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)
sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "migration-completeness-analyzer"))

from multi_volume_report_generator import (
    generate_multi_volume_report,
    _build_cover_page,
    _split_story_into_volumes,
    _make_table,
    _estimate_pages,
    _PageCountCanvas,
    _make_canvas_class,
    CodeBlockFlowable,
    DonutGaugeFlowable,
    SpiderChartFlowable,
    NAVY, BLUE, SUCCESS,
    STYLES,
)


def _make_full_pipeline_results():
    """Build comprehensive pipeline results for testing."""
    return {
        "discovery": {
            "status": "success",
            "summary": {
                "total_programs": 861,
                "total_tables": 94,
                "total_function_modules": 389,
                "company_codes": 4,
                "plants": 12,
                "sales_orgs": 8,
                "total_roles": 342,
                "total_users": 1847,
                "rfc_destinations": 67,
                "idoc_partners": 20,
            },
        },
        "code_analysis": {
            "status": "success",
            "total_issues": 216,
            "auto_remediated": 213,
            "manual_review": 3,
            "fix_rate": 98.6,
            "critical_issues": 110,
            "programs_fixed": 50,
            "total_fixes_applied": 500,
            "fixes_by_level": {
                "DEEP_knowledge": 180,
                "L1_table_field": 120,
                "L2_structure": 150,
                "L2B_aggressive": 50,
            },
        },
        "data_hygiene": {
            "status": "success",
            "results": {
                "customers": 3500,
                "vendors": 1500,
                "bp_created": 4850,
                "duplicates_merged": 150,
                "crosswalk_entries": 5000,
                "cross_entity_matches": 45,
                "number_range_overlaps": 23,
                "vendors_remapped": 23,
                "finance_docs": 5000,
                "finance_lines": 25000,
                "custom_tables": 94,
                "custom_table_rows": 500000,
            },
            "crosswalk": [
                {"source_id": f"C{i:04d}", "s4_bp_id": f"BP{i:06d}",
                 "source_type": "CUSTOMER", "id_action": "DIRECT"}
                for i in range(1, 16)
            ],
        },
        "data_assessment": {
            "status": "success",
            "finance_docs": 5000,
            "finance_lines": 25000,
        },
        "config_assessment": {
            "status": "success",
            "checklist_items": 9,
            "total_roles": 342,
            "fiori_mapped": 0,
            "rfc_total": 67,
            "automated": 45,
        },
        "maintenance_planner": {
            "status": "success",
            "conversion_path": "SUM/DMO Brownfield",
            "target_release": "S/4HANA 2023 FPS02",
            "prereqs_passed": 5,
            "prereqs_total": 5,
        },
        "readiness_check": {
            "status": "success",
            "readiness_score_pct": 88.9,
            "total_checks": 9,
            "passed_checks": 8,
            "compatible_business_functions": 5,
            "total_business_functions": 6,
        },
        "simplification_check": {
            "status": "success",
            "total_items": 8,
            "critical_items": 3,
            "programs_affected": 120,
        },
        "cutover": {"status": "success", "go_no_go": "GO"},
        "completion_report": {
            "overall_score": 98.6,
            "readiness": "READY",
            "readiness_statement": "This migration package is ready for deployment.",
            "dimensions": {
                "code_remediation": {"score": 99.0, "manual_effort_hours": 24},
                "data_transformation": {"score": 97.0, "manual_effort_hours": 0},
                "config_transformation": {"score": 98.0, "manual_effort_hours": 0},
                "role_authorization": {"score": 96.0, "manual_effort_hours": 0},
                "integration_migration": {"score": 99.0, "manual_effort_hours": 0},
                "test_readiness": {"score": 98.0, "manual_effort_hours": 0},
            },
            "remaining_effort": {
                "total_manual_hours": 24,
                "breakdown": {
                    "code_remediation": {
                        "hours": 24,
                        "description": "3 programs require manual ABAP remediation",
                    }
                },
            },
        },
    }


def _make_minimal_pipeline_results():
    """Build minimal pipeline results (should fit in <50 pages)."""
    return {
        "discovery": {"status": "success", "summary": {
            "total_programs": 10, "total_tables": 5, "total_function_modules": 20,
            "company_codes": 1, "plants": 1, "sales_orgs": 1,
            "total_roles": 5, "total_users": 50, "rfc_destinations": 3, "idoc_partners": 2,
        }},
        "code_analysis": {
            "status": "success", "total_issues": 5, "auto_remediated": 5,
            "manual_review": 0, "fix_rate": 100.0, "critical_issues": 2,
            "programs_fixed": 3, "total_fixes_applied": 10,
            "fixes_by_level": {"DEEP_knowledge": 5, "L1_table_field": 3, "L2_structure": 2},
        },
        "data_hygiene": {"status": "success", "results": {
            "customers": 100, "vendors": 50, "bp_created": 145,
            "duplicates_merged": 5, "crosswalk_entries": 150,
            "cross_entity_matches": 2, "number_range_overlaps": 1,
            "vendors_remapped": 1, "finance_docs": 500, "finance_lines": 2500,
            "custom_tables": 5, "custom_table_rows": 10000,
        }, "crosswalk": []},
        "data_assessment": {"status": "success", "finance_docs": 500, "finance_lines": 2500},
        "config_assessment": {
            "status": "success", "checklist_items": 5,
            "total_roles": 5, "fiori_mapped": 0, "rfc_total": 3, "automated": 2,
        },
        "maintenance_planner": {"status": "success", "conversion_path": "SUM/DMO", "target_release": "S/4HANA 2023", "prereqs_passed": 5, "prereqs_total": 5},
        "readiness_check": {"status": "success", "readiness_score_pct": 100, "total_checks": 5, "passed_checks": 5, "compatible_business_functions": 4, "total_business_functions": 4},
        "simplification_check": {"status": "success", "total_items": 3, "critical_items": 1, "programs_affected": 5},
        "cutover": {"status": "success", "go_no_go": "GO"},
        "completion_report": {
            "overall_score": 99.0, "readiness": "READY",
            "readiness_statement": "Ready for deployment.",
            "dimensions": {
                "code_remediation": {"score": 100, "manual_effort_hours": 0},
                "data_transformation": {"score": 100, "manual_effort_hours": 0},
                "config_transformation": {"score": 95, "manual_effort_hours": 0},
                "role_authorization": {"score": 95, "manual_effort_hours": 0},
                "integration_migration": {"score": 100, "manual_effort_hours": 0},
                "test_readiness": {"score": 95, "manual_effort_hours": 0},
            },
            "remaining_effort": {"total_manual_hours": 0, "breakdown": {}},
        },
    }


class TestMultiVolumeReportGeneration(unittest.TestCase):
    """Tests for generate_multi_volume_report."""

    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix="m4h_test_")

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_single_volume_minimal(self):
        """Minimal data should generate a single volume."""
        results = _make_minimal_pipeline_results()
        files = generate_multi_volume_report(
            results, self.output_dir, "Test Company", max_pages_per_volume=200
        )
        self.assertEqual(len(files), 1)
        self.assertTrue(os.path.isfile(files[0]))
        self.assertGreater(os.path.getsize(files[0]), 0)

    def test_full_report_generates(self):
        """Full pipeline data should generate at least 1 volume."""
        results = _make_full_pipeline_results()
        files = generate_multi_volume_report(
            results, self.output_dir, "Bharat Industrial Solutions Pvt Ltd"
        )
        self.assertGreaterEqual(len(files), 1)
        for f in files:
            self.assertTrue(os.path.isfile(f))
            self.assertGreater(os.path.getsize(f), 0)

    def test_file_naming_convention(self):
        """Verify PDF file naming follows the expected pattern."""
        results = _make_minimal_pipeline_results()
        files = generate_multi_volume_report(
            results, self.output_dir, "Test Co", max_pages_per_volume=200
        )
        fname = os.path.basename(files[0])
        self.assertTrue(fname.startswith("Migrate4HANA_Migration_Report_"))
        self.assertIn("Test_Co", fname)
        self.assertIn("_Vol1_of_", fname)
        self.assertTrue(fname.endswith(".pdf"))

    def test_volume_splitting_small_max(self):
        """With a very small max_pages, should generate multiple volumes."""
        results = _make_full_pipeline_results()
        files = generate_multi_volume_report(
            results, self.output_dir, "Test Co", max_pages_per_volume=5
        )
        self.assertGreater(len(files), 1)

    def test_output_directory_created(self):
        """Output directory should be created if it doesn't exist."""
        nested_dir = os.path.join(self.output_dir, "sub", "dir")
        results = _make_minimal_pipeline_results()
        files = generate_multi_volume_report(
            results, nested_dir, "Test Co", max_pages_per_volume=200
        )
        self.assertTrue(os.path.isdir(nested_dir))
        self.assertGreaterEqual(len(files), 1)

    def test_handles_empty_data(self):
        """Should handle empty/missing pipeline data gracefully."""
        results = {
            "discovery": {"status": "success", "summary": {}},
            "code_analysis": {"status": "success"},
            "data_hygiene": {"status": "success", "results": {}},
            "data_assessment": {"status": "success"},
            "config_assessment": {"status": "success"},
            "completion_report": {
                "overall_score": 0, "readiness": "NOT_READY",
                "readiness_statement": "Insufficient data.",
                "dimensions": {}, "remaining_effort": {"total_manual_hours": 0, "breakdown": {}},
            },
        }
        files = generate_multi_volume_report(
            results, self.output_dir, "Empty Co", max_pages_per_volume=200
        )
        self.assertGreaterEqual(len(files), 1)
        self.assertTrue(os.path.isfile(files[0]))


class TestCodeBlockFlowable(unittest.TestCase):
    """Test the CodeBlockFlowable custom flowable."""

    def test_wrap_returns_dimensions(self):
        cb = CodeBlockFlowable("DATA lv_test TYPE string.", (1, 0.95, 0.95), (0.9, 0, 0))
        w, h = cb.wrap(500, 500)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_multiline_code(self):
        code = "LINE 1\nLINE 2\nLINE 3\nLINE 4"
        cb = CodeBlockFlowable(code, (1, 0.95, 0.95), (0.9, 0, 0))
        w, h = cb.wrap(500, 500)
        self.assertGreater(h, 20)

    def test_courier_font_used(self):
        """Verify CodeBlockFlowable renders with Courier font."""
        import io
        from reportlab.platypus import SimpleDocTemplate, Spacer
        from reportlab.lib.pagesizes import A4

        cb = CodeBlockFlowable("DATA lv_test TYPE string.", (1, 0.95, 0.95), (0.9, 0, 0))
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        doc.build([Spacer(1, 20), cb, Spacer(1, 20)])
        pdf_bytes = buf.getvalue()
        # Courier font must appear in the PDF output
        self.assertIn(b"Courier", pdf_bytes)


class TestDonutGaugeFlowable(unittest.TestCase):
    """Test the DonutGaugeFlowable."""

    def test_wrap(self):
        gauge = DonutGaugeFlowable(95.5)
        w, h = gauge.wrap(500, 500)
        self.assertEqual(w, 200)
        self.assertEqual(h, 200)


class TestSpiderChartFlowable(unittest.TestCase):
    """Test the SpiderChartFlowable."""

    def test_wrap(self):
        dims = [("Code", 99), ("Data", 97), ("Config", 98),
                ("Roles", 96), ("Integration", 99), ("Tests", 98)]
        spider = SpiderChartFlowable(dims)
        w, h = spider.wrap(500, 500)
        self.assertEqual(w, 280)
        self.assertEqual(h, 280)


class TestTableHelper(unittest.TestCase):
    """Test _make_table helper."""

    def test_creates_table(self):
        t = _make_table(["A", "B"], [["1", "2"], ["3", "4"]])
        self.assertIsNotNone(t)

    def test_custom_widths(self):
        t = _make_table(["A", "B"], [["1", "2"]], col_widths=[100, 200])
        self.assertIsNotNone(t)


class TestCoverPage(unittest.TestCase):
    """Test cover page generation."""

    def test_cover_page_elements(self):
        story = _build_cover_page("Test Company", "2026-04-05", 1, 3)
        self.assertGreater(len(story), 0)

    def test_cover_page_contains_volume_info(self):
        """Cover page should contain volume number, company name, and date."""
        from reportlab.platypus import Paragraph
        story = _build_cover_page("Acme Corp", "2026-06-15", 2, 5)
        # Collect all text content from Paragraph elements
        texts = []
        for el in story:
            if isinstance(el, Paragraph):
                texts.append(el.text)
        combined = " ".join(texts)
        self.assertIn("Volume 2 of 5", combined)
        self.assertIn("Acme Corp", combined)
        self.assertIn("2026-06-15", combined)


class TestVolumeSplitting(unittest.TestCase):
    """Test the volume splitting logic."""

    def test_empty_sections(self):
        volumes = _split_story_into_volumes([])
        self.assertEqual(len(volumes), 1)

    def test_single_small_section(self):
        from reportlab.platypus import Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        ss = getSampleStyleSheet()
        elements = [Paragraph("Hello", ss["Normal"])]
        volumes = _split_story_into_volumes([("S1", elements)], max_pages=50)
        self.assertEqual(len(volumes), 1)

    def test_continued_headers_in_split(self):
        """When a section is split across volumes, continuation headers should appear."""
        from reportlab.platypus import Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        ss = getSampleStyleSheet()
        # Create a large section using many text elements (avoids PageBreak edge cases)
        large_elements = []
        for i in range(500):
            large_elements.append(Paragraph(f"Content line {i} " * 20, ss["Normal"]))
        sections = [("Section 3: Code Remediation", large_elements)]
        volumes = _split_story_into_volumes(sections, max_pages=5)
        # Should have multiple volumes
        self.assertGreater(len(volumes), 1)
        # Second volume onward should have "(continued)" in section name
        found_continued = False
        for vol in volumes[1:]:
            for section_name, _ in vol:
                if "(continued)" in section_name:
                    found_continued = True
                    break
        self.assertTrue(found_continued, "Expected '(continued)' in section names after split")


class TestPageNumberFormat(unittest.TestCase):
    """Test that page numbering uses 'Page X of Y — Volume N of M' format."""

    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix="m4h_page_test_")

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_page_numbering_format(self):
        """PDF should contain 'Page X of Y' page numbering format."""
        import io
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.pagesizes import A4

        ss = getSampleStyleSheet()
        cls = _make_canvas_class(1, 1)
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, pageCompression=0)
        story = [Paragraph("Test Content", ss["Normal"]), Spacer(1, 100)]
        doc.build(story, canvasmaker=cls)
        pdf_bytes = buf.getvalue()
        # Verify "Page X of Y" format appears in uncompressed PDF
        self.assertIn(b"Page 1 of 1", pdf_bytes)
        self.assertIn(b"Volume 1 of 1", pdf_bytes)

    def test_canvas_class_factory(self):
        """_make_canvas_class should produce canvas with correct volume info."""
        cls = _make_canvas_class(2, 4)
        self.assertEqual(cls._vol_num, 2)
        self.assertEqual(cls._tot_vols, 4)
        self.assertTrue(issubclass(cls, _PageCountCanvas))


if __name__ == "__main__":
    unittest.main()
