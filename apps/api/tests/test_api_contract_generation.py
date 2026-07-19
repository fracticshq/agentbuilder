"""Keep committed API integration artefacts tied to the FastAPI route contract."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_openapi_and_postman_contracts_are_current():
    root = Path(__file__).resolve().parents[3]
    commands = (
        [sys.executable, str(root / "scripts" / "generate_openapi.py"), "--check"],
        [sys.executable, str(root / "scripts" / "generate_postman_collection.py"), "--check"],
    )
    for command in commands:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
