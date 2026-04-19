"""
SAP NW RFC SDK — DLL/shared-library loader
===========================================
Import this module **before** ``import pyrfc`` to register the SDK library
path with the Python runtime.

On **Windows** (Python ≥ 3.8) it calls ``os.add_dll_directory()`` so that
``sapnwrfc.dll`` and its ICU dependencies are found.

On **Linux** the Dockerfile already sets ``LD_LIBRARY_PATH``; this module
is a no-op but will set ``SAPNWRFC_HOME`` as a convenience.

Usage (one line, anywhere before pyrfc is imported)::

    import sapnwrfc          # registers DLL path
    from pyrfc import Connection
"""

import os
import sys
import pathlib

_LIB_DIR = pathlib.Path(__file__).resolve().parent / "lib"


def _register():
    """Add sapnwrfc/lib to the runtime library search path."""
    lib_str = str(_LIB_DIR)

    if not _LIB_DIR.is_dir():
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
        os.environ["SAPNWRFC_HOME"] = str(_LIB_DIR.parent)


_register()
