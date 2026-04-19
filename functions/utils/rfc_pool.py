"""
RFC Connection Pool — Thread-safe SAP RFC connection management
================================================================
Prevents SAP Gateway bottlenecks by reusing RFC connections across
function invocations within the same execution environment.

Without pooling, each function call opens a new RFC connection which:
- Causes SAP Gateway saturation (max ~100 concurrent connections per instance)
- Adds 200-500ms latency per connection handshake
- Can trigger SAP ICM watchdog alerts (looks like a DDoS)

Usage:
    from rfc_pool import RFCConnectionPool

    pool = RFCConnectionPool(max_connections=5)
    with pool.get_connection(secret_name="sap-ecc-credentials") as conn:
        result = conn.call("RFC_READ_TABLE", QUERY_TABLE="T001")
"""

import threading
import time
import logging
import json
import os
from collections import deque
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

logger = logging.getLogger(__name__)

try:
    from pyrfc import Connection as RFCConnection
    PYRFC_AVAILABLE = True
except ImportError:
    PYRFC_AVAILABLE = False
    logger.warning("pyrfc not available — connection pool will use mock connections")


class _MockConnection:
    """Lightweight mock RFC connection for development/testing."""

    def __init__(self, **kwargs):
        self._alive = True
        self._call_count = 0
        self._committed = 0

    def call(self, func_name, **kwargs):
        self._call_count += 1
        if func_name == "RFC_SYSTEM_INFO":
            return {"RFCSI_EXPORT": {"RFCSYSID": "BIS", "RFCHOST": "mock", "RFCSAPRL": "750"}}
        if func_name == "RFC_PING":
            return {}
        if func_name == "BAPI_TRANSACTION_COMMIT":
            self._committed += 1
            return {"RETURN": []}
        if func_name == "RFC_READ_TABLE":
            return {"DATA": [], "FIELDS": []}
        return {"RETURN": [{"TYPE": "S", "MESSAGE": f"Mock: {func_name} executed"}]}

    def close(self):
        self._alive = False

    @property
    def alive(self):
        return self._alive


class _PooledConnection:
    """Wrapper that tracks connection metadata for the pool."""

    __slots__ = ("connection", "created_at", "last_used", "use_count", "_params_hash")

    def __init__(self, connection, params_hash: str):
        self.connection = connection
        self.created_at = time.monotonic()
        self.last_used = time.monotonic()
        self.use_count = 0
        self._params_hash = params_hash

    def is_healthy(self, max_age_seconds: int = 300) -> bool:
        """Check if connection is still usable."""
        # Too old
        if time.monotonic() - self.created_at > max_age_seconds:
            return False
        # Ping check
        try:
            self.connection.call("RFC_PING")
            return True
        except Exception:
            return False

    def touch(self):
        self.last_used = time.monotonic()
        self.use_count += 1


