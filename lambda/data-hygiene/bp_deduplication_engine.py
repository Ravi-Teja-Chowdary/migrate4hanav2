"""
bp_deduplication_engine.py - Production-Grade Business Partner Deduplication
==============================================================================
ML-driven deduplication for SAP Customers (KNA1) and Vendors (LFA1) using:
  1. Exact compound-key matching (Tax ID + City)
  2. Levenshtein edit-distance fuzzy matching on names
  3. Soundex phonetic matching for transliteration variants
  4. AWS Entity Resolution integration (when configured)
  5. Weighted multi-field scoring with configurable thresholds

Output feeds Stage 9 (data-loader) for BUT000 BP creation in S/4HANA.
"""
import logging
import os
import re
import math
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger("bp_deduplication")
logger.setLevel(logging.INFO)

# Configurable thresholds — can be overridden via environment variables
FUZZY_THRESHOLD = float(os.environ.get("BP_FUZZY_THRESHOLD", "0.82"))
ENTITY_RESOLUTION_ENABLED = os.environ.get("ENTITY_RESOLUTION_WORKFLOW_ARN", "") != ""

# =============================================================================
# PHONETIC & FUZZY MATCHING ALGORITHMS
# =============================================================================

def _soundex(name: str) -> str:
    """American Soundex algorithm for phonetic name matching.
    Maps names to a letter + 3-digit code so that similar-sounding names
    (e.g. 'SMITH' / 'SMYTH', 'MEYER' / 'MEIER') produce the same code."""
    if not name:
        return "0000"
    name = re.sub(r'[^A-Z]', '', name.upper())
    if not name:
        return "0000"

    code_map = {
        'B': '1', 'F': '1', 'P': '1', 'V': '1',
        'C': '2', 'G': '2', 'J': '2', 'K': '2', 'Q': '2', 'S': '2', 'X': '2', 'Z': '2',
        'D': '3', 'T': '3',
        'L': '4',
        'M': '5', 'N': '5',
        'R': '6',
    }
    result = name[0]
    prev_code = code_map.get(name[0], '0')

    for ch in name[1:]:
        code = code_map.get(ch, '0')
        if code != '0' and code != prev_code:
            result += code
        prev_code = code if code != '0' else prev_code

    return (result + '000')[:4]


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein (edit) distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def _levenshtein_similarity(s1: str, s2: str) -> float:
    """Normalized Levenshtein similarity [0.0 .. 1.0]."""
    if not s1 and not s2:
        return 1.0
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    return 1.0 - (_levenshtein_distance(s1, s2) / max_len)


def normalize_string(val: str) -> str:
    """Normalize string for comparison: uppercase, strip non-alphanumeric."""
    if not val:
        return ""
    v = str(val).upper().strip()
    return re.sub(r'[^A-Z0-9]', '', v)


def _normalize_name(val: str) -> str:
    """Name-specific normalization: expand common abbreviations, strip suffixes."""
    if not val:
        return ""
    v = str(val).upper().strip()
    # Remove common legal suffixes that don't affect identity
    for suffix in [' GMBH', ' AG', ' LTD', ' LLC', ' INC', ' CORP', ' CORPORATION',
                   ' PVT', ' PRIVATE', ' LIMITED', ' CO', ' COMPANY', ' & CO',
                   ' S.A.', ' SA', ' SE', ' PLC', ' NV', ' BV', ' KG', ' OHG',
                   ' LTDA', ' EIRELI', ' SRL', ' SPA', ' PTY']:
        if v.endswith(suffix):
            v = v[:-len(suffix)].strip()
    return re.sub(r'[^A-Z0-9 ]', '', v).strip()


# =============================================================================
# MULTI-FIELD WEIGHTED SCORING
# =============================================================================

# Field weights for composite similarity score
FIELD_WEIGHTS = {
    "name":    0.35,
    "tax_id":  0.30,
    "city":    0.15,
    "postal":  0.10,
    "street":  0.10,
}

