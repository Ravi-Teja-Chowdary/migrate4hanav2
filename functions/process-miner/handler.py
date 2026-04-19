"""
Migrate4HANA — Stage 6: Process Miner
=======================================
ST03N workload analysis and T-code → S/4HANA Fiori app mapping.

Delegates to st03n_analyzer.py which already contains a main.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from st03n_analyzer import main  # noqa: F401
