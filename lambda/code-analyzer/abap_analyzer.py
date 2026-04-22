"""
Migrate4HANA — Enhanced ABAP Code Analyzer
============================================
Analyzes ABAP source code against 100 simplification rules.
Produces detailed reports with effort estimates and auto-fixes.

Usage:
    from abap_analyzer import ABAPAnalyzer
    analyzer = ABAPAnalyzer()
    report = analyzer.analyze_program("ZPROGRAM", source_code)
    fixed_code = analyzer.auto_remediate("ZPROGRAM", source_code)
"""

import re
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
from datetime import datetime


@dataclass
class CodeIssue:
    """A single issue found in ABAP source code."""
    rule_id: str
    program: str
    line: int
    column: int
    line_content: str
    category: str
    description: str
    severity: str
    auto_fixable: bool
    fix_suggestion: Optional[str] = None
    suggested_fix_line: Optional[str] = None
    effort_hours: float = 0.5
    s4_note: Optional[str] = None
    tags: list = field(default_factory=list)


@dataclass
class AnalysisReport:
    """Complete analysis report for one or more ABAP programs."""
    timestamp: str
    programs_analyzed: int
    total_lines: int
    total_issues: int
    severity_breakdown: Dict[str, int]
    category_breakdown: Dict[str, int]
    auto_fixable_count: int
    manual_review_count: int
    total_effort_hours: float
    effort_by_category: Dict[str, float]
    issues: List[CodeIssue]
    top_impacted_programs: List[Dict]
    remediation_summary: Dict
    team_sizing: Optional[Dict] = None
    timeline: Optional[Dict] = None


