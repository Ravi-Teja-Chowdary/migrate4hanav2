"""
hana_staging — direct SAP HANA staging-table ingestion layer (MC-1).

The Migration Cockpit "Staging Tables (Remote SAP HANA Database Schema)" method
lets an external ETL tool write transformed source rows straight into the target
HANA staging tables, bypassing the file-upload path (and its 100 MB / ZIP cap).
This module is migrate4hana acting as that ETL tool.

Connection facts verified live on the S/4 2020 CAL (2026-07-17):
  * driver: `hdbcli` (SAP HANA Python client)
  * tenant DB SQL port = 3<hana_sysnr>15  (e.g. 30215 for sysnr 02)
  * SYSTEMDB SQL port   = 3<hana_sysnr>13
  * the CAL SQL listener is PLAINTEXT (encrypt=True gave RTE -10709 "Invalid
    flags"); production HANA is typically TLS, so `encrypt` is configurable.
  * credentials come from the connections.json `lift_and_shift_target` hana_*
    profile + the `M4H_HANA_PASSWD` env var (never persisted — same policy as
    the SAP RFC passwords).

MC-1.1 = connect + round-trip (this file's connect()/current_user()).
MC-1.2 = describe_staging() — discover a migration object's staging table(s)
         and typed columns from the HANA catalog (names are release-specific).
MC-1.3 = load_staging() — bulk-insert transformed rows (see MC-2.3 lane).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_CONNECT_TIMEOUT_MS = 15000


class HanaStagingError(RuntimeError):
    pass


def sql_port(hana_sysnr: str, *, systemdb: bool = False) -> int:
    """Tenant DB SQL port 3<nn>15, or SYSTEMDB 3<nn>13."""
    nn = str(hana_sysnr or "02").zfill(2)
    return int(f"3{nn}{'13' if systemdb else '15'}")


class HanaStaging:
    """Thin, resilient-ish wrapper over an hdbcli connection to the target HANA.

    Params come from the `lift_and_shift_target` profile in connections.json plus
    M4H_HANA_PASSWD. Override any field via the constructor for prod/TLS.
    """

    def __init__(self, profile: dict, *, password: Optional[str] = None,
                 host: Optional[str] = None, port: Optional[int] = None,
                 user: Optional[str] = None, schema: Optional[str] = None,
                 encrypt: Optional[bool] = None,
                 connect_timeout_ms: int = _DEFAULT_CONNECT_TIMEOUT_MS):
        profile = profile or {}
        self.host = host or profile.get("target_public_ip") or profile.get("hana_host")
        self.port = int(port) if port else sql_port(profile.get("hana_sysnr", "02"))
        # Connect user: explicit arg > M4H_HANA_USER env > profile hana_user.
        # NOTE: the profile's hana_user (SAPHANADB) is the ABAP schema OWNER and is
        # typically locked for interactive logon — use SYSTEM (or a dedicated DB
        # user) for external SQL. Set M4H_HANA_USER=SYSTEM for the CAL.
        self.user = user or os.environ.get("M4H_HANA_USER") or profile.get("hana_user", "SAPHANADB")
        self.schema = schema or profile.get("hana_schema", "SAPHANADB")
        self._password = password if password is not None else os.environ.get("M4H_HANA_PASSWD", "")
        # CAL is plaintext; default to env override or False. Set encrypt=True for prod TLS.
        if encrypt is None:
            encrypt = os.environ.get("M4H_HANA_ENCRYPT", "0") == "1"
        self.encrypt = bool(encrypt)
        self._timeout = connect_timeout_ms
        self._conn = None

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def connect(self):
        if self._conn is not None:
            return self._conn
        if not self.host:
            raise HanaStagingError("no HANA host (set connections.json hana_host / target_public_ip)")
        if not self._password:
            raise HanaStagingError("no HANA password (set M4H_HANA_PASSWD)")
        try:
            from hdbcli import dbapi
        except Exception as e:  # noqa: BLE001
            raise HanaStagingError(f"hdbcli not installed: {e}")
        kwargs = dict(address=self.host, port=self.port, user=self.user,
                      password=self._password, connectTimeout=self._timeout)
        if self.encrypt:
            kwargs.update(encrypt=True, sslValidateCertificate=False)
        else:
            kwargs.update(encrypt=False)
        try:
            self._conn = dbapi.connect(**kwargs)
        except Exception as e:  # noqa: BLE001
            raise HanaStagingError(
                f"HANA connect failed ({self.user}@{self.host}:{self.port}, "
                f"encrypt={self.encrypt}): {type(e).__name__}: {str(e)[:160]}")
        if self.schema:
            try:
                cur = self._conn.cursor()
                cur.execute(f'SET SCHEMA "{self.schema}"')
                cur.close()
            except Exception:  # noqa: BLE001 — non-fatal; queries can qualify names
                pass
        return self._conn

    def close(self):
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:  # noqa: BLE001
            pass
        self._conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # ── MC-1.1: round-trip ─────────────────────────────────────────────────────
    def current_user(self) -> dict:
        cur = self.connect().cursor()
        cur.execute("SELECT CURRENT_USER, CURRENT_SCHEMA FROM DUMMY")
        u, sch = cur.fetchone()
        cur.close()
        return {"current_user": u, "current_schema": sch,
                "host": self.host, "port": self.port}

    # ── MC-1.2: staging-table introspection (release-specific names) ────────────
    def describe_staging(self, table_name: str, schema: Optional[str] = None) -> list:
        """Return [{column, type, length, nullable, position}, ...] for a staging
        table, from the HANA catalog. Table names are discovered (MC-2.1 resolves
        the MC object -> staging table mapping); this reads whichever exists."""
        sch = schema or self.schema
        cur = self.connect().cursor()
        cur.execute(
            "SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH, IS_NULLABLE, POSITION "
            "FROM TABLE_COLUMNS WHERE SCHEMA_NAME = ? AND TABLE_NAME = ? "
            "ORDER BY POSITION", (sch, table_name))
        cols = [{"column": r[0], "type": r[1], "length": r[2],
                 "nullable": r[3] == "TRUE", "position": r[4]} for r in cur.fetchall()]
        cur.close()
        return cols

    def find_staging_tables(self, name_like: str, schema: Optional[str] = None,
                            limit: int = 50) -> list:
        """Discover candidate staging tables by name pattern (MC-1.2 helper).
        MC staging tables vary by release (e.g. '/1LT/DS*' or a project schema);
        this lets the orchestrator locate them without hardcoding."""
        sch = schema or self.schema
        cur = self.connect().cursor()
        cur.execute(
            "SELECT SCHEMA_NAME, TABLE_NAME FROM TABLES "
            "WHERE SCHEMA_NAME = ? AND TABLE_NAME LIKE ? "
            "ORDER BY TABLE_NAME LIMIT ?", (sch, name_like, limit))
        out = [{"schema": r[0], "table": r[1]} for r in cur.fetchall()]
        cur.close()
        return out


def from_connections(conns: dict, **overrides) -> HanaStaging:
    """Build a HanaStaging from a loaded connections.json dict."""
    profile = (conns or {}).get("lift_and_shift_target") or {}
    return HanaStaging(profile, **overrides)
