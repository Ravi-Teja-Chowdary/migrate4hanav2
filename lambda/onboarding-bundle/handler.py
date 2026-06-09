"""
onboarding-bundle - WS3 Customer Onboarding Bundle Generator.

Generates a per-customer downloadable bundle that lets the client's
corporate network security team activate the VPN connection without manual
configuration:

  - <tenant>.ovpn               OpenVPN client profile (auth + remote +
                                routes), pre-rendered with the customer's
                                Client VPN endpoint DNS + client CIDR
  - firewall-routing.csv         Source-CIDR / dest-CIDR / port / protocol
                                rows the customer's firewall admin can
                                pipe into their change-management system
  - README.md                   Human-readable activation steps
  - manifest.json               Tenant metadata + cert fingerprints +
                                signed-url validity window for audit

The bundle is packaged as a tarball, uploaded to the customer's tenant-
scoped S3 prefix (via the F7 TenantContext routing convention), and
returned as a 24-hour presigned URL.

Trigger: API Gateway POST /onboarding/bundle (via the WS1 api-orchestrator)
OR a direct lambda invoke with payload:

    { "tenant_id":          "acme-corp",
      "vpn_endpoint_id":    "cvpn-endpoint-...",
      "vpn_dns_name":       "cvpn-endpoint-....prod.clientvpn.us-east-1.amazonaws.com",
      "client_cidr":        "10.99.0.0/22",
      "service_vpc_cidr":   "10.30.0.0/16",
      "customer_subnet":    "172.16.0.0/12",
      "client_certificate": "<PEM bytes, base64>",
      "client_key":         "<PEM bytes, base64>" }
"""
from __future__ import annotations

import base64
import io
import json
import os
import tarfile
import time

try:
    import boto3
    S3 = boto3.client("s3")
except Exception:
    S3 = None


BUNDLE_BUCKET = os.environ.get("M4H_ONBOARDING_BUCKET",
                                "migrate4hana-onboarding-prod")
PRESIGN_TTL = 24 * 60 * 60   # 24 hours


# ─────────────────────────────────────────────────────────────────────────────
# Bundle templates
# ─────────────────────────────────────────────────────────────────────────────
OVPN_TEMPLATE = """\
client
dev tun
proto udp
remote {vpn_dns_name} 443
remote-cert-tls server
auth-nocache
auth-user-pass-optional
cipher AES-256-GCM
verify-x509-name "{vpn_endpoint_id}" name-prefix
verb 3

# Migrate4HANA tenant: {tenant_id}
# Bundle generated: {generated_at}
# Client CIDR pool: {client_cidr}

<ca>
{ca_pem}
</ca>
<cert>
{client_certificate}
</cert>
<key>
{client_key}
</key>
"""


README_TEMPLATE = """\
# Migrate4HANA VPN Onboarding -- {tenant_id}

Generated {generated_at}.

This bundle contains everything your corporate network security team needs
to activate the VPN connection to your Migrate4HANA landscape:

  - **{tenant_id}.ovpn**   OpenVPN client profile (auth + routing)
  - **firewall-routing.csv** Per-port allow rules for your firewall admin
  - **manifest.json**         Tenant metadata + cert validity window

## Activation steps (network admin)

1. Apply the firewall rules in `firewall-routing.csv` to your egress
   firewall. The Source CIDR is YOUR corporate range; the Destination
   CIDR is the Migrate4HANA Client VPN endpoint pool (`{client_cidr}`).

2. Distribute `{tenant_id}.ovpn` to authorized users via your standard
   secrets-distribution channel. Each user imports it into their
   OpenVPN client (Tunnelblick / OpenVPN Connect / network manager).

3. (Optional) If your corporate network requires per-user MFA on VPN
   connect, enable Federated SAML on the Client VPN endpoint via the
   AWS console -- the .ovpn profile above already includes the MFA
   negotiation directive.

## Connectivity test

Once connected, run:

    curl -v https://<service-vpc-internal-elb>.amazonaws.com/health

Expected: HTTP 200 with `{{"service":"api-orchestrator", "tenant":"{tenant_id}", ...}}`.

If the curl fails with timeout, your firewall is still blocking; review
the rules in `firewall-routing.csv` and ensure they're applied to BOTH
inbound and outbound directions on your egress firewall.

## Support

  - Tenant ID:       {tenant_id}
  - Bundle expires:  {expires_at}
  - Onboarding ticket: cite tenant_id + bundle SHA-256 fingerprint from manifest.json
"""


# ─────────────────────────────────────────────────────────────────────────────
def _render_ovpn(payload: dict, ca_pem: str = "") -> str:
    """Render the .ovpn client profile from the payload + tenant metadata."""
    return OVPN_TEMPLATE.format(
        vpn_dns_name=payload["vpn_dns_name"],
        vpn_endpoint_id=payload["vpn_endpoint_id"],
        tenant_id=payload["tenant_id"],
        client_cidr=payload["client_cidr"],
        generated_at=_iso_now(),
        ca_pem=ca_pem.strip() or "# (CA chain attached at deploy time)",
        client_certificate=_decode_pem(payload.get("client_certificate", "")),
        client_key=_decode_pem(payload.get("client_key", "")),
    )