class ABAPAnalyzer:
    """
    Main ABAP code analysis engine.

    Analyzes ABAP source code against the S/4HANA simplification list
    and produces detailed migration readiness reports.
    """

    # Severity multipliers for effort estimation:
    # base 0.5h x severity multiplier
    SEVERITY_MULTIPLIERS = {
        "critical": 2.0,
        "high": 1.5,
        "medium": 1.25,
        "low": 1.0,
    }
    EFFORT_BASE_HOURS = 0.5

    def __init__(self):
        # Import rules
        from simplification_rules import get_all_rules, get_auto_fixable_rules
        self.rules = get_all_rules()
        self.auto_fix_rules = get_auto_fixable_rules()

        # Compile regex patterns for performance
        self._compiled = {}
        for rule in self.rules:
            try:
                self._compiled[rule.id] = re.compile(rule.pattern, re.IGNORECASE)
            except re.error:
                print(f"Warning: Invalid regex in rule {rule.id}: {rule.pattern}")

    @classmethod
    def _calculate_effort(cls, severity: str) -> float:
        """Calculate effort hours as base 0.5h x severity multiplier."""
        multiplier = cls.SEVERITY_MULTIPLIERS.get(severity.lower(), 1.0)
        return cls.EFFORT_BASE_HOURS * multiplier

    def analyze_program(self, program_name: str, source_code: str) -> List[CodeIssue]:
        """
        Analyze a single ABAP program against all rules.
        Returns list of issues found.
        """
        issues = []
        lines = source_code.split("\n")

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()

            # Skip comment lines
            if stripped.startswith("*") or stripped.startswith('"'):
                continue

            # Skip empty lines
            if not stripped:
                continue

            for rule in self.rules:
                compiled = self._compiled.get(rule.id)
                if not compiled:
                    continue

                match = compiled.search(line)
                if match:
                    # Calculate effort as base 0.5h x severity multiplier
                    # (overrides static per-rule effort_hours)
                    calculated_effort = self._calculate_effort(rule.severity)

                    issue = CodeIssue(
                        rule_id=rule.id,
                        program=program_name,
                        line=line_num,
                        column=match.start() + 1,
                        line_content=stripped[:120],
                        category=rule.category,
                        description=rule.description,
                        severity=rule.severity,
                        auto_fixable=rule.auto_fix,
                        fix_suggestion=rule.fix_suggestion,
                        effort_hours=calculated_effort,
                        s4_note=rule.s4_note,
                        tags=rule.tags,
                    )

                    # Generate suggested fix line if auto-fixable
                    if rule.auto_fix and rule.fix_pattern and rule.fix_replacement is not None:
                        try:
                            fixed_line = re.sub(
                                rule.fix_pattern, rule.fix_replacement,
                                stripped, flags=re.IGNORECASE
                            )
                            if fixed_line != stripped:
                                issue.suggested_fix_line = fixed_line
                        except re.error:
                            pass

                    issues.append(issue)

        return issues

    def auto_remediate(self, program_name: str, source_code: str) -> Tuple[str, List[Dict]]:
        """
        Apply all auto-fix rules to the source code.
        Returns (fixed_source_code, list_of_changes_made).
        """
        fixed = source_code
        changes = []
        lines = fixed.split("\n")
        new_lines = []

        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            original = line

            # Skip comments
            if stripped.startswith("*") or stripped.startswith('"'):
                new_lines.append(line)
                continue

            modified = False
            for rule in self.auto_fix_rules:
                if not rule.fix_pattern or rule.fix_replacement is None:
                    continue

                compiled = self._compiled.get(rule.id)
                if not compiled or not compiled.search(line):
                    continue

                try:
                    new_line = re.sub(
                        rule.fix_pattern, rule.fix_replacement,
                        line, flags=re.IGNORECASE
                    )
                    if new_line != line:
                        changes.append({
                            "rule_id": rule.id,
                            "line": line_num,
                            "description": rule.description,
                            "original": line.rstrip(),
                            "fixed": new_line.rstrip(),
                        })
                        line = new_line
                        modified = True
                except re.error:
                    pass

            new_lines.append(line)

        fixed_source = "\n".join(new_lines)
        return fixed_source, changes

    def analyze_multiple(self, programs: Dict[str, str]) -> AnalysisReport:
        """
        Analyze multiple programs and produce a consolidated report.

        Args:
            programs: Dict of {program_name: source_code}

        Returns:
            AnalysisReport with complete analysis
        """
        all_issues = []
        total_lines = 0
        program_stats = {}

        for prog_name, source_code in programs.items():
            issues = self.analyze_program(prog_name, source_code)
            all_issues.extend(issues)
            total_lines += len(source_code.split("\n"))

            program_stats[prog_name] = {
                "name": prog_name,
                "lines": len(source_code.split("\n")),
                "issues": len(issues),
                "critical": len([i for i in issues if i.severity == "critical"]),
                "effort_hours": sum(i.effort_hours for i in issues),
            }

        # Severity breakdown
        severity_breakdown = {}
        for issue in all_issues:
            severity_breakdown[issue.severity] = severity_breakdown.get(issue.severity, 0) + 1

        # Category breakdown
        category_breakdown = {}
        for issue in all_issues:
            category_breakdown[issue.category] = category_breakdown.get(issue.category, 0) + 1

        # Effort by category
        effort_by_category = {}
        for issue in all_issues:
            effort_by_category[issue.category] = (
                effort_by_category.get(issue.category, 0) + issue.effort_hours
            )

        auto_fixable = [i for i in all_issues if i.auto_fixable]
        manual_review = [i for i in all_issues if not i.auto_fixable]

        # Top impacted programs
        top_programs = sorted(
            program_stats.values(),
            key=lambda x: (x["critical"], x["issues"]),
            reverse=True,
        )[:20]

        # Remediation summary
        total_manual_hours = sum(i.effort_hours for i in manual_review)
        estimated_team_size = max(1, int(total_manual_hours / 160))
        estimated_weeks = max(
            1, int(total_manual_hours / (40 * estimated_team_size))
        )

        remediation = {
            "auto_fix_count": len(auto_fixable),
            "auto_fix_effort_saved_hours": sum(i.effort_hours for i in auto_fixable),
            "manual_count": len(manual_review),
            "manual_effort_hours": total_manual_hours,
            "estimated_team_size": estimated_team_size,
            "estimated_weeks": estimated_weeks,
        }

        # Auto-generated team sizing
        team_sizing = {
            "recommended_developers": estimated_team_size,
            "senior_developers": max(1, estimated_team_size // 3),
            "junior_developers": max(0, estimated_team_size - max(1, estimated_team_size // 3)),
            "total_manual_effort_hours": total_manual_hours,
            "hours_per_developer_per_week": 40,
            "utilization_factor": 0.8,
            "effective_hours_per_dev_per_week": 32,
        }

        # Auto-generated timeline estimation
        effective_weekly_capacity = team_sizing["effective_hours_per_dev_per_week"] * estimated_team_size
        timeline_weeks = max(1, int(total_manual_hours / effective_weekly_capacity)) if effective_weekly_capacity > 0 else 1

        timeline = {
            "estimated_weeks": timeline_weeks,
            "estimated_months": round(timeline_weeks / 4.33, 1),
            "phases": [
                {"phase": "Critical issues remediation", "weeks": max(1, int(timeline_weeks * 0.4))},
                {"phase": "High severity remediation", "weeks": max(1, int(timeline_weeks * 0.3))},
                {"phase": "Medium/Low severity remediation", "weeks": max(1, int(timeline_weeks * 0.2))},
                {"phase": "Validation and testing", "weeks": max(1, int(timeline_weeks * 0.1))},
            ],
            "auto_fix_time_saved_hours": sum(i.effort_hours for i in auto_fixable),
        }

        return AnalysisReport(
            timestamp=datetime.now().isoformat(),
            programs_analyzed=len(programs),
            total_lines=total_lines,
            total_issues=len(all_issues),
            severity_breakdown=severity_breakdown,
            category_breakdown=category_breakdown,
            auto_fixable_count=len(auto_fixable),
            manual_review_count=len(manual_review),
            total_effort_hours=sum(i.effort_hours for i in all_issues),
            effort_by_category=effort_by_category,
            issues=all_issues,
            top_impacted_programs=top_programs,
            remediation_summary=remediation,
            team_sizing=team_sizing,
            timeline=timeline,
        )

    def print_report(self, report: AnalysisReport):
        """Print a formatted analysis report to the console."""
        print(f"\n{'=' * 70}")
        print(f"  MIGRATE4HANA — ABAP Code Analysis Report")
        print(f"  {report.timestamp}")
        print(f"{'=' * 70}\n")

        print(f"  Programs Analyzed:  {report.programs_analyzed}")
        print(f"  Total Lines:        {report.total_lines:,}")
        print(f"  Total Issues:       {report.total_issues}")
        print(f"  Auto-fixable:       {report.auto_fixable_count}")
        print(f"  Manual Review:      {report.manual_review_count}")

        print(f"\n  Severity Breakdown:")
        severity_order = ["critical", "high", "medium", "low", "info"]
        for sev in severity_order:
            count = report.severity_breakdown.get(sev, 0)
            bar = "█" * min(count, 40)
            indicator = "🔴" if sev == "critical" else "🟠" if sev == "high" else "🟡" if sev == "medium" else "🔵" if sev == "low" else "⚪"
            print(f"    {indicator} {sev.upper():10s} {count:4d}  {bar}")

        print(f"\n  Category Breakdown:")
        for cat, count in sorted(report.category_breakdown.items(), key=lambda x: -x[1]):
            bar = "▓" * min(count, 40)
            print(f"    {cat:25s} {count:4d}  {bar}")

        print(f"\n  Effort Estimate (base 0.5h x severity multiplier):")
        print(f"    Total effort:           {report.total_effort_hours:.0f} hours")
        print(f"    Auto-fix saves:         {report.remediation_summary['auto_fix_effort_saved_hours']:.0f} hours")
        print(f"    Manual effort:          {report.remediation_summary['manual_effort_hours']:.0f} hours")
        print(f"    Recommended team size:  {report.remediation_summary['estimated_team_size']} developers")
        print(f"    Estimated duration:     {report.remediation_summary['estimated_weeks']} weeks")

        if report.team_sizing:
            print(f"\n  Team Sizing:")
            print(f"    Senior developers:      {report.team_sizing['senior_developers']}")
            print(f"    Junior developers:      {report.team_sizing['junior_developers']}")
            print(f"    Utilization factor:     {report.team_sizing['utilization_factor']:.0%}")

        if report.timeline:
            print(f"\n  Timeline:")
            print(f"    Estimated duration:     {report.timeline['estimated_weeks']} weeks ({report.timeline['estimated_months']} months)")
            for phase in report.timeline.get("phases", []):
                print(f"      - {phase['phase']:40s} {phase['weeks']} weeks")

        if report.top_impacted_programs:
            print(f"\n  Top Impacted Programs:")
            for prog in report.top_impacted_programs[:10]:
                print(f"    {prog['name']:40s} {prog['issues']:3d} issues ({prog['critical']} critical, {prog['effort_hours']:.1f}h)")

        print(f"\n{'=' * 70}\n")

    def export_report_json(self, report: AnalysisReport, filepath: str):
        """Export analysis report to JSON file."""
        data = {
            "timestamp": report.timestamp,
            "programs_analyzed": report.programs_analyzed,
            "total_lines": report.total_lines,
            "total_issues": report.total_issues,
            "severity_breakdown": report.severity_breakdown,
            "category_breakdown": report.category_breakdown,
            "auto_fixable_count": report.auto_fixable_count,
            "manual_review_count": report.manual_review_count,
            "total_effort_hours": report.total_effort_hours,
            "effort_by_category": report.effort_by_category,
            "remediation_summary": report.remediation_summary,
            "team_sizing": report.team_sizing,
            "timeline": report.timeline,
            "top_impacted_programs": report.top_impacted_programs,
            "issues": [asdict(i) for i in report.issues],
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

        print(f"Report exported to: {filepath}")


# =============================================================================
# CLI ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    import sys
    import os

    # CLI demo: supply an ABAP source file as the first argument.
    # Example:
    #   py -3.10 abap_analyzer.py path/to/program.abap
    #
    # Mock-ECC based demo has been removed — this runner now requires either
    # an explicit source file or a live RFC extract.
    if len(sys.argv) < 2:
        print("Usage: python abap_analyzer.py <abap_source_file>")
        print("  Mock-ECC demo mode has been removed. Provide a real ABAP source file,")
        print("  or drive the analyzer from run_local_pipeline.py (live RFC).")
        sys.exit(1)

    src_file = sys.argv[1]
    if not os.path.isfile(src_file):
        print(f"File not found: {src_file}")
        sys.exit(1)

    with open(src_file, "r", encoding="utf-8", errors="replace") as _f:
        source = _f.read()

    prog_name = os.path.splitext(os.path.basename(src_file))[0].upper()
    programs = {prog_name: source}

    print("\nInitializing ABAP Analyzer with 100 rules...")
    analyzer = ABAPAnalyzer()

    print(f"Analyzing {len(programs)} program(s)...\n")

    report = analyzer.analyze_multiple(programs)
    analyzer.print_report(report)

    # Show auto-remediation on first program
    if programs:
        first_prog = list(programs.keys())[0]
        print(f"\n{'=' * 70}")
        print(f"  AUTO-REMEDIATION DEMO: {first_prog}")
        print(f"{'=' * 70}\n")

        fixed_code, changes = analyzer.auto_remediate(first_prog, programs[first_prog])

        if changes:
            for change in changes:
                print(f"  Rule {change['rule_id']} (line {change['line']}):")
                print(f"    BEFORE: {change['original']}")
                print(f"    AFTER:  {change['fixed']}")
                print()

            print(f"  Total auto-fixes applied: {len(changes)}")
        else:
            print("  No auto-fixes applicable to this program.")

    # Export report
    output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "test-output")
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "code-analysis-report.json")
    analyzer.export_report_json(report, report_path)
