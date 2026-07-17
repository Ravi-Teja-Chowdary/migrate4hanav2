"""
rfc_session — resilient pyrfc connection wrapper (H0.3).

A migration run holds RFC sessions for minutes to hours; SAP gateways, CAL
suspensions, and network blips drop them mid-run (seen live 2026-07-14/16:
`RFC_COMMUNICATION_FAILURE` / "connection closed"). This wrapper transparently
re-dials on a *transport* failure with capped exponential backoff, so a blip
self-heals instead of failing the run.

Critical safety rule: only **transport/communication** failures are retried.
An ABAP application error, an ABAP runtime error, or a logon failure is a real
result and must propagate immediately — reconnecting would either mask a genuine
business error or hammer a system with bad credentials.

Usage — drop-in for pyrfc.Connection:

    from rfc_session import ResilientRfc
    conn = ResilientRfc(dict(ashost=..., sysnr=..., client=..., user=..., passwd=...))
    conn.call("BAPI_...", ...)      # auto-reconnects + retries on a dropped link
    conn.close()

Or as the connection FACTORY the loaders already accept:

    loader.target_conn_factory = lambda: ResilientRfc(params)

The wrapper proxies `.call()`, `.close()`, `.get_connection_attributes()`, and
`.ping()`; any other attribute passes through to the live connection.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Exception *type names* that are real results — never reconnect/retry on these.
_NON_RETRYABLE_TYPES = frozenset({
    "ABAPApplicationError", "ABAPRuntimeError", "LogonError",
})
# Substrings that mark a transport/link failure (lower-cased match).
_RETRYABLE_HINTS = (
    "rfc_communication_failure", "connection closed", "connection is closed",
    "connection reset", "broken pipe", "timed out", "timeout", "network error",
    "no connection", "partner not reached", "connection to partner",
)


def _classify_retryable(exc: BaseException) -> bool:
    name = type(exc).__name__
    if name in _NON_RETRYABLE_TYPES:
        return False
    if name == "CommunicationError":
        return True
    msg = str(exc).lower()
    return any(h in msg for h in _RETRYABLE_HINTS)


class ResilientRfc:
    """A pyrfc.Connection that re-dials on transport failures.

    :param params: kwargs for pyrfc.Connection (ashost, sysnr, client, user, passwd, lang, ...)
    :param max_retries: reconnect attempts per call before giving up (default 4)
    :param backoff_base: seconds; wait = min(cap, base * 2**attempt). Pass 0 in tests.
    :param backoff_cap: max seconds between attempts
    :param connection_factory: test seam — returns an object with .call()/.close()
    :param sleep: test seam — defaults to time.sleep
    """

    def __init__(self, params: dict, *, max_retries: int = 4,
                 backoff_base: float = 2.0, backoff_cap: float = 30.0,
                 connection_factory: Optional[Callable[[], object]] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self._params = dict(params or {})
        self._max_retries = int(max_retries)
        self._backoff_base = float(backoff_base)
        self._backoff_cap = float(backoff_cap)
        self._factory = connection_factory or self._default_factory
        self._sleep = sleep
        self._conn = None
        self._reconnects = 0
        self._open()

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def _default_factory(self):
        from pyrfc import Connection  # lazy: import/test without pyrfc installed
        return Connection(**self._params)

    def _open(self):
        self._conn = self._factory()

    def _safe_close(self):
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:  # noqa: BLE001 — closing a dead handle can itself throw
            pass
        self._conn = None

    def close(self):
        self._safe_close()

    # ── the resilient call ─────────────────────────────────────────────────────
    def call(self, fm: str, **kwargs):
        attempt = 0
        while True:
            try:
                if self._conn is None:
                    self._open()
                return self._conn.call(fm, **kwargs)
            except Exception as e:  # noqa: BLE001
                if attempt >= self._max_retries or not _classify_retryable(e):
                    raise
                wait = min(self._backoff_cap, self._backoff_base * (2 ** attempt))
                logger.warning(
                    "RFC transport failure on %s (%s: %s) — reconnect %d/%d in %.1fs",
                    fm, type(e).__name__, str(e)[:100], attempt + 1,
                    self._max_retries, wait)
                self._safe_close()
                if wait:
                    self._sleep(wait)
                try:
                    self._open()
                    self._reconnects += 1
                except Exception as reopen_err:  # noqa: BLE001
                    # Reopen failed too; leave _conn None and let the next loop
                    # iteration back off + retry until max_retries is hit.
                    logger.warning("reconnect attempt %d failed: %s",
                                   attempt + 1, str(reopen_err)[:100])
                    self._conn = None
                attempt += 1

    # ── proxying ──────────────────────────────────────────────────────────────
    def get_connection_attributes(self):
        return self._conn.get_connection_attributes() if self._conn else {}

    def ping(self):
        if hasattr(self._conn, "ping"):
            return self._conn.ping()
        return None

    @property
    def reconnects(self) -> int:
        return self._reconnects

    def __getattr__(self, name):
        # Only reached for attributes not defined on the wrapper — pass through
        # to the live connection (e.g. any pyrfc method we didn't wrap).
        conn = self.__dict__.get("_conn")
        if conn is None:
            raise AttributeError(name)
        return getattr(conn, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