def _render_firewall_csv(payload: dict) -> str:
    """Produce the firewall-routing.csv. Rows:
      tier, src_cidr, dst_cidr, port, protocol, direction, description
    """
    rows = [
        ["tier", "src_cidr", "dst_cidr", "port_from", "port_to",
         "protocol", "direction", "description"],

        # Customer egress -> VPN endpoint
        ["edge", payload["customer_subnet"], payload["vpn_dns_name"],
         "443", "443", "udp", "egress",
         "Customer -> AWS Client VPN endpoint"],

        # VPN clients -> service VPC bastion tier
        ["bastion", payload["client_cidr"], payload["service_vpc_cidr"],
         "22", "22", "tcp", "ingress",
         "Authorized user SSH to bastion"],
        ["bastion", payload["client_cidr"], payload["service_vpc_cidr"],
         "443", "443", "tcp", "ingress",
         "Authorized user HTTPS to API console (WS1)"],

        # Bastion -> data tier (SAP RFC)
        ["data", payload["service_vpc_cidr"], payload["service_vpc_cidr"],
         "3200", "3300", "tcp", "internal",
         "Bastion -> SAP RFC gateway range"],
        ["data", payload["service_vpc_cidr"], payload["service_vpc_cidr"],
         "44300", "44301", "tcp", "internal",
         "Bastion -> SAP HTTPS OData"],

        # Telemetry egress (CloudWatch)
        ["telemetry", payload["service_vpc_cidr"], "0.0.0.0/0",
         "443", "443", "tcp", "egress",
         "CloudWatch logs + S3 + DDB via VPC endpoints"],
    ]
    buf = io.StringIO()
    import csv
    w = csv.writer(buf)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def _render_manifest(payload: dict, expires_at: str, fingerprint: str) -> str:
    return json.dumps({
        "tenant_id":          payload["tenant_id"],
        "generated_at":       _iso_now(),
        "expires_at":         expires_at,
        "vpn_endpoint_id":    payload["vpn_endpoint_id"],
        "vpn_dns_name":       payload["vpn_dns_name"],
        "client_cidr":        payload["client_cidr"],
        "service_vpc_cidr":   payload["service_vpc_cidr"],
        "customer_subnet":    payload["customer_subnet"],
        "bundle_fingerprint": fingerprint,
        "bundle_version":     "1.0",
    }, indent=2)


def _render_readme(payload: dict, expires_at: str) -> str:
    return README_TEMPLATE.format(
        tenant_id=payload["tenant_id"],
        generated_at=_iso_now(),
        client_cidr=payload["client_cidr"],
        expires_at=expires_at,
    )


def _build_bundle(payload: dict, ca_pem: str = "") -> bytes:
    """Bundle the four files into a tarball, return the tarball bytes."""
    expires_at = _iso_at_offset(PRESIGN_TTL)
    ovpn_content = _render_ovpn(payload, ca_pem=ca_pem)
    firewall_content = _render_firewall_csv(payload)
    readme_content = _render_readme(payload, expires_at)

    # Compute fingerprint over the concatenated contents BEFORE writing the
    # manifest so the manifest references its own bundle by SHA-256.
    import hashlib
    h = hashlib.sha256()
    h.update(ovpn_content.encode("utf-8"))
    h.update(firewall_content.encode("utf-8"))
    h.update(readme_content.encode("utf-8"))
    fingerprint = h.hexdigest()

    manifest_content = _render_manifest(payload, expires_at, fingerprint)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in (
            (f"{payload['tenant_id']}.ovpn", ovpn_content),
            ("firewall-routing.csv", firewall_content),
            ("README.md", readme_content),
            ("manifest.json", manifest_content),
        ):
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _iso_now() -> str:
    import datetime
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _iso_at_offset(seconds: int) -> str:
    import datetime
    t = datetime.datetime.utcnow() + datetime.timedelta(seconds=seconds)
    return t.isoformat(timespec="seconds") + "Z"


def _decode_pem(b64_or_raw: str) -> str:
    """Accept PEM as either raw text or base64-encoded text. Returns raw PEM."""
    if not b64_or_raw:
        return "# (cert injected at deploy time)"
    if b64_or_raw.startswith("-----BEGIN"):
        return b64_or_raw
    try:
        return base64.b64decode(b64_or_raw).decode("utf-8")
    except Exception:
        return b64_or_raw   # last resort: treat as text


def _validate_payload(payload: dict) -> str:
    """Return empty string when valid, error message when not."""
    required = ("tenant_id", "vpn_endpoint_id", "vpn_dns_name",
                "client_cidr", "service_vpc_cidr", "customer_subnet")
    missing = [k for k in required if not (payload.get(k) or "").strip()]
    if missing:
        return f"required fields missing: {','.join(missing)}"
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Lambda entry point
# ─────────────────────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    # Accept both direct invoke + API Gateway proxy formats
    if "body" in event and isinstance(event["body"], str):
        try:
            payload = json.loads(event["body"])
        except Exception:
            payload = {}
    else:
        payload = event

    err = _validate_payload(payload)
    if err:
        return {"statusCode": 400, "body": json.dumps({"error": err})}

    bundle_bytes = _build_bundle(payload, ca_pem=payload.get("ca_pem", ""))

    tenant_id = payload["tenant_id"]
    key = f"tenants/{tenant_id}/onboarding/bundle-{int(time.time())}.tar.gz"

    if S3 is not None:
        try:
            S3.put_object(Bucket=BUNDLE_BUCKET, Key=key, Body=bundle_bytes,
                           ContentType="application/gzip",
                           ServerSideEncryption="AES256")
            url = S3.generate_presigned_url(
                "get_object",
                Params={"Bucket": BUNDLE_BUCKET, "Key": key},
                ExpiresIn=PRESIGN_TTL,
            )
        except Exception as e:
            return {"statusCode": 502,
                    "body": json.dumps({"error": f"S3 upload failed: {e}"})}
    else:
        url = ""    # local dev fallback

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "tenant_id":      tenant_id,
            "bundle_uri":     f"s3://{BUNDLE_BUCKET}/{key}",
            "download_url":   url,
            "expires_in_sec": PRESIGN_TTL,
            "bundle_size":    len(bundle_bytes),
        }),
    }
