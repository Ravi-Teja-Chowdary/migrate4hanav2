"""
Migrate4HANA — Real SAP ECC RFC Connection
============================================
Wraps pyrfc.Connection to extract live data from a real SAP ECC system.
Populates self.dataset in the same format as MockRFCConnection so that
all 17 pipeline stages work unchanged.

Usage:
    from real_rfc_connection import RealRFCConnection
    conn = RealRFCConnection({"ashost": "...", "sysnr": "00", "client": "100",
                              "user": "RFC_USER", "passwd": "secret"})
    # conn.dataset now holds real ECC data
    # conn.call("RFC_READ_TABLE", ...) passes through to pyrfc
"""

import pyrfc
import logging
import time as _time
from datetime import datetime

logger = logging.getLogger("real_rfc_connection")
logger.setLevel(logging.INFO)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _parse_rfc_read_table(result, delimiter="|"):
    """Parse RFC_READ_TABLE result into list of dicts."""
    fields = [f["FIELDNAME"] for f in result.get("FIELDS", [])]
    rows = []
    for entry in result.get("DATA", []):
        wa = entry.get("WA", "")
        values = [v.strip() for v in wa.split(delimiter)]
        row = {}
        for i, fname in enumerate(fields):
            row[fname] = values[i] if i < len(values) else ""
        rows.append(row)
    return rows


def _safe_int(val, default=0):
    """Convert string to int, returning default on failure."""
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return default


# ── Main Class ──────────────────────────────────────────────────────────────

