"""Stage auditor: classify every lambda/* stage REAL / PARTIAL / SCAFFOLD from concrete
code signals, and surface each stage's claimed purpose (module docstring) so claim can be
compared against reality. Heuristic first-pass — drives the targeted deep reads that follow.
"""
import ast, os, re, glob, json

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lambda")

CAP = {  # capability -> regex of "real work" signals
    "SAP_RFC":   r"pyrfc|Connection\(|\.call\(|RFC_READ_TABLE|BAPI_[A-Z]|get_function_description|/IWFND|RFC_FUNCTION",
    "ODATA_HTTP":r"requests\.(get|post|put|patch)|urllib\.request|http[s]?://[^\"' ]+sap|odata|API_[A-Z]",
    "AWS":       r"boto3|put_object|get_object|secretsmanager|invoke\(|lambda_client|stepfunctions",
    "AI_LLM":    r"bedrock|ollama|genai|invoke_model|anthropic|/api/generate|completion|messages\.create",
    "ABAP_ANALYSIS": r"\.abap|\bREPORT\b|\bPERFORM\b|\bFORM\b|SELECT-OPTIONS|\bATC\b|simplif|S4_?HANA_READINESS|SAP_NOTE|RSECNOTE|TADIR|REPOSRC",
    "TRANSPORT": r"R3trans|\btp\b|STMS|tms_|cofiles|/usr/sap/trans|datafile|SCPR|BC[_-]?SET|E070|E071|transport_request",
    "FILES":     r"open\(|json\.dump|csv\.(writer|DictWriter)|\.to_csv|\.write\(|Path\(",
    "SUBPROC":   r"subprocess|os\.system|Popen|check_output",
}
SCAF = {  # scaffold / not-real signals
    "NOT_IMPL":  r"NotImplementedError|raise\s+NotImplemented",
    "TODO":      r"#\s*(TODO|FIXME|XXX|HACK)\b|\bTODO\b|\bFIXME\b",
    "STUB_WORD": r"\b(stub|placeholder|not[_ ]?implemented|coming soon|to be implemented|simulate[d]?|mock(ed)?|dummy|fake|hardcoded|for now)\b",
    "CANNED":    r"return\s*\{[^}]*\"(stub|mock|placeholder|todo|not_implemented|simulated|example)\"",
}

def body_is_trivial(node):
    """function body is only pass / ... / a single bare return / return literal."""
    b = [n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                       and isinstance(n.value.value, str))]  # drop docstring
    if not b:
        return True
    if len(b) == 1:
        n = b[0]
        if isinstance(n, ast.Pass):
            return True
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and n.value.value is Ellipsis:
            return True
        if isinstance(n, ast.Return) and (n.value is None or isinstance(n.value, ast.Constant)):
            return True
    return False

def scan_stage(stage_dir):
    pys = [p for p in glob.glob(os.path.join(stage_dir, "**", "*.py"), recursive=True)
           if "__pycache__" not in p]
    src, loc, defs, classes, trivial, docstring = "", 0, 0, 0, 0, ""
    for p in pys:
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        src += "\n" + text
        loc += sum(1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#"))
        try:
            tree = ast.parse(text)
            if os.path.basename(p) == "handler.py" and not docstring:
                docstring = (ast.get_docstring(tree) or "").strip().split("\n")[0][:140]
            for n in ast.walk(tree):
                if isinstance(n, ast.FunctionDef):
                    defs += 1
                    if body_is_trivial(n):
                        trivial += 1
                elif isinstance(n, ast.ClassDef):
                    classes += 1
        except Exception:
            pass
    caps = {k: len(re.findall(rx, src, re.I)) for k, rx in CAP.items()}
    scafs = {k: len(re.findall(rx, src, re.I)) for k, rx in SCAF.items()}
    cap_cats = sum(1 for v in caps.values() if v > 0)
    scaf_total = scafs["NOT_IMPL"] * 5 + scafs["CANNED"] * 3 + scafs["STUB_WORD"] + scafs["TODO"]
    trivial_ratio = trivial / defs if defs else 1.0
    # classification
    if loc < 50 or (defs and trivial_ratio > 0.6) or scafs["NOT_IMPL"] > 0:
        verdict = "SCAFFOLD"
    elif cap_cats >= 3 and loc >= 150 and scaf_total <= 3 and trivial_ratio < 0.35:
        verdict = "REAL"
    else:
        verdict = "PARTIAL"
    return {"stage": os.path.basename(stage_dir), "files": len(pys), "loc": loc, "defs": defs,
            "classes": classes, "trivial_defs": trivial, "cap_cats": cap_cats,
            "caps": {k: v for k, v in caps.items() if v}, "scaffold_score": scaf_total,
            "scaf": {k: v for k, v in scafs.items() if v}, "verdict": verdict, "claim": docstring}

stages = sorted([d for d in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(d)
                 and os.path.basename(d) not in ("utils", "_deprecated")])
rows = [scan_stage(d) for d in stages]
order = {"REAL": 0, "PARTIAL": 1, "SCAFFOLD": 2}
rows.sort(key=lambda r: (order[r["verdict"]], -r["loc"]))

print("%-32s %-8s %5s %5s %4s %4s  %s" % ("STAGE", "VERDICT", "LOC", "defs", "triv", "cap", "capabilities"))
print("-" * 110)
for r in rows:
    print("%-32s %-8s %5d %5d %4d %4d  %s" % (
        r["stage"], r["verdict"], r["loc"], r["defs"], r["trivial_defs"], r["cap_cats"],
        ",".join(sorted(r["caps"])) or "(none)"))
summary = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("REAL", "PARTIAL", "SCAFFOLD")}
print("\nSUMMARY:", summary, " total stages:", len(rows))
json.dump(rows, open("audit_pipeline_result.json", "w"), indent=2)
print("wrote audit_pipeline_result.json")