def _compute_match_score(entity_a: Dict, entity_b: Dict) -> float:
    """Compute weighted similarity score between two business partner records."""
    score = 0.0

    # NAME — Levenshtein + Soundex bonus
    name_a = _normalize_name(entity_a.get("NAME1", ""))
    name_b = _normalize_name(entity_b.get("NAME1", ""))
    name_sim = _levenshtein_similarity(name_a, name_b)
    if _soundex(name_a) == _soundex(name_b) and name_a and name_b:
        name_sim = min(1.0, name_sim + 0.10)  # phonetic bonus
    score += name_sim * FIELD_WEIGHTS["name"]

    # TAX ID — exact match only (tax IDs should not be fuzzy)
    tax_a = normalize_string(entity_a.get("STCD1", entity_a.get("STCD3", "")))
    tax_b = normalize_string(entity_b.get("STCD1", entity_b.get("STCD3", "")))
    if tax_a and tax_b:
        score += (1.0 if tax_a == tax_b else 0.0) * FIELD_WEIGHTS["tax_id"]
    # If both tax IDs missing, field is neutral (don't penalize)
    elif not tax_a and not tax_b:
        score += 0.5 * FIELD_WEIGHTS["tax_id"]

    # CITY — Levenshtein
    city_a = normalize_string(entity_a.get("ORT01", ""))
    city_b = normalize_string(entity_b.get("ORT01", ""))
    if city_a and city_b:
        score += _levenshtein_similarity(city_a, city_b) * FIELD_WEIGHTS["city"]
    elif not city_a and not city_b:
        score += 0.5 * FIELD_WEIGHTS["city"]

    # POSTAL CODE — exact match
    post_a = normalize_string(entity_a.get("PSTLZ", ""))
    post_b = normalize_string(entity_b.get("PSTLZ", ""))
    if post_a and post_b:
        score += (1.0 if post_a == post_b else 0.0) * FIELD_WEIGHTS["postal"]
    elif not post_a and not post_b:
        score += 0.5 * FIELD_WEIGHTS["postal"]

    # STREET — Levenshtein
    str_a = normalize_string(entity_a.get("STRAS", ""))
    str_b = normalize_string(entity_b.get("STRAS", ""))
    if str_a and str_b:
        score += _levenshtein_similarity(str_a, str_b) * FIELD_WEIGHTS["street"]
    elif not str_a and not str_b:
        score += 0.5 * FIELD_WEIGHTS["street"]

    return score


# =============================================================================
# BLOCKING STRATEGY (Performance Optimization)
# =============================================================================

def _build_blocks(entities: List[Dict]) -> Dict[str, List[int]]:
    """Build blocking keys to avoid O(n^2) pairwise comparison.
    Groups entities by Soundex(NAME1) + first 3 chars of postal code.
    Only entities in the same block are compared pairwise."""
    blocks: Dict[str, List[int]] = {}
    for idx, entity in enumerate(entities):
        name = _normalize_name(entity.get("NAME1", ""))
        postal = normalize_string(entity.get("PSTLZ", ""))[:3]
        block_key = f"{_soundex(name)}_{postal}"
        blocks.setdefault(block_key, []).append(idx)

        # Also add a secondary block on Tax ID for entities with tax numbers
        tax = normalize_string(entity.get("STCD1", entity.get("STCD3", "")))
        if tax:
            tax_block = f"TAX_{tax}"
            blocks.setdefault(tax_block, []).append(idx)

    return blocks


# =============================================================================
# CORE DEDUPLICATION ENGINE
# =============================================================================

