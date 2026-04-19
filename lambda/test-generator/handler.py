"""
Migrate4HANA — Stage 17: Test Generator
=========================================
Generates DITL (Day-in-the-Life) UI automation test scripts from process
mining results.

Delegates to ditl_generator.py which already contains a lambda_handler.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ditl_generator import lambda_handler  # noqa: F401
