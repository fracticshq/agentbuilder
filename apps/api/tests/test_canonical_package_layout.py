"""Regression guard for the canonical shared-package deployment rule."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_repository_has_one_canonical_shared_package_tree():
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "verify_canonical_packages.py"), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
