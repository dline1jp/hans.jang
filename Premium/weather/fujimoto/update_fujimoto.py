# -*- coding: utf-8 -*-
"""The old path now rebuilds the monthly 300,000 won page on the hansjang menu."""
import runpy
from pathlib import Path

TARGET = Path(__file__).resolve().parents[2] / "hansjang" / "DRIP" / "update_drip.py"
runpy.run_path(str(TARGET), run_name="__main__")
