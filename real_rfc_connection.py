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
from datetime import datetime


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

    def __init__(self, conn_params):
        """
        conn_params: dict with keys ashost, sysnr, client, user, passwd,
                     and optionally saprouter.
        """
        clean = {k: v for k, v in conn_params.items() if v}
        self._pyrfc = pyrfc.Connection(**clean)
        self._call_count = 0

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

    # ── Data extraction ─────────────────────────────────────────────────

    def _read_table(self, table, fields=None, options=None, max_rows=0):
        """Wrapper around RFC_READ_TABLE with chunked reads for large tables."""
        params = {"QUERY_TABLE": table, "DELIMITER": "|"}
        if fields:
            params["FIELDS"] = [{"FIELDNAME": f} for f in fields]
        if options:
            params["OPTIONS"] = [{"TEXT": t} for t in options]
        if max_rows:
            params["ROWCOUNT"] = max_rows
        try:
            result = self._pyrfc.call("RFC_READ_TABLE", **params)
            return _parse_rfc_read_table(result)
        except Exception as e:
            print(f"    [RFC] Warning: Could not read {table}: {e}")
            return []

    def _extract_all(self):
        """Extract all ECC data into the standard dataset format."""
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

        print("    -> ABAP source code (RPY_PROGRAM_READ)...")
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
        rows = self._read_table_chunked("TRDIR", fields, options)

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
            ["BUKRS", "BUTXT", "WAERS", "LAND1", "ORT01", "KTOPL", "PERIV"])

        plants = self._read_table("T001W",
            ["WERKS", "NAME1", "BUKRS", "LAND1", "FABKL", "ORT01"])

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
        """Read customers from KNA1."""
        fields = ["KUNNR", "NAME1", "LAND1", "STCD1", "SMTP_ADDR", "TELF1", "KTOKD"]
        rows = self._read_table_chunked("KNA1", fields)
        return rows

    def _extract_vendors(self):
        """Read vendors from LFA1."""
        fields = ["LIFNR", "NAME1", "LAND1", "STCD1", "SMTP_ADDR", "KTOKK"]
        rows = self._read_table_chunked("LFA1", fields)
        return rows

    def _extract_finance(self):
        """Read finance doc headers (BKPF) and line items (BSEG) — sampled."""
        bkpf_fields = ["BUKRS", "BELNR", "GJAHR", "BLART", "BUDAT", "USNAM", "WAERS"]
        bkpf = self._read_table_chunked("BKPF", bkpf_fields, max_rows=10000)

        bseg_fields = ["BUKRS", "BELNR", "GJAHR", "BUZEI", "KOART", "HKONT",
                        "DMBTR", "WRBTR", "SHKZG"]
        bseg = self._read_table_chunked("BSEG", bseg_fields, max_rows=50000)

        return {"bkpf": bkpf, "bseg": bseg}

    def _read_table_chunked(self, table, fields=None, options=None,
                             chunk_size=5000, max_rows=0):
        """Read large tables in chunks. If max_rows > 0, stop after that many."""
        all_rows = []
        skip = 0
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
            try:
                result = self._pyrfc.call("RFC_READ_TABLE", **params)
                rows = _parse_rfc_read_table(result)
                if not rows:
                    break
                all_rows.extend(rows)
                if len(rows) < fetch:
                    break
                skip += fetch
            except Exception as e:
                print(f"    [RFC] Warning: Chunk read of {table} failed at offset {skip}: {e}")
                break
        return all_rows

    def _extract_abap_source(self, programs):
        """Read source code for custom programs via RPY_PROGRAM_READ."""
        sources = {}
        # Read source for a sample of programs (reading all can be slow)
        sample = [p["NAME"] for p in programs if p.get("type") in
                  ("report", "module_pool", "include")]
        # Cap at 200 programs to keep extraction time reasonable
        sample = sample[:200]

        for prog_name in sample:
            try:
                result = self._pyrfc.call("RPY_PROGRAM_READ",
                                           PROGRAM_NAME=prog_name,
                                           WITH_LOWERCASE="X")
                lines = result.get("PROG_SOURCE", [])
                if lines:
                    sources[prog_name] = "\n".join(
                        line.get("LINE", "") for line in lines)
            except Exception:
                pass  # Skip programs we can't read
        return sources

    def _extract_users(self):
        """Read users from USR02."""
        fields = ["BNAME", "TRDAT", "LTIME", "USTYP", "CLASS", "GLTGV", "GLTGB"]
        rows = self._read_table_chunked("USR02", fields)
        return rows
