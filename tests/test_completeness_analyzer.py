"""
Tests for the Migration Completeness Analyzer (Stage 9.5).
"""

import os
import sys
import unittest

# Add paths
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "lambda", "migration-completeness-analyzer"))

from handler import analyze_completion, WEIGHTS


def _make_pipeline_results(
    total_issues=216, auto_remediated=213, manual_review=3, fix_rate=98.6,
    programs_fixed=50, total_fixes=500, critical=110,
    customers=3500, vendors=1500, bp_created=4850, duplicates=150,
    crosswalk=5000, finance_docs=5000, finance_lines=25000,
    custom_tables=94, custom_rows=500000,
    checklist_items=9, total_roles=342, fiori_mapped=0,
    total_programs=861, total_tables=94, total_fms=389,
    company_codes=4, plants=12, sales_orgs=8, total_users=1847,
    rfc_destinations=67, idoc_partners=20,
    rfc_total=67, automated=45,
):
    """Build a pipeline_results dict for testing."""
    return {
        "discovery": {
            "status": "success",
            "summary": {
                "total_programs": total_programs,
                "total_tables": total_tables,
                "total_function_modules": total_fms,
                "company_codes": company_codes,
                "plants": plants,
                "sales_orgs": sales_orgs,
                "total_roles": total_roles,
                "total_users": total_users,
                "rfc_destinations": rfc_destinations,
                "idoc_partners": idoc_partners,
            },
        },
        "code_analysis": {
            "status": "success",
            "total_issues": total_issues,
            "auto_remediated": auto_remediated,
            "manual_review": manual_review,
            "fix_rate": fix_rate,
            "programs_fixed": programs_fixed,
            "total_fixes_applied": total_fixes,
            "critical_issues": critical,
        },
        "data_hygiene": {
            "status": "success",
            "results": {
                "customers": customers,
                "vendors": vendors,
                "bp_created": bp_created,
                "duplicates_merged": duplicates,
                "crosswalk_entries": crosswalk,
                "finance_docs": finance_docs,
                "finance_lines": finance_lines,
                "custom_tables": custom_tables,
                "custom_table_rows": custom_rows,
            },
        },
        "data_assessment": {
            "status": "success",
            "finance_docs": finance_docs,
            "finance_lines": finance_lines,
        },
        "config_assessment": {
            "status": "success",
            "checklist_items": checklist_items,
            "total_roles": total_roles,
            "fiori_mapped": fiori_mapped,
            "rfc_total": rfc_total,
            "automated": automated,
        },
        "cutover": {
            "status": "success",
            "go_no_go": "GO",
        },
        "maintenance_planner": {"status": "success"},
        "readiness_check": {"status": "success"},
        "simplification_check": {"status": "success"},
    }


class TestCompletenessAnalyzer(unittest.TestCase):
    """Tests for analyze_completion function."""

    def test_weights_sum_to_100(self):
        """Verify dimension weights sum to 100%."""
        self.assertEqual(sum(WEIGHTS.values()), 100)

    def test_perfect_score(self):
        """Perfect mock data should score ~98-100%."""
        results = _make_pipeline_results(
            total_issues=200, auto_remediated=200, manual_review=0,
            fix_rate=100.0, critical=0,
            checklist_items=50, fiori_mapped=342,
        )
        report = analyze_completion(results)
        self.assertGreaterEqual(report["overall_score"], 98)
        self.assertEqual(report["readiness"], "READY")

    def test_typical_score(self):
        """Typical mock data should score ~75-85%."""
        results = _make_pipeline_results(
            total_issues=216, auto_remediated=150, manual_review=66,
            fix_rate=69.4, critical=50,
            checklist_items=9, fiori_mapped=0,
        )
        report = analyze_completion(results)
        self.assertGreaterEqual(report["overall_score"], 75)
        self.assertLessEqual(report["overall_score"], 85)

    def test_degraded_score(self):
        """High manual review count should degrade the score below 60%."""
        results = _make_pipeline_results(
            total_issues=200, auto_remediated=40, manual_review=160,
            fix_rate=20.0, critical=150,
            checklist_items=5, fiori_mapped=0,
            finance_docs=0, finance_lines=0,
        )
        report = analyze_completion(results)
        self.assertLess(report["overall_score"], 60)

    def test_effort_estimation(self):
        """Verify person-hours calculation for remaining work."""
        results = _make_pipeline_results(manual_review=5)
        report = analyze_completion(results)
        remaining = report["remaining_effort"]
        # 5 programs * 8 hours each = 40 hours minimum
        self.assertGreaterEqual(remaining["total_manual_hours"], 40)

    def test_dimensions_present(self):
        """All 6 dimensions should be present in output."""
        results = _make_pipeline_results()
        report = analyze_completion(results)
        expected_dims = {
            "code_remediation", "data_transformation",
            "config_transformation", "role_authorization",
            "integration_migration", "test_readiness",
        }
        self.assertEqual(set(report["dimensions"].keys()), expected_dims)

    def test_each_dimension_has_score(self):
        """Each dimension should have a score between 0 and 100."""
        results = _make_pipeline_results()
        report = analyze_completion(results)
        for dim_name, dim_data in report["dimensions"].items():
            self.assertIn("score", dim_data, f"Missing score in {dim_name}")
            self.assertGreaterEqual(dim_data["score"], 0, f"Score below 0 in {dim_name}")
            self.assertLessEqual(dim_data["score"], 100, f"Score above 100 in {dim_name}")

    def test_pipeline_stages_counted(self):
        """Should count completed stages."""
        results = _make_pipeline_results()
        report = analyze_completion(results)
        self.assertGreaterEqual(report["pipeline_stages_completed"], 8)

    def test_empty_results(self):
        """Should handle empty pipeline results gracefully."""
        report = analyze_completion({})
        self.assertIn("overall_score", report)
        self.assertIn("dimensions", report)

    def test_readiness_levels(self):
        """Test different readiness levels."""
        # READY — need high scores across all dimensions
        results = _make_pipeline_results(
            total_issues=100, auto_remediated=100, manual_review=0, fix_rate=100.0,
            checklist_items=50, fiori_mapped=342,
        )
        report = analyze_completion(results)
        self.assertEqual(report["readiness"], "READY")

    def test_handler_entry_point(self):
        """Test the Lambda handler entry point."""
        from handler import handler
        event = {"pipeline_results": _make_pipeline_results()}
        response = handler(event)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("overall_score", response["body"])


if __name__ == "__main__":
    unittest.main()