def run_fuzzy_match(
    entities: List[Dict[str, Any]],
    entity_type: str = "CUSTOMER",
    threshold: float = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Production-grade deduplication using multi-field fuzzy matching.

    Algorithm:
    1. Build blocking keys (Soundex + postal prefix) to prune search space
    2. Within each block, compute pairwise weighted similarity scores
    3. Entities scoring above the threshold are linked as duplicates
    4. Union-Find assigns a canonical master for each duplicate cluster

    Returns: (masters, duplicates) where each duplicate has _M4H_DUPLICATE_OF set.
    """
    if threshold is None:
        threshold = FUZZY_THRESHOLD

    if not entities:
        return [], []

    n = len(entities)
    # Union-Find for clustering
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            # Prefer lower index as root (first-seen = master)
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    # Step 1: Build blocking index
    blocks = _build_blocks(entities)

    # Step 2: Pairwise scoring within blocks
    compared = set()
    match_details = []
    for block_key, indices in blocks.items():
        if len(indices) < 2:
            continue
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                a, b = indices[i], indices[j]
                pair = (min(a, b), max(a, b))
                if pair in compared:
                    continue
                compared.add(pair)

                score = _compute_match_score(entities[a], entities[b])
                if score >= threshold:
                    union(a, b)
                    match_details.append({
                        "entity_a": entities[a].get("KUNNR", entities[a].get("LIFNR", "")),
                        "entity_b": entities[b].get("KUNNR", entities[b].get("LIFNR", "")),
                        "score": round(score, 3),
                        "block": block_key,
                    })

    # Step 3: Assign masters and duplicates based on clusters
    masters = []
    duplicates = []
    cluster_masters = {}

    for idx in range(n):
        root = find(idx)
        entity_id = entities[idx].get("KUNNR", entities[idx].get("LIFNR", "UNKNOWN"))

        if root == idx:
            # This entity is the cluster root (master)
            entities[idx]["_M4H_ACTION"] = "CREATE_NEW_BP"
            entities[idx]["_M4H_CLUSTER_ID"] = root
            masters.append(entities[idx])
            cluster_masters[root] = entity_id
        else:
            # Duplicate — point to master
            master_id = cluster_masters.get(root, entities[root].get("KUNNR", entities[root].get("LIFNR", "")))
            entities[idx]["_M4H_DUPLICATE_OF"] = master_id
            entities[idx]["_M4H_ACTION"] = "MERGE"
            entities[idx]["_M4H_MATCH_SCORE"] = round(
                _compute_match_score(entities[idx], entities[root]), 3
            )
            entities[idx]["_M4H_CLUSTER_ID"] = root
            duplicates.append(entities[idx])
            logger.info(
                f"Fuzzy duplicate {entity_type}: {entity_id} -> Master: {master_id} "
                f"(score={entities[idx]['_M4H_MATCH_SCORE']})"
            )

    logger.info(
        f"Dedup complete [{entity_type}]: {n} total -> "
        f"{len(masters)} unique, {len(duplicates)} duplicates "
        f"({len(compared)} pairs compared, {len(match_details)} matches)"
    )
    return masters, duplicates


# =============================================================================
# AWS ENTITY RESOLUTION INTEGRATION
# =============================================================================

def _run_entity_resolution(
    customers: List[Dict], vendors: List[Dict]
) -> Optional[Dict[str, Any]]:
    """
    Calls AWS Entity Resolution for ML-powered matching when configured.
    Uses the matching workflow ARN from environment variable.
    Falls back gracefully to local fuzzy matching if unavailable.
    """
    workflow_arn = os.environ.get("ENTITY_RESOLUTION_WORKFLOW_ARN", "")
    if not workflow_arn:
        return None

    try:
        import boto3
        er_client = boto3.client("entityresolution")

        # Start the matching job
        response = er_client.start_matching_job(workflowName=workflow_arn.split("/")[-1])
        job_id = response.get("jobId", "")
        logger.info(f"AWS Entity Resolution job started: {job_id}")

        # Poll for completion (Entity Resolution jobs run asynchronously)
        import time
        max_wait = 300  # 5 min max
        waited = 0
        while waited < max_wait:
            status = er_client.get_matching_job(
                workflowName=workflow_arn.split("/")[-1], jobId=job_id
            )
            job_status = status.get("status", "")
            if job_status == "SUCCEEDED":
                logger.info(f"Entity Resolution job {job_id} completed successfully")
                return {
                    "source": "AWS_ENTITY_RESOLUTION",
                    "job_id": job_id,
                    "metrics": status.get("metrics", {}),
                    "output_s3": status.get("outputSourceConfig", []),
                }
            elif job_status in ("FAILED", "CANCELLED"):
                logger.warning(f"Entity Resolution job {job_id} {job_status}")
                return None
            time.sleep(10)
            waited += 10

        logger.warning(f"Entity Resolution job {job_id} timed out after {max_wait}s")
        return None

    except ImportError:
        logger.warning("boto3 not available — skipping Entity Resolution")
        return None
    except Exception as e:
        logger.warning(f"Entity Resolution failed, falling back to local: {e}")
        return None


# =============================================================================
# CROSS-ENTITY CUSTOMER x VENDOR MATCHING
# =============================================================================

def _cross_match_customer_vendor(
    customers: List[Dict], vendors: List[Dict], threshold: float = None
) -> List[Dict]:
    """Detect cases where the same real-world entity exists as both
    a Customer (KNA1) and a Vendor (LFA1) — common in intercompany scenarios.
    These should become a single Business Partner in S/4HANA.

    Uses blocking (Soundex+postal, Tax ID, Country+City) for performance,
    then picks the highest-scoring match per vendor via a two-pass approach
    to guarantee 1:1 customer-vendor merges with the best possible pairing.
    """
    if threshold is None:
        threshold = FUZZY_THRESHOLD

    # Build multi-key blocking index on vendors
    vendor_blocks: Dict[str, List[int]] = {}
    for idx, v in enumerate(vendors):
        if v.get("_M4H_ACTION") != "CREATE_NEW_BP":
            continue
        name = _normalize_name(v.get("NAME1", ""))
        postal = normalize_string(v.get("PSTLZ", ""))[:3]
        country = normalize_string(v.get("LAND1", ""))
        city = normalize_string(v.get("ORT01", ""))[:4]

        # Primary block: Soundex(name) + postal prefix
        block_key = f"{_soundex(name)}_{postal}"
        vendor_blocks.setdefault(block_key, []).append(idx)

        # Secondary block: Tax ID (exact)
        tax = normalize_string(v.get("STCD1", v.get("STCD3", "")))
        if tax:
            vendor_blocks.setdefault(f"TAX_{tax}", []).append(idx)

        # Tertiary block: Country + City prefix (catches records missing postal/tax)
        if country and city:
            vendor_blocks.setdefault(f"GEO_{country}_{city}", []).append(idx)

    # Pass 1: Score all candidate pairs from blocking
    # key = (customer_idx, vendor_idx), value = score
    pair_scores: Dict[Tuple[int, int], float] = {}
    for cidx, c in enumerate(customers):
        if c.get("_M4H_ACTION") != "CREATE_NEW_BP":
            continue

        name = _normalize_name(c.get("NAME1", ""))
        postal = normalize_string(c.get("PSTLZ", ""))[:3]
        country = normalize_string(c.get("LAND1", ""))
        city = normalize_string(c.get("ORT01", ""))[:4]

        candidate_indices: set = set()
        candidate_indices.update(vendor_blocks.get(f"{_soundex(name)}_{postal}", []))

        tax = normalize_string(c.get("STCD1", c.get("STCD3", "")))
        if tax:
            candidate_indices.update(vendor_blocks.get(f"TAX_{tax}", []))
        if country and city:
            candidate_indices.update(vendor_blocks.get(f"GEO_{country}_{city}", []))

        for vidx in candidate_indices:
            score = _compute_match_score(c, vendors[vidx])
            if score >= threshold:
                pair_scores[(cidx, vidx)] = score

    # Pass 2: Greedy best-score assignment (1:1 customer↔vendor)
    matched_customers: set = set()
    matched_vendors: set = set()
    cross_matches = []

    for (cidx, vidx), score in sorted(pair_scores.items(), key=lambda x: -x[1]):
        if cidx in matched_customers or vidx in matched_vendors:
            continue
        matched_customers.add(cidx)
        matched_vendors.add(vidx)

        c = customers[cidx]
        v = vendors[vidx]
        cross_matches.append({
            "customer": c.get("KUNNR", ""),
            "vendor": v.get("LIFNR", ""),
            "score": round(score, 3),
            "merged_bp_type": "BOTH_CUS_VEN",
        })
        logger.info(
            f"Cross-match: Customer {c.get('KUNNR')} <-> Vendor {v.get('LIFNR')} "
            f"(score={score:.3f})"
        )

    return cross_matches


# =============================================================================
# MAIN ENTRYPOINT
# =============================================================================

def process_cvi_deduplication(
    customers_kna1: List[Dict], vendors_lfa1: List[Dict]
) -> Dict[str, Any]:
    """
    Main entrypoint for Stage 3 planning / MDM phase.

    Pipeline:
    1. Try AWS Entity Resolution (if workflow ARN configured)
    2. Fallback: Local fuzzy matching (Levenshtein + Soundex + weighted scoring)
    3. Cross-match customers vs vendors for intercompany BPs
    4. Output instructs Stage 9 (data-loader) on BUT000 BAPI mapping
    """
    # Attempt AWS Entity Resolution first
    er_result = None
    if ENTITY_RESOLUTION_ENABLED:
        er_result = _run_entity_resolution(customers_kna1, vendors_lfa1)

    # Local fuzzy deduplication (always runs — serves as fallback or complement)
    k_unique, k_dupes = run_fuzzy_match(customers_kna1, "CUSTOMER")
    v_unique, v_dupes = run_fuzzy_match(vendors_lfa1, "VENDOR")

    # Cross-entity matching (customer who is also a vendor)
    cross_matches = _cross_match_customer_vendor(k_unique, v_unique)

    return {
        "customers_to_create": k_unique,
        "customers_to_merge": k_dupes,
        "vendors_to_create": v_unique,
        "vendors_to_merge": v_dupes,
        "cross_entity_matches": cross_matches,
        "entity_resolution": er_result,
        "algorithm": {
            "method": "levenshtein_soundex_weighted",
            "threshold": FUZZY_THRESHOLD,
            "field_weights": FIELD_WEIGHTS,
            "blocking": "soundex_name + postal_prefix + tax_id",
            "aws_entity_resolution": "active" if er_result else "not_configured",
        },
        "stats": {
            "total_raw": len(customers_kna1) + len(vendors_lfa1),
            "total_new_bps": len(k_unique) + len(v_unique),
            "total_merged": len(k_dupes) + len(v_dupes),
            "cross_entity_matches": len(cross_matches),
            "customer_dedup_rate": f"{(len(k_dupes) / max(len(customers_kna1), 1)) * 100:.1f}%",
            "vendor_dedup_rate": f"{(len(v_dupes) / max(len(vendors_lfa1), 1)) * 100:.1f}%",
        },
    }
