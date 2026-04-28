"""
Migrate4HANA — SAP NW RFC SDK loader
=====================================
Platform-aware bootstrap that makes the bundled SAP NetWeaver RFC SDK
discoverable by ``pyrfc`` regardless of whether the tool runs on Windows
or Linux.

Layout in the repo
------------------
    sapnwrfc/lib/*.dll          ← Windows SDK (already bundled)
    nwrfcsdk-linux/lib/*.so*    ← Linux SDK   (bundled)

Behaviour
---------
* On Windows:
    - ``SAPNWRFC_HOME`` defaults to ``<repo>/sapnwrfc``.
    - ``<repo>/sapnwrfc/lib`` is prepended to ``PATH`` so the loader can
      resolve ``sapnwrfc.dll`` and its ICU/SAP UC dependencies.
    - Python 3.8+: ``os.add_dll_directory`` is called for the same path
      so DLL search works under stricter security policies.

* On Linux:
    - ``SAPNWRFC_HOME`` defaults to ``<repo>/nwrfcsdk-linux``.
    - ``<repo>/nwrfcsdk-linux/lib`` is prepended to ``LD_LIBRARY_PATH``
      (helpful for child processes spawned later).
    - The ICU and SAP UC shared objects are pre-loaded with
      ``ctypes.CDLL(..., RTLD_GLOBAL)`` so ``libsapnwrfc.so`` resolves
      its NEEDED dependencies even when the dynamic linker has already
      cached its search path before this Python process started.

The bootstrap is idempotent and silently no-ops if the SDK directory is
absent (e.g. inside the AWS Lambda layer where the SDK is installed at
``/opt/sap`` and the env vars are set by the Dockerfile).

Usage
-----
Import this module *before* importing ``pyrfc``::

    import sapnwrfc  # noqa: F401  (configures SAP NW RFC SDK paths)
    from pyrfc import Connection
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent

# Public attributes — useful for diagnostics / tests
sdk_home: str | None = None
sdk_lib_dir: str | None = None
preloaded_libs: list[str] = []


def _prepend_path(env_var: str, new_dir: str) -> None:
    """Prepend ``new_dir`` to a ``os.pathsep``-delimited environment var."""
    existing = os.environ.get(env_var, "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if new_dir in parts:
        return
    parts.insert(0, new_dir)
    os.environ[env_var] = os.pathsep.join(parts)


def _bootstrap_windows() -> None:
    global sdk_home, sdk_lib_dir
    sdk_dir = _HERE  # the sapnwrfc/ folder itself is SAPNWRFC_HOME on Windows
    lib_dir = sdk_dir / "lib"
    if not lib_dir.is_dir():
        logger.debug("Windows SAP NW RFC SDK not found at %s", lib_dir)
        return

    sdk_home = str(sdk_dir)
    sdk_lib_dir = str(lib_dir)

    os.environ.setdefault("SAPNWRFC_HOME", sdk_home)
    _prepend_path("PATH", sdk_lib_dir)

    add_dll = getattr(os, "add_dll_directory", None)
    if add_dll is not None:
        try:
            add_dll(sdk_lib_dir)
        except (OSError, FileNotFoundError) as exc:
            logger.debug("os.add_dll_directory(%s) failed: %s", sdk_lib_dir, exc)


def _bootstrap_linux() -> None:
    global sdk_home, sdk_lib_dir, preloaded_libs
    sdk_dir = _PROJECT_ROOT / "nwrfcsdk-linux"
    lib_dir = sdk_dir / "lib"
    if not lib_dir.is_dir():
        logger.debug("Linux SAP NW RFC SDK not found at %s", lib_dir)
        return

    sdk_home = str(sdk_dir)
    sdk_lib_dir = str(lib_dir)

    os.environ.setdefault("SAPNWRFC_HOME", sdk_home)
    _prepend_path("LD_LIBRARY_PATH", sdk_lib_dir)

    # Pre-load SAP/ICU shared objects in dependency order so the dynamic
    # linker has them in memory before pyrfc loads libsapnwrfc.so. This
    # is the reliable way to avoid "cannot open shared object file"
    # errors when LD_LIBRARY_PATH was not exported before Python started.
    preload_order = (
        "libicudata.so.50",
        "libicuuc.so.50",
        "libicui18n.so.50",
        "libicudecnumber.so",
        "libsapucum.so",
        "libsapnwrfc.so",
    )
    for name in preload_order:
        path = lib_dir / name
        if not path.is_file():
            continue
        try:
            ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
            preloaded_libs.append(name)
        except OSError as exc:
            logger.debug("Preload of %s failed: %s", path, exc)


# ---------------------------------------------------------------------------
# Run bootstrap at import time. Wrapped in try/except so that a misconfigured
# SDK directory can never prevent the module (or pyrfc) from importing.
# ---------------------------------------------------------------------------
try:
    if sys.platform.startswith("win"):
        _bootstrap_windows()
    elif sys.platform.startswith("linux"):
        _bootstrap_linux()
    # macOS / other: SAP does not ship an SDK. The bootstrap silently no-ops.
except Exception as exc:  # pragma: no cover - defensive
    logger.warning("SAP NW RFC SDK bootstrap failed: %s", exc)


__all__ = ["sdk_home", "sdk_lib_dir", "preloaded_libs"]
