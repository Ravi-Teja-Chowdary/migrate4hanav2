"""
visualize_dag.py
----------------
Emit the migrate4hana object DependencyDAG as Graphviz DOT so stakeholders
can review the migration ordering visually.

Usage:
    python scripts/visualize_dag.py                      # default → dag.dot
    python scripts/visualize_dag.py --out my.dot
    python scripts/visualize_dag.py --scope SalesOrder,OpenAR

Render:
    dot -Tsvg dag.dot -o dag.svg
    dot -Tpng dag.dot -o dag.png

Grouping:
    Nodes are coloured by lane (BAPI vs MC-file vs IDoc vs untyped) using a
    curated lane map that mirrors the tracker. This is the "at-a-glance"
    artefact the SAP consultants asked for during the presentation review.
"""
from __future__ import annotations

import argparse
import os
import sys


def _load_dag():
    here = os.path.dirname(os.path.abspath(__file__))
    utils = os.path.abspath(os.path.join(here, "..", "lambda", "utils"))
    sys.path.insert(0, utils)
    from dependency_dag import DependencyDAG  # type: ignore
    return DependencyDAG.from_defaults()


# Curated lane map — matches BREADTH_TRACKER.md
_LANE = {
    # BAPI-lane
    "BusinessPartner":    "bapi",
    "Customer":           "bapi",
    "Vendor":             "bapi",
    "Material":           "bapi",
    "Bank":               "bapi",
    "ExchangeRates":      "bapi",
    "CostCenter":         "bapi",
    "ProfitCenter":       "bapi",
    "InternalOrder":      "bapi",
    "FixedAsset":         "bapi",
    "Equipment":          "bapi",
    "FunctionalLocation": "bapi",
    "Characteristic":     "bapi",
    "Class":              "bapi",
    "Batch":              "bapi",
    "InventoryBalance":   "bapi",
    "OpenAR":             "bapi",
    "OpenAP":             "bapi",
    "OpenPO":             "bapi",
    "PurchaseRequisition": "bapi",
    "PurchaseContract":   "bapi",
    "SalesOrder":         "bapi",
    "Project":            "bapi",
    "CostElementGroup":   "bapi",
    "ProfitCenterGroup":  "bapi",
    "Quotation":          "bapi",
    "Inquiry":            "bapi",
    "SalesContract":      "bapi",
    "OutboundDelivery":   "bapi",
    "GoodsReceipt":       "bapi",
    "IncomingInvoice":    "bapi",
    "AccountingDocument": "bapi",
    # MC-file lane
    "Routing":            "mc",
    "ActivityType":       "mc",
    "StatisticalKeyFigure": "mc",
    "CommitmentItem":     "mc",
    "GLAccount":          "mc",
    "TaskList":           "mc",
    "InspPlan":           "mc",
    "InspMethod":         "mc",
    "ServiceMaster":      "mc",
    "SourceList":         "mc",
    "HouseBank":          "mc",
    "HouseBankAccount":   "mc",
    "ConditionRecord":    "mc",
    "CustomerHierarchy":  "mc",
    "BOMItem":            "mc",
    "Network":            "mc",
    "WBSElement":         "mc",
    "OrgUnit":            "mc",
    "Position":           "mc",
    "EmployeeAction":     "mc",
    "WBS":                "mc",
    "Plant":              "mc",
    # PM / manufacturing extended (BAPI-lane on modern releases)
    "MeasurementPoint":   "bapi",
    "MeasurementDocument": "bapi",
    "MaintenancePlan":    "bapi",
    "MaintenanceItem":    "bapi",
    "Notification":       "bapi",
    "ProductionOrder":    "bapi",
    "ProcessOrder":       "bapi",
    "PlannedOrder":       "bapi",
    # HR — IDoc lane
    "HRMaster":           "idoc",
}


_COLOR = {
    "bapi":  "#3b82f6",   # blue
    "mc":    "#8b5cf6",   # purple
    "idoc":  "#f97316",   # orange
    "other": "#94a3b8",   # slate
}


def emit_dot(dag, scope=None) -> str:
    order = dag.topological_sort(scope=scope) if scope else dag.topological_sort()
    lines = [
        "digraph M4H_DAG {",
        '  rankdir=LR;',
        '  node [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=10];',
        '  edge [color="#94a3b8", arrowsize=0.6];',
    ]
    scope_set = set(order)
    for n in order:
        lane = _LANE.get(n, "other")
        colour = _COLOR[lane]
        text_col = "white" if lane != "other" else "black"
        lines.append(f'  "{n}" [fillcolor="{colour}", fontcolor="{text_col}"];')
    for n in order:
        for d in sorted(dag.edges.get(n, ())):
            if d in scope_set:
                lines.append(f'  "{d}" -> "{n}";')
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dag.dot",
                     help="Output DOT file (default dag.dot)")
    ap.add_argument("--scope", default="",
                     help="Comma-separated scope objects (transitive deps auto-pulled). "
                          "Default = full DAG.")
    args = ap.parse_args()

    dag = _load_dag()
    scope = [s.strip() for s in args.scope.split(",") if s.strip()] or None

    cycles = dag.validate()
    if cycles:
        print(f"[!] DAG has cycles: {cycles}", file=sys.stderr)
        return 2

    dot = emit_dot(dag, scope=scope)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(dot)

    order = dag.topological_sort(scope=scope) if scope else dag.topological_sort()
    print(f"[+] {len(order)} nodes → {args.out}")
    print(f"    Render with:")
    print(f"      dot -Tsvg {args.out} -o {os.path.splitext(args.out)[0]}.svg")
    print(f"      dot -Tpng {args.out} -o {os.path.splitext(args.out)[0]}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
