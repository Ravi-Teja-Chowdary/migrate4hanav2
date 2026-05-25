"""
odata_client — minimal S/4 OData (gateway) client over HTTPS.

The RFC surface can't create transaction-ready customers/vendors here (S/4 is BP/CVI-led,
external numbering; classic create BAPIs blocked, EI APIs not RFC-callable — see
partner-readiness-cvi memory). The SAP-supported way is the OData gateway: the released
API_BUSINESS_PARTNER service creates BP-led customers/suppliers WITH company-code/sales/
purchasing facets, honoring CVI numbering, fully support-clean. That runs over HTTPS:44300
with basic auth + CSRF — a different door than RFC, which is exactly why it works.

This client handles: basic auth, self-signed appliance cert, CSRF fetch/reuse, JSON
GET/POST, and the sap-client param. Mechanism-agnostic; callers build the payloads.
"""
from __future__ import annotations
import json

try:
    import requests
    import urllib3
    urllib3.disable_warnings()
except Exception:  # pragma: no cover
    requests = None


class ODataError(Exception):
    def __init__(self, status, message, body=None):
        super().__init__(f"OData {status}: {message}")
        self.status = status
        self.body = body


class ODataClient:
    def __init__(self, host: str, user: str, passwd: str, client: str = "100",
                 port: int = 44300, verify: bool = False, timeout: int = 120):
        if requests is None:
            raise RuntimeError("python 'requests' not available for OData")
        self.base = f"https://{host}:{port}/sap/opu/odata/sap"
        self.client = client
        self.timeout = timeout
        self.s = requests.Session()
        self.s.auth = (user, passwd)
        self.s.verify = verify
        self._token = None

    # ── low level ────────────────────────────────────────────────────────────
    def _params(self, extra=None):
        p = {"sap-client": self.client, "$format": "json"}
        if extra:
            p.update(extra)
        return p

    def fetch_csrf(self, service: str):
        """Fetch a CSRF token (+ session cookies) for write calls."""
        r = self.s.get(f"{self.base}/{service}/",
                       headers={"X-CSRF-Token": "Fetch", "Accept": "application/json"},
                       params={"sap-client": self.client}, timeout=self.timeout)
        self._token = r.headers.get("x-csrf-token") or r.headers.get("X-CSRF-Token")
        return self._token, r.status_code

    def get(self, service: str, path: str, params=None):
        r = self.s.get(f"{self.base}/{service}/{path}",
                       headers={"Accept": "application/json"},
                       params=self._params(params), timeout=self.timeout)
        return r

    def post(self, service: str, entityset: str, payload: dict):
        """Create an entity (deep-insert supported via nested payload). Auto-fetches
        a CSRF token on first write and once on a 403 token-expiry retry."""
        if not self._token:
            self.fetch_csrf(service)
        for attempt in (1, 2):
            h = {"X-CSRF-Token": self._token or "", "Content-Type": "application/json",
                 "Accept": "application/json"}
            r = self.s.post(f"{self.base}/{service}/{entityset}", headers=h,
                            params={"sap-client": self.client},
                            data=json.dumps(payload), timeout=self.timeout)
            if r.status_code == 403 and "csrf" in (r.headers.get("x-csrf-token", "") + r.text).lower() and attempt == 1:
                self.fetch_csrf(service)   # token expired — refresh once
                continue
            return r
        return r

    @staticmethod
    def error_messages(resp) -> list:
        """Pull human-readable error text out of an OData JSON/XML error body."""
        try:
            d = resp.json().get("error", {})
            msgs = [d.get("message", {}).get("value", "")]
            for e in d.get("innererror", {}).get("errordetails", []) or []:
                if e.get("message"):
                    msgs.append(e["message"])
            return [m for m in msgs if m]
        except Exception:
            return [resp.text[:300]]
