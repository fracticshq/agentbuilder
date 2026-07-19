"""Keep the read-only capacity-probe thresholds deterministic."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module(root: Path):
    spec = importlib.util.spec_from_file_location("load_probe", root / "scripts" / "load_probe.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_probe_collects_percentiles_and_bounded_failure_samples(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    module = _load_module(root)
    responses = iter(
        [
            (True, 12.0, "HTTP 200"),
            (True, 17.0, "HTTP 200"),
            (False, 20.0, "HTTP 503"),
            (True, 23.0, "HTTP 200"),
        ]
    )
    monkeypatch.setattr(module, "request_once", lambda *args, **kwargs: next(responses))

    result = module.run_probe("https://api.example/ready", requests=4, concurrency=2, timeout=1, insecure_tls=False)

    assert result["successes"] == 3
    assert result["failures"] == 1
    assert result["error_rate"] == 0.25
    assert result["latency_ms"]["p95"] == 23.0
    assert result["failure_samples"] == ["HTTP 503"]
