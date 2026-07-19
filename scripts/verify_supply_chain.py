#!/usr/bin/env python3
"""Fail CI when release inputs lose immutable pinning or SBOM coverage."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ACTION_REF = re.compile(r"^\s*(?:-\s*)?uses:\s*[^@\s]+@([0-9a-f]{40})\b")
DOCKER_FROM = re.compile(r"^\s*FROM\s+([^\s]+)", re.IGNORECASE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sbom", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    errors: list[str] = []

    if not args.sbom.is_file() or args.sbom.stat().st_size == 0:
        errors.append("CycloneDX SBOM was not generated")

    workflows = sorted((root / ".github" / "workflows").glob("*.y*ml"))
    if not workflows:
        errors.append("No GitHub Actions workflows found")
    for workflow in workflows:
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "uses:" in line and not ACTION_REF.match(line):
                errors.append(f"Unpinned GitHub Action in {workflow.relative_to(root)}: {line.strip()}")

    for dockerfile in sorted(root.glob("apps/*/Dockerfile")):
        for line in dockerfile.read_text(encoding="utf-8").splitlines():
            match = DOCKER_FROM.match(line)
            if match and "@sha256:" not in match.group(1):
                errors.append(f"Unpinned container base image in {dockerfile}: {match.group(1)}")

    if errors:
        raise SystemExit("Supply-chain verification failed:\n- " + "\n- ".join(errors))
    print("Supply-chain verification passed: pinned actions/base images and SBOM present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
