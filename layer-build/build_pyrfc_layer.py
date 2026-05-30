"""
Build the pyrfc Lambda layer using the prebuilt wheel from SAP's GitHub Releases
+ the SDK .so files already in this repo. Cross-platform, no Docker required.

Why GitHub and not PyPI: SAP's PyPI release for v3.3.1 only ships macOS-arm64 +
Windows wheels (no Linux). The GitHub release at
https://github.com/SAP/PyRFC/releases ships the Linux x86_64 wheels we need for
Lambda (Amazon Linux 2 / 2023 runtime). Both wheels are byte-identical to what
`pip install pyrfc` would produce on the matching platform.

Produces:  layer-build/pyrfc-layer.zip
  ├── lib/     ← libsapnwrfc.so + libsapucum.so + ICU libs from nwrfcsdk-linux/
  └── python/  ← pyrfc package contents from the cp311 linux_x86_64 wheel

Pin a specific version with:  M4H_PYRFC_VERSION=3.3.1 python build_pyrfc_layer.py
Defaults to 3.3.1 (the version with a known-good cp311 linux wheel on GitHub).
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SDK_LIB = REPO / "nwrfcsdk-linux" / "lib"
BUILD = HERE / "build"
OUT = HERE / "pyrfc-layer.zip"

PYRFC_VERSION = os.environ.get("M4H_PYRFC_VERSION", "3.3.1")
PY_TAG = "cp311"
PLATFORM_TAG = "linux_x86_64"
WHEEL_NAME = f"pyrfc-{PYRFC_VERSION}-{PY_TAG}-{PY_TAG}-{PLATFORM_TAG}.whl"
WHEEL_URL = f"https://github.com/SAP/PyRFC/releases/download/v{PYRFC_VERSION}/{WHEEL_NAME}"


def fetch(url: str) -> bytes:
    """Download a file with a clear progress message (some networks are slow)."""
    print(f"  GET {url}")
    with urllib.request.urlopen(url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} from {url}")
        return resp.read()


def main() -> int:
    if not SDK_LIB.exists() or not any(SDK_LIB.iterdir()):
        print(f"ERROR: SAP SDK lib not found / empty at {SDK_LIB}", file=sys.stderr)
        print("       Expected `nwrfcsdk-linux/lib/*.so` from the repo.", file=sys.stderr)
        return 1

    # ── 1. clean staging ────────────────────────────────────────────────
    if BUILD.exists():
        shutil.rmtree(BUILD)
    (BUILD / "python").mkdir(parents=True)
    (BUILD / "lib").mkdir(parents=True)

    # ── 2. copy SDK .so files into lib/ ─────────────────────────────────
    sdk_files = [f for f in SDK_LIB.iterdir() if f.is_file()]
    for f in sdk_files:
        shutil.copy(str(f), str(BUILD / "lib" / f.name))
    print(f"[1/3] copied {len(sdk_files)} SDK files into lib/")

    # ── 3. download the prebuilt wheel from SAP's GitHub release ────────
    print(f"[2/3] fetching pyrfc wheel for {PY_TAG}/{PLATFORM_TAG} (v{PYRFC_VERSION})")
    try:
        wheel_bytes = fetch(WHEEL_URL)
    except Exception as e:
        print(f"\nERROR: download failed: {e}", file=sys.stderr)
        print("  If 3.3.1 was yanked, set M4H_PYRFC_VERSION to a release listed at", file=sys.stderr)
        print("  https://github.com/SAP/PyRFC/releases (look for a *-cp311-cp311-linux_x86_64.whl asset).", file=sys.stderr)
        return 1
    print(f"      got {len(wheel_bytes):,} bytes")

    # The wheel is a plain zip — extract its contents straight into build/python/
    # (skipping the dist-info metadata is optional; we keep it for traceability)
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as wh:
        wh.extractall(str(BUILD / "python"))

    # ── 4. zip the layer (python/ + lib/ at root, Lambda mounts as /opt/) ─
    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(str(OUT), "w", zipfile.ZIP_DEFLATED) as zf:
        for base in ("python", "lib"):
            base_dir = BUILD / base
            for p in base_dir.rglob("*"):
                if p.is_file():
                    zf.write(str(p), str(p.relative_to(BUILD)))
    size_mb = OUT.stat().st_size / 1024.0 / 1024.0
    print(f"[3/3] built {OUT} ({size_mb:.1f} MB)")

    print("\nNext step:")
    print("  cd terraform\\environments\\prod")
    print("  terraform apply    # Terraform detects the zip and publishes the layer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
