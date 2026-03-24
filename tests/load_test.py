"""
load_test.py — Locust load testing for Migrate4HANA API & Pipeline
===================================================================
Simulates concurrent users hitting the API server and triggering
pipeline executions to establish the performance envelope.

Usage:
    # Install Locust
    pip install locust

    # Run against local API server
    locust -f tests/load_test.py --host=http://localhost:8000

    # Run headless (CI-friendly)
    locust -f tests/load_test.py --host=http://localhost:8000 \
        --headless -u 50 -r 5 --run-time 5m \
        --csv=test-output/load-test

    # Run against deployed API
    locust -f tests/load_test.py --host=https://api.migrate4hana.internal \
        --headless -u 100 -r 10 --run-time 10m \
        --csv=test-output/load-test
"""

import json
import os

from locust import HttpUser, task, between, tag


# JWT token — set via environment or generate with: python api_server.py --generate-token
API_TOKEN = os.environ.get("M4H_API_TOKEN", "")
API_KEY = os.environ.get("M4H_API_KEY", "test-key")


class Migrate4HANAUser(HttpUser):
    """Simulates a user interacting with the Migrate4HANA API."""

    wait_time = between(1, 3)

    def on_start(self):
        """Authenticate on session start."""
        self.headers = {}
        if API_TOKEN:
            self.headers["Authorization"] = f"Bearer {API_TOKEN}"
        elif API_KEY:
            self.headers["X-API-Key"] = API_KEY
        else:
            # Try to get a token
            resp = self.client.post(
                "/api/auth/token",
                json={"username": "admin", "password": "admin"},
            )
            if resp.status_code == 200:
                token = resp.json().get("token", "")
                self.headers["Authorization"] = f"Bearer {token}"

    # ── Health & Status (high frequency) ─────────────────
    @tag("health")
    @task(10)
    def health_check(self):
        self.client.get("/api/health")

    @tag("status")
    @task(5)
    def get_status(self):
        self.client.get("/api/status", headers=self.headers)

    # ── Run Management (medium frequency) ────────────────
    @tag("runs")
    @task(3)
    def list_runs(self):
        self.client.get("/api/runs", headers=self.headers)

    @tag("connections")
    @task(2)
    def get_connections(self):
        self.client.get("/api/connections", headers=self.headers)

    # ── Pipeline Trigger (low frequency) ─────────────────
    @tag("pipeline")
    @task(1)
    def trigger_assessment(self):
        self.client.post(
            "/api/pipeline/assess",
            json={"phases": ["PREPARE"]},
            headers=self.headers,
        )


class Migrate4HANAHeavyUser(HttpUser):
    """Simulates a power user running full pipelines and downloading reports."""

    wait_time = between(5, 15)

    def on_start(self):
        self.headers = {}
        if API_TOKEN:
            self.headers["Authorization"] = f"Bearer {API_TOKEN}"
        elif API_KEY:
            self.headers["X-API-Key"] = API_KEY

    @tag("pipeline")
    @task(1)
    def full_pipeline(self):
        self.client.post(
            "/api/pipeline/full",
            json={"mode": "full", "ecc_client": "100", "execute": False},
            headers=self.headers,
        )

    @tag("runs")
    @task(2)
    def get_run_detail(self):
        resp = self.client.get("/api/runs", headers=self.headers)
        if resp.status_code == 200:
            runs = resp.json()
            if isinstance(runs, list) and runs:
                run_id = runs[0].get("run_id", runs[0].get("id", ""))
                if run_id:
                    self.client.get(
                        f"/api/runs/{run_id}", headers=self.headers
                    )

    @tag("connections")
    @task(1)
    def test_ecc_connection(self):
        self.client.post(
            "/api/connections/ecc/test",
            json={
                "host": "10.10.1.100",
                "sysnr": "00",
                "client": "100",
                "user": "RFC_USER",
                "passwd": "test",
            },
            headers=self.headers,
        )
