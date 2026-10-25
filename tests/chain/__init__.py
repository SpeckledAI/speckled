"""Tests for lib/speckled_chain. Run with: python3 -m unittest discover tests"""
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[2] / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
