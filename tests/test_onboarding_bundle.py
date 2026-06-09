"""
Unit tests for the WS3 onboarding bundle generator.

Validates the bundle contents (4 files: .ovpn, .csv, README, manifest.json),
the templating logic, and the API Gateway / direct-invoke dual-shape handler.
"""
from __future__ import annotations
import sys, json, base64, io, tarfile, csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "lambda" / "onboarding-bundle"))


# Mock S3 BEFORE importing handler
class FakeS3:
    def __init__(self):
        self.objects = {}
        self.presigned = "https://s3.amazonaws.com/test-bucket/presigned-test"

    class exceptions:
        class NoSuchKey(Exception): pass

    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"{self.presigned}?expires={ExpiresIn}"


import handler as ob  # noqa
_fake_s3 = FakeS3()
ob.S3 = _fake_s3


VALID_PAYLOAD = {
    "tenant_id":          "acme-corp",
    "vpn_endpoint_id":    "cvpn-endpoint-0123456789abcdef0",
    "vpn_dns_name":       "cvpn-endpoint-0.prod.clientvpn.us-east-1.amazonaws.com",
    "client_cidr":        "10.99.0.0/22",
    "service_vpc_cidr":   "10.30.0.0/16",
    "customer_subnet":    "172.16.0.0/12",
    "client_certificate": base64.b64encode(b"-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----").decode(),
    "client_key":         base64.b64encode(b"-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----").decode(),
}


def _extract_bundle(bundle_bytes):
    """Read the tarball back into a name -> contents dict."""
    out = {}
    with tarfile.open(fileobj=io.BytesIO(bundle_bytes), mode="r:gz") as tar:
        for member in tar:
            f = tar.extractfile(member)
            if f:
                out[member.name] = f.read().decode("utf-8")
    return out


# ─────────────────────────────────────────────────────────────────────────────
def test_validate_rejects_missing_required_fields():
    err = ob._validate_payload({"tenant_id": "x"})
    assert err and "missing" in err
    print("  [OK] validator rejects payload missing required fields")


def test_validate_accepts_full_payload():
    err = ob._validate_payload(VALID_PAYLOAD)
    assert err == ""
    print("  [OK] validator accepts full payload")


def test_build_bundle_contains_4_files():
    out = _extract_bundle(ob._build_bundle(VALID_PAYLOAD))
    expected = {f"{VALID_PAYLOAD['tenant_id']}.ovpn", "firewall-routing.csv",
                 "README.md", "manifest.json"}
    assert set(out.keys()) == expected
    print("  [OK] bundle contains exactly 4 files (.ovpn / .csv / README / manifest)")


def test_ovpn_includes_vpn_dns_and_endpoint_id():
    out = _extract_bundle(ob._build_bundle(VALID_PAYLOAD))
    ovpn = out[f"{VALID_PAYLOAD['tenant_id']}.ovpn"]
    assert VALID_PAYLOAD["vpn_dns_name"] in ovpn
    assert VALID_PAYLOAD["vpn_endpoint_id"] in ovpn
    assert VALID_PAYLOAD["tenant_id"] in ovpn
    assert "AES-256-GCM" in ovpn
    print("  [OK] .ovpn includes vpn_dns_name + endpoint_id + AES-256-GCM cipher")


def test_ovpn_decodes_base64_pem_blocks():
    out = _extract_bundle(ob._build_bundle(VALID_PAYLOAD))
    ovpn = out[f"{VALID_PAYLOAD['tenant_id']}.ovpn"]
    # The base64-encoded cert in VALID_PAYLOAD decodes to a string containing
    # "BEGIN CERTIFICATE" -- check it landed in the ovpn rendered output.
    assert "BEGIN CERTIFICATE" in ovpn
    assert "BEGIN PRIVATE KEY" in ovpn
    print("  [OK] .ovpn decodes base64-wrapped PEM blocks into raw cert text")


def test_firewall_csv_has_8_columns_and_routing_rows():
    out = _extract_bundle(ob._build_bundle(VALID_PAYLOAD))
    body = out["firewall-routing.csv"]
    rows = list(csv.reader(io.StringIO(body)))
    header = rows[0]
    assert header == ["tier", "src_cidr", "dst_cidr", "port_from",
                       "port_to", "protocol", "direction", "description"]
    # At least 6 routing rules across edge/bastion/data/telemetry tiers
    data_rows = rows[1:]
    tiers = {r[0] for r in data_rows}
    assert tiers == {"edge", "bastion", "data", "telemetry"}
    print("  [OK] firewall-routing.csv: 8-column header + edge/bastion/data/telemetry tiers")


def test_firewall_csv_includes_customer_cidr_and_service_vpc_cidr():
    body = _extract_bundle(ob._build_bundle(VALID_PAYLOAD))["firewall-routing.csv"]
    assert VALID_PAYLOAD["customer_subnet"] in body
    assert VALID_PAYLOAD["client_cidr"] in body
    assert VALID_PAYLOAD["service_vpc_cidr"] in body
    print("  [OK] firewall CSV references customer + client + service CIDRs")


def test_manifest_carries_fingerprint_and_tenant_metadata():
    out = _extract_bundle(ob._build_bundle(VALID_PAYLOAD))
    manifest = json.loads(out["manifest.json"])
    assert manifest["tenant_id"] == "acme-corp"
    assert manifest["vpn_endpoint_id"] == VALID_PAYLOAD["vpn_endpoint_id"]
    assert "bundle_fingerprint" in manifest
    assert len(manifest["bundle_fingerprint"]) == 64    # SHA-256 hex
    assert "expires_at" in manifest
    assert manifest["bundle_version"] == "1.0"
    print("  [OK] manifest.json has tenant metadata + SHA-256 fingerprint")


def test_readme_includes_tenant_id_and_steps():
    out = _extract_bundle(ob._build_bundle(VALID_PAYLOAD))
    readme = out["README.md"]
    assert "acme-corp" in readme
    assert "Activation steps" in readme
    assert "firewall-routing.csv" in readme
    print("  [OK] README.md includes tenant_id + activation steps + .csv reference")


def test_lambda_handler_direct_invoke():
    """Direct-invoke shape: event itself IS the payload."""
    resp = ob.lambda_handler(VALID_PAYLOAD, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["tenant_id"] == "acme-corp"
    assert body["bundle_uri"].startswith("s3://")
    assert "download_url" in body
    assert body["bundle_size"] > 0
    print("  [OK] lambda_handler direct-invoke -> 200 + S3 URI + presigned URL")


def test_lambda_handler_apigw_proxy_invoke():
    """API Gateway shape: payload is in event['body'] as JSON string."""
    resp = ob.lambda_handler({"body": json.dumps(VALID_PAYLOAD)}, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["tenant_id"] == "acme-corp"
    print("  [OK] lambda_handler API Gateway proxy shape (event['body'] string) -> 200")


def test_lambda_handler_returns_400_on_missing_fields():
    resp = ob.lambda_handler({"tenant_id": "incomplete"}, None)
    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "missing" in body["error"]
    print("  [OK] lambda_handler missing fields -> 400 with error message")


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 70)
    print("WS3 onboarding bundle generator tests")
    print("=" * 70)
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("\nAll onboarding bundle tests passed.")
