import os
import sys

# Ensure src/ is on sys.path so ncp_adapter is importable
_src_path = os.path.join(os.path.dirname(__file__), "..", "..", "src")
if _src_path not in sys.path:
    sys.path.insert(0, os.path.abspath(_src_path))
