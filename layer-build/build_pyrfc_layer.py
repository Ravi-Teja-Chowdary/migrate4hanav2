"""
Build the pyrfc Lambda layer from the SAP NW RFC SDK already in this repo.

What this produces:  layer-build/pyrfc-layer.zip
  ├── lib/        ← the .so files from nwrfcsdk-linux/lib (Lambda mounts as /opt/lib)
  └── python/     ← the pyrfc wheel extracted (Lambda mounts as /opt/python)

How it's used:  terraform/environments/prod/main.tf detects this file's presence and
publishes it as an aws_lambda_layer_version on `terraform apply` — no manual
`pyrfc_layer_arn` tfvar needed for testing.

Run it once:   python layer-build/build_pyrfc_layer.py
Re-run when you change SDK files or want a fresh pyrfc wheel.

Requirements:
  * Python 3.7+ on the host (pip is used purely to *download* the cp311
    manylinux wheel — your local Python version does not matter).
  * Internet access for the one-time pip download of pyrfc from PyPI.
  * The repo's nwrfcsdk-linux/lib directory must exist (already committed).
"""
from __future__ import print_function

import glob
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SDK_LIB = REPO / "nwrfcsdk-linux" / "lib"
BUILD = HERE / "build"
WHEELS = BUILD / "wheels"
OUT = HERE / "pyrfc-layer.zip"

# Lambda target: must match the runtime in the lambda module
TARGET_PYTHON = "3.11"
TARGET_PLATFORM = "manylinux2014_x86_64"
PYRFC_VERSION = os.environ.get("M4H_PYRFC_VERSION", "")  # empty -> latest


def main() -> int:
    if not SDK_LIB.exists():
        print(f"ERROR: SAP SDK lib not found at {SDK_LIB}", file=sys.stderr)
        print("       Expected `nwrfcsdk-linux/lib/*.so` from the repo.", file=sys.stderr)
        return 1
    so_files = sorted(SDK_LIB.iterdir())
    if not so_files:
        print(f"ERROR: {SDK_LIB} is empty", file=sys.stderr)
        return 1

    # ── 1. clean staging ──────────────────────────────────────────────────
    if BUILD.exists():
        shutil.rmtree(BUILD)
    (BUILD / "python").mkdir(parents=True)
    (BUILD / "lib").mkdir(parents=True)
    WHEELS.mkdir(parents=True)

    # ── 2. copy the SDK .so files into lib/ ───────────────────────────────
    for f in so_files:
        if f.is_file():
            shutil.copy(str(f), str(BUILD / "lib" / f.name))
    print("[1/3] copied {} SDK files into lib/".format(
        len(list((BUILD / "lib").iterdir()))))

    # ── 3. download the cp311 manylinux pyrfc wheel from PyPI ─────────────
    spec = "pyrfc" + ("==" + PYRFC_VERSION if PYRFC_VERSION else "")
    cmd = [sys.executable, "-m", "pip", "download",
           "--platform", TARGET_PLATFORM,
           "--python-version", TARGET_PYTHON,
           "--implementation", "cp",
           "--only-binary=:all:",
           "--no-deps",
           "-d", str(WHEELS),
           spec]
    print("[2/3] downloading pyrfc wheel:")
    print("      " + " ".join(cmd))
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print("\nERROR: pip download failed.", file=sys.stderr)
        print("  If pyrfc has no cp311 manylinux wheel on PyPI for your", file=sys.stderr)
        print("  pip version, either upgrade pip (`python -m pip install -U pip`)", file=sys.stderr)
        print("  or set M4H_PYRFC_VERSION env to a known-good version.", file=sys.stderr)
        return e.returncode

    wheels = glob.glob(str(WHEELS / "*.whl"))
    if not wheels:
        print("ERROR: no .whl downloaded", file=sys.stderr)
        return 1
    for whl in wheels:
        with zipfile.ZipFile(whl) as zf:
            zf.extractall(str(BUILD / "python"))
        print("      extracted " + os.path.basename(whl))

    # ── 4. zip layer ─────────────────────────────────────────────────────
    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(str(OUT), "w", zipfile.ZIP_DEFLATED) as zf:
        for base in ("python", "lib"):
            base_dir = BUILD / base
            for p in base_dir.rglob("*"):
                if p.is_file():
                    zf.write(str(p), str(p.relative_to(BUILD)))
    size_mb = OUT.stat().st_size / 1024.0 / 1024.0
    print("[3/3] built {} ({:.1f} MB)".format(OUT, size_mb))
    print("\nNext step:")
    print("  cd terraform/environments/prod && terraform apply")
    print("Terraform will detect the zip and publish it as a Lambda layer automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
