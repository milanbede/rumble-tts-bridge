"""pytest configuration for KITT bot tests."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the kitt package is importable (repo root is the project root)
_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
