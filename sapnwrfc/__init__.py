"""
SAP NW RFC SDK — DLL/shared-library loader
===========================================
Import this module **before** ``import pyrfc`` to register the SDK library
path with the Python runtime.

On **Windows** (Python ≥ 3.8) it uses ``sapnwrfc/lib/`` (bundled DLLs) and
calls ``os.add_dll_directory()`` so that ``sapnwrfc.dll`` and its ICU
dependencies are found.

On **Linux** it uses ``nwrfcsdk-linux/lib/`` (bundled .so files) and sets
``LD_LIBRARY_PATH`` and ``SAPNWRFC_HOME``.  Inside Docker the Dockerfile
already copies these to ``/opt/sap/lib`` so this acts as a fallback.

Usage (one line, anywhere before pyrfc is imported)::

    import sapnwrfc          # registers library path
    from pyrfc import Connection
"""

import os
import sys
import pathlib

_PKG_DIR = pathlib.Path(__file__).resolve().parent          # sapnwrfc/
_PROJECT_ROOT = _PKG_DIR.parent                             # repo root
_WIN_LIB = _PKG_DIR / "lib"                                # sapnwrfc/lib/
_LINUX_LIB = _PROJECT_ROOT / "nwrfcsdk-linux" / "lib"      # nwrfcsdk-linux/lib/


def _register():
    """Add the correct SDK lib directory to the runtime library search path."""

    if sys.platform == "win32":
        lib_dir = _WIN_LIB
    else:
        # Prefer /opt/sap/lib (Docker) if present, otherwise bundled repo copy
        docker_lib = pathlib.Path("/opt/sap/lib")
        lib_dir = docker_lib if docker_lib.is_dir() else _LINUX_LIB

    lib_str = str(lib_dir)

    if not lib_dir.is_dir():
        return  # SDK not present — pyrfc will fall back to ImportError

    if sys.platform == "win32":
        # Python 3.8+ requires explicit DLL directory registration
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(lib_str)
        # Also prepend to PATH for older ctypes / subprocess calls
        current = os.environ.get("PATH", "")
        if lib_str not in current:
            os.environ["PATH"] = lib_str + os.pathsep + current
    else:
        # Linux / macOS — extend LD_LIBRARY_PATH if not already set
        ld = os.environ.get("LD_LIBRARY_PATH", "")
        if lib_str not in ld:
            os.environ["LD_LIBRARY_PATH"] = lib_str + (os.pathsep + ld if ld else "")

    # Set SAPNWRFC_HOME (some pyrfc builds check this)
    if not os.environ.get("SAPNWRFC_HOME"):
        os.environ["SAPNWRFC_HOME"] = str(lib_dir.parent)


_register()
