"""Regression tests for immutable release-evidence validation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / "release_evidence.py"), "--root", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_release_evidence_requires_digest_pinned_images_attestations_and_smoke(tmp_path: Path):
    root = Path(__file__).resolve().parents[3]
    sbom = tmp_path / "sbom.json"
    smoke = tmp_path / "smoke.json"
    capacity = tmp_path / "capacity.json"
    evidence = tmp_path / "release.json"
    sbom.write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5"}), encoding="utf-8")
    smoke.write_text(json.dumps({"schema_version": 1, "passed": True}), encoding="utf-8")
    capacity.write_text(json.dumps({"schema_version": 1, "passed": True}), encoding="utf-8")
    digest = "sha256:" + "a" * 64

    created = _run(
        root,
        "create",
        "--output", str(evidence),
        "--sbom", str(sbom),
        "--smoke-report", str(smoke),
        "--capacity-report", str(capacity),
        "--image", f"api=registry.example/agentbuilder/api@{digest}",
        "--attestation", "api=signature=oci://registry.example/signature",
        "--attestation", "api=provenance=oci://registry.example/provenance",
        "--commit", "f" * 40,
        "--environment", "production",
        "--ci-run-url", "https://github.example/org/repo/actions/runs/1",
        "--approved-by", "release-operator",
    )
    assert created.returncode == 0, created.stderr

    validated = _run(
        root,
        "validate",
        "--evidence", str(evidence),
        "--expected-commit", "f" * 40,
        "--require-attestations",
        "--require-smoke",
        "--require-capacity",
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr

    invalid = _run(
        root,
        "create",
        "--output", str(tmp_path / "invalid.json"),
        "--sbom", str(sbom),
        "--image", "api=registry.example/agentbuilder/api:mutable-tag",
        "--commit", "f" * 40,
        "--environment", "production",
        "--ci-run-url", "https://github.example/org/repo/actions/runs/1",
        "--approved-by", "release-operator",
    )
    assert invalid.returncode != 0
    assert "immutable OCI digest" in invalid.stderr
