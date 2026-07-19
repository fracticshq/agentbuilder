#!/usr/bin/env python3
"""Enforce the repository-root shared package tree as the only source."""

from __future__ import annotations

import argparse
from pathlib import Path


CANONICAL_PACKAGES = ("commons", "llm", "memory", "retrieval", "tools", "agent_runtime")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    errors: list[str] = []

    for package in CANONICAL_PACKAGES:
        package_root = root / "packages" / package
        if not (package_root / "pyproject.toml").is_file() or not (package_root / "src").is_dir():
            errors.append(f"Canonical package is incomplete: packages/{package}")

    # Bytecode may survive a developer's local deletion, but source files or a
    # package manifest here would recreate the old test/deploy split-brain.
    duplicate_root = root / "apps" / "api" / "packages"
    if duplicate_root.exists():
        duplicate_sources = [
            path.relative_to(root).as_posix()
            for pattern in ("*.py", "pyproject.toml", "README.md", "AGENTS.md")
            for path in duplicate_root.rglob(pattern)
        ]
        if duplicate_sources:
            errors.append(
                "Duplicate API-local package source is forbidden: " + ", ".join(sorted(duplicate_sources)[:8])
            )

    start_script = (root / "apps" / "api" / "start.sh").read_text(encoding="utf-8")
    if '"${API_DIR}/packages/${package}/src"' in start_script:
        errors.append("apps/api/start.sh still falls back to apps/api/packages")

    if errors:
        raise SystemExit("Canonical package verification failed:\n- " + "\n- ".join(errors))
    print("Canonical package verification passed: one root package tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