class RFCConnectionPool:
    """
    Thread-safe RFC connection pool with health checking and auto-reconnection.

    Features:
    - Configurable max connections per SAP system
    - Health-check via RFC_PING before returning a connection
    - Max connection age (default 5 min) to prevent stale connections
    - Thread-safe borrow/return with Lock
    - Automatic cleanup of dead connections
    - Graceful fallback to mock connections when PyRFC unavailable

    Args:
        max_connections: Maximum connections per SAP system (default: 5)
        max_age_seconds: Recycle connections older than this (default: 300s)
        connect_timeout: Seconds to wait for a free connection (default: 30)
    """

    def __init__(
        self,
        max_connections: int = 5,
        max_age_seconds: int = 300,
        connect_timeout: int = 30,
    ):
        self._max_connections = max_connections
        self._max_age = max_age_seconds
        self._connect_timeout = connect_timeout
        self._lock = threading.Lock()
        # Keyed by params hash → deque of _PooledConnection
        self._available: dict[str, deque] = {}
        self._in_use: dict[str, set] = {}
        self._params_cache: dict[str, dict] = {}
        self._secret_cache: dict[str, tuple] = {}  # secret_arn → (params, fetched_at)
        self._stats = {"connections_created": 0, "connections_reused": 0,
                       "connections_recycled": 0, "health_check_failures": 0}

    def _resolve_params(self, secret_name: str = "", conn_params: dict = None) -> dict:
        """Resolve connection parameters from Azure Key Vault or direct dict.
        
        Caches secrets for up to max_age seconds, then re-fetches to pick up
        rotated credentials automatically.
        """
        if conn_params:
            return conn_params

        if not secret_name:
            raise ValueError("Either secret_name or conn_params must be provided")

        # Check cache — re-fetch if older than max_age
        cached = self._secret_cache.get(secret_name)
        if cached:
            params, fetched_at = cached
            if time.monotonic() - fetched_at < self._max_age:
                return params

        from utils.secrets_client import get_secret_value
        secret = json.loads(
            get_secret_value(secret_name)["SecretString"]
        )
        self._secret_cache[secret_name] = (secret, time.monotonic())
        return secret

    def _params_hash(self, params: dict) -> str:
        """Create a stable hash for connection parameters (excluding password)."""
        key_parts = [
            params.get("ashost", ""),
            params.get("sysnr", ""),
            params.get("client", ""),
            params.get("user", ""),
        ]
        return "|".join(key_parts)

    def _create_connection(self, params: dict, params_key: str) -> _PooledConnection:
        """Create a new RFC connection."""
        if PYRFC_AVAILABLE:
            conn = RFCConnection(**params)
        else:
            conn = _MockConnection(**params)

        self._stats["connections_created"] += 1
        return _PooledConnection(conn, params_key)

    @contextmanager
    def get_connection(self, secret_name: str = "", conn_params: dict = None):
        """
        Borrow a healthy RFC connection from the pool.

        Usage:
            with pool.get_connection(secret_name="sap-ecc-credentials") as conn:
                result = conn.call("RFC_READ_TABLE", QUERY_TABLE="T001")

        The connection is automatically returned to the pool on exit.
        If the connection raises an exception, it is discarded (not returned).
        On auth failure, credentials are re-fetched and a fresh connection is tried once.
        """
        params = self._resolve_params(secret_name, conn_params)
        params_key = self._params_hash(params)

        # Cache params for reconnection
        self._params_cache[params_key] = params

        pooled_conn = self._borrow(params_key, params)
        try:
            yield pooled_conn.connection
            # Return healthy connection to pool
            self._return(pooled_conn)
        except Exception as exc:
            # Connection may be broken — discard it
            self._discard(pooled_conn)
            # On auth failure, invalidate cached secret and retry once
            exc_msg = str(exc).upper()
            if secret_arn and ("LOGON" in exc_msg or "PASSWORD" in exc_msg or "AUTHORIZATION" in exc_msg):
                logger.warning("Auth failure detected — refreshing credentials and retrying")
                self._secret_cache.pop(secret_arn, None)
                fresh_params = self._resolve_params(secret_arn)
                fresh_key = self._params_hash(fresh_params)
                self._params_cache[fresh_key] = fresh_params
                fresh_conn = self._borrow(fresh_key, fresh_params)
                try:
                    yield fresh_conn.connection
                    self._return(fresh_conn)
                    return
                except Exception:
                    self._discard(fresh_conn)
                    raise
            raise

    def _borrow(self, params_key: str, params: dict) -> _PooledConnection:
        """Borrow a connection, creating one if necessary."""
        deadline = time.monotonic() + self._connect_timeout

        while True:
            with self._lock:
                # Initialize pool structures for this system
                if params_key not in self._available:
                    self._available[params_key] = deque()
                    self._in_use[params_key] = set()

                # Try to reuse an existing idle connection
                while self._available[params_key]:
                    candidate = self._available[params_key].popleft()
                    if candidate.is_healthy(self._max_age):
                        candidate.touch()
                        self._in_use[params_key].add(id(candidate))
                        self._stats["connections_reused"] += 1
                        return candidate
                    else:
                        # Stale or dead — close and discard
                        self._stats["connections_recycled"] += 1
                        try:
                            candidate.connection.close()
                        except Exception:
                            pass

                # Check if we can create a new one
                total = len(self._available[params_key]) + len(self._in_use[params_key])
                if total < self._max_connections:
                    conn = self._create_connection(params, params_key)
                    conn.touch()
                    self._in_use[params_key].add(id(conn))
                    return conn

            # Pool is full — wait and retry
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"RFC connection pool exhausted (max={self._max_connections}, "
                    f"in_use={len(self._in_use.get(params_key, set()))}). "
                    f"Increase max_connections or check for connection leaks."
                )
            time.sleep(0.1)

    def _return(self, pooled_conn: _PooledConnection):
        """Return a connection to the pool."""
        with self._lock:
            key = pooled_conn._params_hash
            self._in_use.get(key, set()).discard(id(pooled_conn))
            if key in self._available:
                self._available[key].append(pooled_conn)

    def _discard(self, pooled_conn: _PooledConnection):
        """Discard a broken connection."""
        with self._lock:
            key = pooled_conn._params_hash
            self._in_use.get(key, set()).discard(id(pooled_conn))
        try:
            pooled_conn.connection.close()
        except Exception:
            pass
        self._stats["health_check_failures"] += 1

    def close_all(self):
        """Close all pooled connections. Call during Lambda shutdown."""
        with self._lock:
            for key in list(self._available.keys()):
                while self._available[key]:
                    pooled = self._available[key].popleft()
                    try:
                        pooled.connection.close()
                    except Exception:
                        pass
            self._available.clear()
            self._in_use.clear()

    @property
    def stats(self) -> dict:
        """Return pool usage statistics."""
        with self._lock:
            total_available = sum(len(q) for q in self._available.values())
            total_in_use = sum(len(s) for s in self._in_use.values())
        return {
            **self._stats,
            "connections_available": total_available,
            "connections_in_use": total_in_use,
            "systems_tracked": len(self._available),
        }

    def __repr__(self):
        s = self.stats
        return (
            f"RFCConnectionPool(max={self._max_connections}, "
            f"available={s['connections_available']}, in_use={s['connections_in_use']}, "
            f"created={s['connections_created']}, reused={s['connections_reused']})"
        )