class RealRFCConnection:
    """
    Drop-in replacement for MockRFCConnection that reads from a real SAP ECC.

    On init, extracts all ECC data via RFC calls and stores in self.dataset
    in the same format the pipeline expects.  The call() method passes through
    to the real pyrfc.Connection for any RFC function.
    """

    def __init__(self, conn_params, limit=0):
        """
        conn_params: dict with keys ashost, sysnr, client, user, passwd,
                     and optionally saprouter.
        limit: when > 0, cap programs/customers/vendors to this many for fast testing.
        """
        clean = {k: v for k, v in conn_params.items() if v}
        self._conn_params = clean
        self._pyrfc = pyrfc.Connection(**clean)
        self._call_count = 0
        self._limit = limit

        # Execution tracking (same as MockRFCConnection)
        self._deployed_programs = {}
        self._activated_programs = set()
        self._transport_requests = []
        self._loaded_finance_docs = []
        self._loaded_bps = []
        self._loaded_material_docs = []
        self._created_roles = []
        self._rfc_destinations = []
        self._idoc_partners = []
        self._config_applied = []
        self._committed = 0

        # Extract live data
        self._field_cache = {}  # Cache for DDIF_FIELDINFO_GET results per table
        self.dataset = self._extract_all()

    # ── Public interface ────────────────────────────────────────────────

    def call(self, function_name, **kwargs):
        """Pass through to real pyrfc, track call count."""
        self._call_count += 1
        return self._pyrfc.call(function_name, **kwargs)

    def close(self):
        try:
            self._pyrfc.close()
        except Exception:
            pass

    # ── Dynamic Field Discovery ─────────────────────────────────────────

    def _discover_table_fields(self, table_name):
        """Call DDIF_FIELDINFO_GET for the given table and return the set of
        valid field names.  Results are cached so repeated calls for the same
        table hit SAP only once."""
        if table_name in self._field_cache:
            return self._field_cache[table_name]

        try:
            self._ensure_connection()
            result = self._pyrfc.call("DDIF_FIELDINFO_GET",
                                       TABNAME=table_name, FIELDNAME="", LANGU="E")
            # DFIES_TAB contains the full field catalog
            dfies = result.get("DFIES_TAB", [])
            fields = {row.get("FIELDNAME", "") for row in dfies if row.get("FIELDNAME")}
            if not fields:
                # Fallback — try the LINES_DESCRIBED table
                lines_desc = result.get("LINES_DESCRIBED", [])
                fields = {row.get("FIELDNAME", "") for row in lines_desc if row.get("FIELDNAME")}
            self._field_cache[table_name] = fields
            logger.info(f"[FIELD_DISCOVERY] {table_name}: {len(fields)} fields discovered")
            return fields
        except Exception as e:
            logger.warning(f"[FIELD_DISCOVERY] DDIF_FIELDINFO_GET failed for {table_name}: {e}")
            print(f"    [FIELD_DISCOVERY] Warning: Could not discover fields for {table_name}: {e}")
            self._field_cache[table_name] = set()  # cache the failure to avoid repeated calls
            return set()

    def _validate_fields(self, table, requested_fields, mandatory_fields=None):
        """Intersect requested fields with actual SAP table fields.
        Returns the list of valid fields to pass to RFC_READ_TABLE.
        Logs CRITICAL for any mandatory fields that are missing."""
        actual = self._discover_table_fields(table)
        if not actual:
            # Discovery failed — fall back to original field list (let RFC_READ_TABLE decide)
            logger.warning(f"[FIELD_VALIDATE] {table}: field discovery returned nothing, using all requested fields")
            return requested_fields

        valid = [f for f in requested_fields if f in actual]
        dropped = [f for f in requested_fields if f not in actual]

        if dropped:
            logger.warning(f"[FIELD_VALIDATE] {table}: Dropped non-existent fields: {dropped}")
            print(f"    [FIELD_VALIDATE] {table}: Dropped {len(dropped)} invalid fields: {', '.join(dropped)}")

        if mandatory_fields:
            missing_mandatory = [f for f in mandatory_fields if f not in actual]
            if missing_mandatory:
                logger.critical(
                    f"[FIELD_VALIDATE] {table}: MANDATORY fields missing from SAP schema: {missing_mandatory}"
                )
                print(f"    {chr(27)}[91m[FIELD_VALIDATE] CRITICAL: {table} is missing mandatory fields: "
                      f"{', '.join(missing_mandatory)} — data quality will be degraded!{chr(27)}[0m")

        if not valid:
            logger.error(f"[FIELD_VALIDATE] {table}: No valid fields remaining after intersection!")
            return requested_fields  # fall back

        return valid

    # ── Data extraction ─────────────────────────────────────────────────

    def _read_table(self, table, fields=None, options=None, max_rows=0,
                    mandatory_fields=None):
        """Wrapper around RFC_READ_TABLE with dynamic field validation and reconnect."""
        if fields:
            fields = self._validate_fields(table, fields, mandatory_fields)
        params = {"QUERY_TABLE": table, "DELIMITER": "|"}
        if fields:
            params["FIELDS"] = [{"FIELDNAME": f} for f in fields]
        if options:
            params["OPTIONS"] = [{"TEXT": t} for t in options]
        if max_rows:
            params["ROWCOUNT"] = max_rows
        try:
            self._ensure_connection()
            result = self._pyrfc.call("RFC_READ_TABLE", **params)
            return _parse_rfc_read_table(result)
        except Exception as e:
            logger.warning(f"[RFC] Could not read {table}: {e}")
            print(f"    [RFC] Warning: Could not read {table}: {e}")
            return []

    def _extract_all(self):
        """Extract all ECC data into the standard dataset format."""
        if self._limit > 0:
            print(f"  Extracting live ECC data via RFC (--limit {self._limit} active)...")
        else:
            print("  Extracting live ECC data via RFC...")
        data = {}

        # System info from RFC_SYSTEM_INFO
        print("    -> System info...")
        data["system_info"] = self._extract_system_info()

        print("    -> Custom ABAP programs (TRDIR)...")
        data["programs"] = self._extract_programs()
        print(f"       {len(data['programs'])} programs found")

        print("    -> Custom tables (DD02L)...")
        data["tables"] = self._extract_tables()
        print(f"       {len(data['tables'])} custom tables found")

        print("    -> Function modules (TFDIR+ENLFDIR)...")
        data["function_modules"] = self._extract_function_modules()
        print(f"       {len(data['function_modules'])} function modules found")

        print("    -> Org structure (T001, T001W, TVKO, TKA01, T001L, T024E)...")
        data["org_structure"] = self._extract_org_structure()

        print("    -> User roles (AGR_DEFINE)...")
        data["roles"] = self._extract_roles()
        print(f"       {len(data['roles']['roles'])} roles found")

        print("    -> Integration points (RFCDES, EDPP1)...")
        data["integrations"] = self._extract_integrations()

        print("    -> Customers (KNA1)...")
        data["customers"] = self._extract_customers()
        print(f"       {len(data['customers'])} customers found")

        print("    -> Vendors (LFA1)...")
        data["vendors"] = self._extract_vendors()
        print(f"       {len(data['vendors'])} vendors found")

        print("    -> Finance documents (BKPF/BSEG)...")
        data["finance"] = self._extract_finance()
        print(f"       {len(data['finance']['bkpf'])} doc headers, {len(data['finance']['bseg'])} line items")

        print("    -> ABAP source code (3-tier: RPY → RFC_READ → READ_REPORT)...")
        data["abap_source"] = self._extract_abap_source(data["programs"])
        print(f"       {len(data['abap_source'])} programs with source code")

        data["fixed_abap_source"] = {}

        # Users
        print("    -> Users (USR02)...")
        data["users"] = self._extract_users()
        print(f"       {len(data['users'])} users found")

        # Fill summary counts in system_info
        data["system_info"].update({
            "total_custom_programs": len(data["programs"]),
            "total_custom_tables": len(data["tables"]),
            "total_function_modules": len(data["function_modules"]),
            "total_customers": len(data["customers"]),
            "total_vendors": len(data["vendors"]),
            "total_roles": len(data["roles"]["roles"]),
            "total_users": len(data["users"]),
            "generated_at": datetime.now().isoformat(),
        })

        print(f"\n  ✅ Live ECC extraction complete!")
        print(f"     System: {data['system_info'].get('description', 'N/A')}")
        print(f"     Programs: {data['system_info']['total_custom_programs']}")
        print(f"     Tables: {data['system_info']['total_custom_tables']}")
        print(f"     Customers: {data['system_info']['total_customers']}")
        print(f"     Vendors: {data['system_info']['total_vendors']}")

        return data

    # ── Individual extractors ───────────────────────────────────────────

    def _extract_system_info(self):
        """Get system info via RFC_SYSTEM_INFO."""
        try:
            result = self._pyrfc.call("RFC_SYSTEM_INFO")
            si = result.get("RFCSI_EXPORT", {})
            return {
                "sid": si.get("RFCSYSID", "???"),
                "description": f"{si.get('RFCSYSID', '???')} — SAP {si.get('RFCSAPRL', '')}",
                "database": si.get("RFCDBSYS", ""),
                "os": si.get("RFCOPSYS", ""),
                "kernel": si.get("RFCKERNRL", ""),
                "unicode": si.get("RFCUNICODE", "") == "1",
                "client": si.get("RFCCLIENT", ""),
                "host": si.get("RFCHOST", ""),
                "sap_release": si.get("RFCSAPRL", ""),
            }
        except Exception as e:
            print(f"    [RFC] Warning: RFC_SYSTEM_INFO failed: {e}")
            return {"sid": "???", "description": "Unknown SAP system"}

    def _extract_programs(self):
        """Read custom programs from TRDIR (Z* and Y* namespace)."""
        fields = ["NAME", "SUBC", "CDAT", "UDAT", "UNAM", "RSTAT"]
        options = ["NAME LIKE 'Z%' OR NAME LIKE 'Y%'"]
        max_rows = self._limit if self._limit > 0 else 0
        rows = self._read_table_chunked("TRDIR", fields, options, max_rows=max_rows)

        programs = []
        type_map = {"1": "report", "I": "include", "M": "module_pool",
                     "F": "function_group", "S": "subroutine_pool",
                     "J": "interface", "K": "class"}
        for r in rows:
            programs.append({
                "NAME": r.get("NAME", ""),
                "SUBC": r.get("SUBC", ""),
                "CDAT": r.get("CDAT", ""),
                "UDAT": r.get("UDAT", ""),
                "UNAM": r.get("UNAM", ""),
                "RSTAT": r.get("RSTAT", ""),
                "type": type_map.get(r.get("SUBC", ""), "other"),
                "modified_by": r.get("UNAM", ""),
                "status": "active" if r.get("RSTAT", "") != "S" else "inactive",
            })
        return programs

    def _extract_tables(self):
        """Read custom tables from DD02L."""
        fields = ["TABNAME", "TABCLASS", "AS4DATE"]
        options = ["TABNAME LIKE 'Z%' OR TABNAME LIKE 'Y%'"]
        rows = self._read_table_chunked("DD02L", fields, options)

        # Get table descriptions from DD02T
        desc_rows = self._read_table("DD02T",
                                      ["TABNAME", "DDTEXT"],
                                      ["DDLANGUAGE = 'E'"])
        desc_map = {r["TABNAME"]: r.get("DDTEXT", "") for r in desc_rows}

        tables = []
        for r in rows:
            tabname = r.get("TABNAME", "")
            tables.append({
                "TABNAME": tabname,
                "TABCLASS": r.get("TABCLASS", "TRANSP"),
                "AS4DATE": r.get("AS4DATE", ""),
                "desc": desc_map.get(tabname, ""),
                "rows": 0,
                "estimated_rows": 0,
            })
        return tables

    def _extract_function_modules(self):
        """Read custom function modules from TFDIR."""
        fields = ["FUNCNAME", "PNAME", "FMODE"]
        options = ["FUNCNAME LIKE 'Z%' OR FUNCNAME LIKE 'Y%'"]
        rows = self._read_table_chunked("TFDIR", fields, options)

        fms = []
        for r in rows:
            fms.append({
                "FUNCNAME": r.get("FUNCNAME", ""),
                "PNAME": r.get("PNAME", ""),
                "FMODE": r.get("FMODE", ""),
                "is_rfc_enabled": r.get("FMODE", "") == "R",
            })
        return fms

    def _extract_org_structure(self):
        """Read org structure from T001, T001W, TVKO, TKA01, T001L, T024E."""
        company_codes = self._read_table("T001",
            ["BUKRS", "BUTXT", "WAERS", "LAND1", "ORT01", "KTOPL", "PERIV"],
            mandatory_fields=["BUKRS", "BUTXT"])

        plants = self._read_table("T001W",
            ["WERKS", "NAME1", "BUKRS", "LAND1", "FABKL", "ORT01"],
            mandatory_fields=["WERKS", "NAME1"])

        storage_locs = self._read_table("T001L",
            ["WERKS", "LGORT", "LGOBE"])

        sales_orgs = self._read_table("TVKO",
            ["VKORG", "BUKRS"])
        # Try to get sales org text from TVKOT
        so_text = self._read_table("TVKOT", ["VKORG", "VTEXT"], ["SPRAS = 'E'"])
        so_map = {r["VKORG"]: r.get("VTEXT", "") for r in so_text}
        for so in sales_orgs:
            so["VTEXT"] = so_map.get(so.get("VKORG", ""), "")

        controlling = self._read_table("TKA01",
            ["KOKRS", "BEZEI", "WAERS"])
        # Try to get BUKRS mapping from TKA02
        tka02 = self._read_table("TKA02", ["KOKRS", "BUKRS"])
        kokrs_bukrs = {}
        for r in tka02:
            kokrs_bukrs.setdefault(r.get("KOKRS", ""), []).append(r.get("BUKRS", ""))
        for ca in controlling:
            ca["BUKRS"] = kokrs_bukrs.get(ca.get("KOKRS", ""), [])

        purchasing = self._read_table("T024E",
            ["EKORG", "BUKRS", "EKOTX"])

        cc_count = len(company_codes)
        pl_count = len(plants)
        so_count = len(sales_orgs)
        ca_count = len(controlling)
        print(f"       {cc_count} company codes, {pl_count} plants, {so_count} sales orgs, {ca_count} controlling areas")

        return {
            "company_codes": company_codes,
            "plants": plants,
            "storage_locations": storage_locs,
            "sales_orgs": sales_orgs,
            "controlling_areas": controlling,
            "purchasing_orgs": purchasing,
        }

    def _extract_roles(self):
        """Read roles from AGR_DEFINE, user counts from AGR_USERS."""
        fields = ["AGR_NAME", "PARENT_AGR"]
        options = ["AGR_NAME LIKE 'Z%' OR AGR_NAME LIKE 'Y%' OR AGR_NAME LIKE 'SAP%'"]
        rows = self._read_table_chunked("AGR_DEFINE", fields, options)

        # Get user counts per role
        user_rows = self._read_table_chunked("AGR_USERS",
            ["AGR_NAME", "UNAME"])
        user_counts = {}
        unique_users = set()
        for ur in user_rows:
            name = ur.get("AGR_NAME", "")
            user_counts[name] = user_counts.get(name, 0) + 1
            unique_users.add(ur.get("UNAME", ""))

        roles = []
        for r in rows:
            agr_name = r.get("AGR_NAME", "")
            parent = r.get("PARENT_AGR", "")
            roles.append({
                "AGR_NAME": agr_name,
                "PARENT_AGR": parent,
                "is_composite": bool(parent and parent.strip()),
                "user_count": user_counts.get(agr_name, 0),
            })

        return {
            "roles": roles,
            "total_users": len(unique_users),
            "role_count": len(roles),
        }

    def _extract_integrations(self):
        """Read RFC destinations from RFCDES, IDoc partners from EDPP1."""
        rfc_rows = self._read_table("RFCDES",
            ["RFCDEST", "RFCTYPE", "RFCOPTIONS"])

        rfc_destinations = []
        for r in rfc_rows:
            rfc_destinations.append({
                "RFCDEST": r.get("RFCDEST", ""),
                "RFCTYPE": r.get("RFCTYPE", ""),
                "desc": r.get("RFCOPTIONS", ""),
            })

        idoc_rows = self._read_table("EDPP1",
            ["RCVPRN", "RCVPRT", "MESTYP", "IDOCTP"])

        idoc_partners = []
        for r in idoc_rows:
            idoc_partners.append({
                "RCVPRN": r.get("RCVPRN", ""),
                "RCVPRT": r.get("RCVPRT", ""),
                "MESTYP": r.get("MESTYP", ""),
                "IDOCTP": r.get("IDOCTP", ""),
                "desc": f"{r.get('MESTYP', '')} via {r.get('IDOCTP', '')}",
            })

        rfc_count = len(rfc_destinations)
        idoc_count = len(idoc_partners)
        print(f"       {rfc_count} RFC destinations, {idoc_count} IDoc partners")

        return {
            "rfc_destinations": rfc_destinations,
            "idoc_partners": idoc_partners,
        }

    def _extract_customers(self):
        """Read customers from KNA1 with dynamic field validation."""
        fields = ["KUNNR", "NAME1", "LAND1", "ORT01", "PSTLZ", "STRAS",
                   "STCD1", "SMTP_ADDR", "TELF1", "KTOKD"]
        mandatory = ["KUNNR", "NAME1", "PSTLZ"]
        max_rows = self._limit if self._limit > 0 else 0
        rows = self._read_table_chunked("KNA1", fields, max_rows=max_rows,
                                         mandatory_fields=mandatory)
        return rows

    def _extract_vendors(self):
        """Read vendors from LFA1 with dynamic field validation."""
        fields = ["LIFNR", "NAME1", "LAND1", "ORT01", "PSTLZ", "STRAS",
                   "STCD1", "SMTP_ADDR", "KTOKK"]
        mandatory = ["LIFNR", "NAME1", "PSTLZ"]
        max_rows = self._limit if self._limit > 0 else 0
        rows = self._read_table_chunked("LFA1", fields, max_rows=max_rows,
                                         mandatory_fields=mandatory)
        return rows

    def _extract_finance(self):
        """Read finance doc headers (BKPF) and line items (BSEG) — sampled."""
        bkpf_fields = ["BUKRS", "BELNR", "GJAHR", "BLART", "BUDAT", "USNAM", "WAERS"]
        bkpf = self._read_table_chunked("BKPF", bkpf_fields, max_rows=10000)

        bseg_fields = ["BUKRS", "BELNR", "GJAHR", "BUZEI", "KOART", "HKONT",
                        "DMBTR", "WRBTR", "SHKZG"]
        bseg = self._read_table_chunked("BSEG", bseg_fields, max_rows=50000)

        return {"bkpf": bkpf, "bseg": bseg}

    def _ensure_connection(self):
        """Reconnect if the pyrfc connection has dropped."""
        try:
            self._pyrfc.alive
        except Exception:
            logger.warning("RFC connection lost — reconnecting...")
            try:
                self._pyrfc = pyrfc.Connection(**self._conn_params)
                logger.info("RFC reconnection successful")
            except Exception as e:
                logger.error(f"RFC reconnection failed: {e}")
                raise

    def _read_table_chunked(self, table, fields=None, options=None,
                             chunk_size=5000, max_rows=0, max_retries=3,
                             mandatory_fields=None):
        """Read large tables in chunks with retry/backoff and dynamic field validation.
        If max_rows > 0, stop after that many."""
        if fields:
            fields = self._validate_fields(table, fields, mandatory_fields)
        all_rows = []
        skip = 0
        consecutive_failures = 0
        chunk_num = 0
        while True:
            remaining = max_rows - len(all_rows) if max_rows else chunk_size
            fetch = min(chunk_size, remaining) if max_rows else chunk_size
            if fetch <= 0:
                break

            params = {"QUERY_TABLE": table, "DELIMITER": "|",
                      "ROWCOUNT": fetch, "ROWSKIPS": skip}
            if fields:
                params["FIELDS"] = [{"FIELDNAME": f} for f in fields]
            if options:
                params["OPTIONS"] = [{"TEXT": t} for t in options]

            success = False
            chunk_num += 1
            for attempt in range(1, max_retries + 1):
                try:
                    self._ensure_connection()
                    result = self._pyrfc.call("RFC_READ_TABLE", **params)
                    rows = _parse_rfc_read_table(result)
                    if not rows:
                        if chunk_num == 1:
                            logger.warning(f"[RFC] {table}: First chunk returned 0 rows")
                        return all_rows  # table exhausted
                    all_rows.extend(rows)
                    consecutive_failures = 0
                    success = True
                    target_str = f"/{max_rows}" if max_rows else ""
                    print(f"       Chunk {chunk_num} received — {len(all_rows):,}{target_str} rows from {table}")
                    if len(rows) < fetch:
                        return all_rows  # last page
                    skip += fetch
                    break
                except Exception as e:
                    backoff = min(2 ** attempt, 30)
                    logger.warning(
                        f"[RFC] Chunk read of {table} failed at offset {skip} "
                        f"(attempt {attempt}/{max_retries}): {e} — retrying in {backoff}s"
                    )
                    print(f"    [RFC] Warning: {table} offset {skip} attempt {attempt}/{max_retries}: {e}")
                    _time.sleep(backoff)

            if not success:
                consecutive_failures += 1
                logger.error(f"[RFC] Giving up on {table} at offset {skip} after {max_retries} retries")
                print(f"    [RFC] ERROR: Could not read {table} at offset {skip} after {max_retries} retries")
                break

        logger.info(f"[RFC] {table}: fetched {len(all_rows)} total rows")
        return all_rows

    # ── Authorization error keywords SAP embeds in RFC exceptions ──
    _AUTH_ERROR_KEYWORDS = [
        "NO_AUTHORITY", "AUTHORITY", "NOT_AUTHORIZED", "ENQUEUE",
        "NO_PERMISSION", "AUTHORIZATION", "S_DEVELOP", "S_PROGNAM",
        "ACTVT", "RC=12", "PERMISSION_FAILURE",
    ]

    def _check_auth_error(self, prog_name, exc):
        """Inspect an RFC exception for SAP authorization failures.
        Returns True if an auth error was detected (and logs details)."""
        err_upper = str(exc).upper()
        for kw in self._AUTH_ERROR_KEYWORDS:
            if kw in err_upper:
                logger.critical(
                    f"[ABAP-AUTH] {prog_name}: SAP authorization error detected! "
                    f"Missing auth object keyword: '{kw}'. Full error: {exc}"
                )
                print(f"       🔒 AUTH ERROR: {prog_name} — SAP denied access "
                      f"(keyword '{kw}'). Check S_DEVELOP / S_PROGNAM authorizations.")
                return True
        return False

    def _read_single_report(self, prog_name):
        """Read a single ABAP program source using a 3-tier cascade.
        Tier 1: RPY_PROGRAM_READ  (PROG_SOURCE table)
        Tier 2: RFC_READ_REPORT   (CONTENT table)
        Tier 3: READ_REPORT       (direct kernel read)
        Each tier is attempted even if the previous returned empty data.
        Returns (source_string, line_count, auth_error_flag)."""
        padded_name = prog_name.ljust(40)

        # ── Tier 1: RPY_PROGRAM_READ ──
        try:
            self._ensure_connection()
            result = self._pyrfc.call("RPY_PROGRAM_READ",
                                       PROGRAM_NAME=padded_name,
                                       WITH_LOWERCASE="X")
            content = result.get("PROG_SOURCE", result.get("PROG_SOURCES", []))
            line_count = len(content)
            print(f"       DEBUG: [Tier1-RPY] {prog_name} -> {line_count} lines")
            if content:
                code = "\n".join(
                    line.get("LINE", line.get("SOURCE", "")) for line in content
                )
                if code.strip():
                    print(f"       DEBUG: Successfully fetched {len(code)} characters for {prog_name}")
                    return code, line_count, False
        except Exception as e1:
            if self._check_auth_error(prog_name, e1):
                return None, 0, True
            logger.info(f"[ABAP] Tier1 RPY_PROGRAM_READ failed for {prog_name}: {e1}")

        # ── Tier 2: RFC_READ_REPORT ──
        try:
            self._ensure_connection()
            result = self._pyrfc.call("RFC_READ_REPORT",
                                       PROGRAM=padded_name)
            content = result.get("CONTENT", [])
            line_count = len(content)
            print(f"       DEBUG: [Tier2-RFC_READ] {prog_name} -> {line_count} lines")
            if content:
                code = "\n".join(line.get("LINE", "") for line in content)
                if code.strip():
                    print(f"       DEBUG: Successfully fetched {len(code)} characters for {prog_name}")
                    return code, line_count, False
        except Exception as e2:
            if self._check_auth_error(prog_name, e2):
                return None, 0, True
            logger.info(f"[ABAP] Tier2 RFC_READ_REPORT failed for {prog_name}: {e2}")

        # ── Tier 3: READ_REPORT (standard SAP kernel read) ──
        try:
            self._ensure_connection()
            result = self._pyrfc.call("READ_REPORT",
                                       REPORT=padded_name)
            content = result.get("LINES", result.get("CONTENT", []))
            line_count = len(content)
            print(f"       DEBUG: [Tier3-READ_REPORT] {prog_name} -> {line_count} lines")
            if content:
                code = "\n".join(
                    line.get("LINE", line.get("TDLINE", "")) for line in content
                )
                if code.strip():
                    print(f"       DEBUG: Successfully fetched {len(code)} characters for {prog_name}")
                    return code, line_count, False
        except Exception as e3:
            if self._check_auth_error(prog_name, e3):
                return None, 0, True
            logger.info(f"[ABAP] Tier3 READ_REPORT failed for {prog_name}: {e3}")

        logger.warning(f"[ABAP] All 3 extraction tiers returned empty for {prog_name}")
        return None, 0, False

    def _extract_abap_source(self, programs):
        """Read source code for custom programs via 3-tier fallback cascade:
        RPY_PROGRAM_READ → RFC_READ_REPORT → READ_REPORT.
        Includes authorization error detection, type diagnostics, and progress logging."""
        sources = {}
        failed_programs = []
        whitespace_only_programs = []
        auth_blocked_programs = []
        programs_processed = 0

        # Diagnostic: log type distribution so we can see if filter is dropping programs
        type_counts = {}
        for p in programs:
            t = p.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        print(f"       Program type distribution: {type_counts}")
        logger.info(f"[ABAP] Program type distribution: {type_counts}")

        # Accept report, module_pool, include, subroutine_pool — skip class/interface/function_group
        eligible_types = ("report", "module_pool", "include", "subroutine_pool")
        sample = [p["NAME"] for p in programs if p.get("type") in eligible_types]

        # If standard filter returns nothing, try ALL programs as last resort
        if not sample:
            logger.warning("[ABAP] No programs matched standard type filter — trying ALL programs")
            print(f"       WARNING: Type filter matched 0 programs — retrying with ALL types")
            sample = [p["NAME"] for p in programs if p.get("NAME", "").strip()]

        if not sample:
            logger.warning("[ABAP] No eligible programs found at all")
            print(f"       WARNING: No eligible programs found for source extraction!")
            return sources

        # Respect --limit if set, otherwise cap at 500
        cap = self._limit if self._limit > 0 else 500
        sample = sample[:cap]

        total = len(sample)
        batch_size = 25
        logger.info(f"[ABAP] Extracting source for {total} programs (cap={cap}) via 3-tier cascade")
        print(f"       Extracting source for {total} programs via 3-tier cascade "
              f"(RPY_PROGRAM_READ → RFC_READ_REPORT → READ_REPORT)...")

        extraction_start = _time.time()

        for batch_start in range(0, total, batch_size):
            batch = sample[batch_start:batch_start + batch_size]
            batch_end = min(batch_start + batch_size, total)
            print(f"       ... batch {batch_start+1}-{batch_end}/{total}")

            for prog_name in batch:
                max_retries = 2
                extracted = False
                for attempt in range(1, max_retries + 1):
                    code, line_count, auth_error = self._read_single_report(prog_name)
                    if auth_error:
                        auth_blocked_programs.append(prog_name)
                        extracted = True  # don't retry auth failures
                        break
                    if code is not None:
                        if not code.strip():
                            logger.warning(f"[ABAP] {prog_name}: {line_count} lines returned but ALL whitespace")
                            print(f"       WARNING: {prog_name} returned {line_count} lines but all whitespace — skipping")
                            whitespace_only_programs.append(prog_name)
                        else:
                            sources[prog_name] = code
                        extracted = True
                        break
                    elif code is None and line_count == 0:
                        if attempt < max_retries:
                            backoff = min(2 ** attempt, 15)
                            logger.warning(f"[ABAP] {prog_name}: empty result, attempt {attempt}/{max_retries} — retry in {backoff}s")
                            _time.sleep(backoff)
                        else:
                            logger.error(f"[ABAP] {prog_name}: FAILED after {max_retries} attempts — all 3 tiers empty")
                            failed_programs.append(prog_name)

                programs_processed += 1
                if programs_processed % 10 == 0 or programs_processed == total:
                    elapsed = _time.time() - extraction_start
                    rate = programs_processed / max(elapsed, 0.01)
                    print(f"       Program {programs_processed}/{total} analyzed "
                          f"({len(sources)} extracted, {elapsed:.1f}s, {rate:.1f} prog/s)")

                # Throttle to avoid ECC gateway overload
                _time.sleep(0.1)

        elapsed_total = _time.time() - extraction_start

        if whitespace_only_programs:
            print(f"       WARNING: {len(whitespace_only_programs)} programs returned whitespace-only source:")
            for p in whitespace_only_programs[:10]:
                print(f"         - {p}")

        if auth_blocked_programs:
            print(f"       🔒 AUTH BLOCKED: {len(auth_blocked_programs)} programs denied by SAP authorization:")
            for p in auth_blocked_programs[:10]:
                print(f"         - {p}")
            print(f"       → Check transactions SU01/SU53 for missing S_DEVELOP, S_PROGNAM objects")

        if failed_programs:
            print(f"       WARNING: {len(failed_programs)} programs failed all 3 extraction tiers:")
            for p in failed_programs[:10]:
                print(f"         - {p}")
            if len(failed_programs) > 10:
                print(f"         ... and {len(failed_programs) - 10} more")

        if total > 0 and len(sources) == 0:
            logger.critical(f"[ABAP] ZERO programs extracted from {total} candidates in {elapsed_total:.1f}s!")
            print(f"       CRITICAL: 0/{total} programs extracted — all 3 tiers returned nothing!")
            if auth_blocked_programs:
                print(f"       → {len(auth_blocked_programs)} were authorization failures — this is likely the root cause!")
        elif elapsed_total < 1.0 and total > 10:
            logger.warning(f"[ABAP] Extraction of {total} programs completed in {elapsed_total:.1f}s — suspiciously fast")
            print(f"       WARNING: Extraction of {total} programs finished in {elapsed_total:.1f}s — verify data is real")

        logger.info(f"[ABAP] Source extraction complete: {len(sources)} succeeded, "
                     f"{len(failed_programs)} failed, {len(auth_blocked_programs)} auth-blocked, "
                     f"{len(whitespace_only_programs)} whitespace-only in {elapsed_total:.1f}s")
        print(f"       Extraction complete: {len(sources)}/{total} programs in {elapsed_total:.1f}s")
        return sources

    def _extract_users(self):
        """Read users from USR02."""
        fields = ["BNAME", "TRDAT", "LTIME", "USTYP", "CLASS", "GLTGV", "GLTGB"]
        rows = self._read_table_chunked("USR02", fields)
        return rows
