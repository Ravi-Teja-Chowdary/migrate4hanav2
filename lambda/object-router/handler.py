"""
object-router — Phase 0, Stage 3
=================================
Emits a Directed Acyclic Graph of migration objects with lane routing,
dependencies, preconditions, reconciliation method, delta strategy and
manual-gate flag. Step Functions consumes this DAG topologically.
"""
import json
import logging
import os
import sys
import boto3
from collections import defaultdict, deque

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "utils")))
from logger import log_stage_event  # type: ignore

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
STAGING_BUCKET = os.environ.get("S3_STAGING_BUCKET", "migrate4hana-staging-dev")

DEFAULT_ROUTES = {
    "CompanyCode":       {"lane": "BC_SET",  "depends_on": []},
    "ChartOfAccounts":   {"lane": "BC_SET",  "depends_on": []},
    "ControllingArea":   {"lane": "BC_SET",  "depends_on": ["CompanyCode"]},
    "Plant":             {"lane": "BC_SET",  "depends_on": ["CompanyCode"]},
    "GLAccount":         {"lane": "MC",      "depends_on": ["ChartOfAccounts"]},
    "CostCenter":        {"lane": "MC",      "depends_on": ["ControllingArea"]},
    "ProfitCenter":      {"lane": "MC",      "depends_on": ["ControllingArea"]},
    "BPGrouping":        {"lane": "BC_SET",  "depends_on": []},
    "BusinessPartner":   {"lane": "MC",      "depends_on": ["BPGrouping", "CompanyCode"],
                          "reconciliation": "count + KNA1 sum", "delta_strategy": "by KNA1.ERDAT"},
    "Customer":          {"lane": "MC",      "depends_on": ["BusinessPartner"]},
    "Vendor":            {"lane": "MC",      "depends_on": ["BusinessPartner"]},
    "Material":          {"lane": "MC",      "depends_on": ["Plant"], "delta_strategy": "by MARA.ERSDA"},
    "BOM":               {"lane": "MC",      "depends_on": ["Material"]},
    "Routing":           {"lane": "MC",      "depends_on": ["Material"]},
    "WorkCenter":        {"lane": "MC",      "depends_on": ["Plant"]},
    "OpenPO":            {"lane": "MC",      "depends_on": ["Vendor", "Material"], "delta_strategy": "by EKKO.AEDAT"},
    "OpenSO":            {"lane": "MC",      "depends_on": ["Customer", "Material"]},
    "OpenAR":            {"lane": "MC",      "depends_on": ["Customer", "GLAccount"]},
    "OpenAP":            {"lane": "MC",      "depends_on": ["Vendor", "GLAccount"]},
    "GLBalances":        {"lane": "MC",      "depends_on": ["GLAccount", "CostCenter"], "manual_gate": True},
    "InventoryBalances": {"lane": "MC",      "depends_on": ["Material", "Plant"], "manual_gate": True},
    "AssetMaster":       {"lane": "MC",      "depends_on": ["GLAccount"]},
    "NumberRanges":      {"lane": "manual",  "depends_on": [], "manual_gate": True,
                          "note": "Preserve legacy via SNRO transport — Basis owns"},
    "PFCGRoles":         {"lane": "CTSplus", "depends_on": [],
                          "note": "PFCG transport; user assignments → CSV for security team"},
    "BankStatements":    {"lane": "IDoc",    "depends_on": ["GLAccount"]},
    "ExchangeRates":     {"lane": "IDoc",    "depends_on": []},
    "BatchJobs":         {"lane": "CTSplus", "depends_on": []},
    "SmartForms":        {"lane": "CTSplus", "depends_on": []},
    "CustomZTable":      {"lane": "LTMOM",   "depends_on": [], "manual_gate": True},
    "CustomCode":        {"lane": "abapGit", "depends_on": []},
    "RFCDestinations":   {"lane": "CTSplus", "depends_on": [], "note": "SM59 customizing transport"},
    "PartnerProfiles":   {"lane": "CTSplus", "depends_on": ["RFCDestinations"]},
}


def lambda_handler(event, context):
    run_id = event.get("run_id", "local")
    discovered = event.get("discovered_objects") or list(DEFAULT_ROUTES.keys())
    overrides = event.get("routing_overrides", {})

    log_stage_event(run_id, "object-router", "started", {"object_count": len(discovered)})

    nodes = []
    for obj in discovered:
        base = DEFAULT_ROUTES.get(obj, {"lane": "manual", "depends_on": [], "manual_gate": True,
                                       "note": "Unknown object — Basis must classify"})
        merged = {**base, **overrides.get(obj, {}), "object": obj}
        merged.setdefault("preconditions", [])
        merged.setdefault("reconciliation", "count")
        merged.setdefault("delta_strategy", "full-reload")
        merged.setdefault("manual_gate", False)
        nodes.append(merged)

    order = _topo_sort(nodes)
    dag = {"nodes": nodes, "execution_order": order, "lanes": _summarise_lanes(nodes)}
    s3.put_object(Bucket=STAGING_BUCKET,
                  Key=f"runs/{run_id}/object-router/dag.json",
                  Body=json.dumps(dag, default=str).encode())

    log_stage_event(run_id, "object-router", "completed",
                    {"nodes": len(nodes), "lanes": dag["lanes"]})
    return {"status": "success", "node_count": len(nodes),
            "execution_order": order, "lanes": dag["lanes"]}


def _topo_sort(nodes):
    indeg = defaultdict(int)
    edges = defaultdict(list)
    names = {n["object"] for n in nodes}
    for n in nodes:
        for dep in n.get("depends_on", []):
            if dep in names:
                edges[dep].append(n["object"])
                indeg[n["object"]] += 1
    queue = deque(n["object"] for n in nodes if indeg[n["object"]] == 0)
    out = []
    while queue:
        x = queue.popleft()
        out.append(x)
        for y in edges[x]:
            indeg[y] -= 1
            if indeg[y] == 0:
                queue.append(y)
    if len(out) != len(nodes):
        remaining = [n["object"] for n in nodes if n["object"] not in out]
        logger.warning("DAG cycle detected; remaining: %s", remaining)
        out += remaining
    return out


def _summarise_lanes(nodes):
    counts = defaultdict(int)
    for n in nodes:
        counts[n["lane"]] += 1
    return dict(counts)