# =============================================================================
# MODULE-LEVEL SINGLETON
# =============================================================================
# Lambda reuses execution environments, so a module-level pool persists
# across warm invocations (typically 5-15 min). This is the key optimization.
_DEFAULT_POOL = None


def get_pool(max_connections: int = 5) -> RFCConnectionPool:
    """Get the module-level connection pool singleton."""
    global _DEFAULT_POOL
    if _DEFAULT_POOL is None:
        _DEFAULT_POOL = RFCConnectionPool(max_connections=max_connections)
    return _DEFAULT_POOL


# =============================================================================
# RFC CALL TIMEOUT WRAPPER
# =============================================================================
# pyrfc has no native per-call timeout. This uses a thread pool future
# so that a hanging RFC call (e.g. SAP Gateway overload) doesn't consume
# the entire Lambda execution window.

# Default timeout in seconds — overridable via env var
RFC_CALL_TIMEOUT = int(os.environ.get("RFC_CALL_TIMEOUT_SECONDS", "120"))

_rfc_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rfc_timeout")


def call_rfc_with_timeout(conn, func_name: str, timeout: int = None, **kwargs):
    """
    Call an RFC function with a timeout guard.

    Args:
        conn: pyrfc Connection (or mock).
        func_name: SAP function module name.
        timeout: Seconds to wait before aborting (default: RFC_CALL_TIMEOUT).
        **kwargs: Parameters forwarded to conn.call().

    Returns:
        The RFC call result dict.

    Raises:
        TimeoutError: If the call exceeds the timeout.
    """
    if timeout is None:
        timeout = RFC_CALL_TIMEOUT

    future = _rfc_executor.submit(conn.call, func_name, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeout:
        logger.error(f"RFC call {func_name} timed out after {timeout}s")
        raise TimeoutError(f"RFC call {func_name} exceeded {timeout}s timeout")


# =============================================================================
# PAGINATED RFC_READ_TABLE
# =============================================================================
# SAP RFC_READ_TABLE returns all rows in one shot. For large tables this
# can OOM the application server or hit the 512 KB response limit.
# This helper paginates via ROWSKIPS / ROWCOUNT.

DEFAULT_PAGE_SIZE = int(os.environ.get("RFC_PAGE_SIZE", "5000"))


def read_table_chunked(conn, query_table: str, fields: list, options: list = None,
                       delimiter: str = "|", page_size: int = None,
                       max_rows: int = 0, timeout: int = None):
    """
    Paginated RFC_READ_TABLE reader.

    Yields pages of rows (list[dict]) so callers can stream-process
    without loading the full result set into memory.

    Args:
        conn: RFC connection.
        query_table: SAP table name.
        fields: List of FIELDNAME dicts, e.g. [{"FIELDNAME": "MATNR"}].
        options: WHERE clause dicts, e.g. [{"TEXT": "MATNR LIKE 'Z%'"}].
        delimiter: Field delimiter (default "|").
        page_size: Rows per RFC call (default DEFAULT_PAGE_SIZE).
        max_rows: Stop after this many total rows (0 = unlimited).
        timeout: Per-call timeout in seconds.

    Yields:
        list[dict]: Each element is {"WA": "<delimited row>"} — same as
        RFC_READ_TABLE DATA output.
    """
    if page_size is None:
        page_size = DEFAULT_PAGE_SIZE
    if options is None:
        options = []

    offset = 0
    total_fetched = 0

    while True:
        effective_count = page_size
        if max_rows > 0:
            remaining = max_rows - total_fetched
            if remaining <= 0:
                break
            effective_count = min(page_size, remaining)

        result = call_rfc_with_timeout(
            conn, "RFC_READ_TABLE",
            timeout=timeout,
            QUERY_TABLE=query_table,
            DELIMITER=delimiter,
            FIELDS=fields,
            OPTIONS=options,
            ROWSKIPS=offset,
            ROWCOUNT=effective_count,
        )

        rows = result.get("DATA", [])
        if not rows:
            break

        yield rows

        total_fetched += len(rows)
        offset += len(rows)

        # If we got fewer rows than requested, we've reached the end
        if len(rows) < effective_count:
            break
