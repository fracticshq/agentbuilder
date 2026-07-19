"""Verify the read-only production smoke gate against a representative endpoint contract."""

from __future__ import annotations

import json
import sys
import importlib.util
from pathlib import Path


def _load_smoke_module(root: Path):
    script = root / "scripts" / "smoke_production.py"
    spec = importlib.util.spec_from_file_location("smoke_production", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_production_smoke_gate_writes_passing_report(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    module = _load_smoke_module(root)
    base_url = "http://127.0.0.1:8000"
    report = tmp_path / "smoke.json"

    def fake_request(url: str, *, timeout: float, insecure_tls: bool):
        if url.endswith("/live"):
            return 200, json.dumps({"status": "alive"}).encode(), "application/json"
        if url.endswith("/ready"):
            return 200, json.dumps({"status": "healthy", "dependencies": {"mongodb": "healthy", "redis": "healthy"}}).encode(), "application/json"
        if url.endswith("/config-check"):
            return 200, json.dumps({"environment": "production", "debug": False, "mongodb_required": True, "redis_required": True, "admin_key_bypass_allowed": False, "metrics_enabled": True}).encode(), "application/json"
        if url.endswith("/runtime-config.js"):
            return 200, f'window.__APP_CONFIG__ = {{ API_BASE_URL: "{base_url}" }};'.encode(), "application/javascript"
        if url.endswith("/health"):
            return 200, b"OK", "text/plain"
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(module, "request", fake_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_production.py",
            "--api-url", base_url,
            "--admin-url", base_url,
            "--widget-url", base_url,
            "--shopify-url", base_url,
            "--allow-http",
            "--report", str(report),
        ],
    )
    assert module.main() == 0
    assert json.loads(report.read_text(encoding="utf-8"))["passed"] is True
