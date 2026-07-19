#!/usr/bin/env python3
"""Generate a deterministic CycloneDX JSON SBOM from deployed manifests.

The project has Python and Node deployables rather than one package manager.
Using only the standard library keeps the CI gate reproducible and makes the
result usable before an external SBOM service is introduced. It is deliberately
manifest-level: image build provenance remains the release system's job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any


REQUIREMENT = re.compile(r"^([A-Za-z0-9_.-]+)\s*==\s*([^\s;]+)")
DEPENDENCY = re.compile(r"^([A-Za-z0-9_.-]+)\s*(.*)$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def component(name: str, version: str, ecosystem: str, source: str) -> dict[str, Any]:
    normalized = name.lower().replace("_", "-")
    return {
        "type": "library",
        "name": name,
        "version": version or "unspecified",
        "bom-ref": f"pkg:{ecosystem}/{normalized}@{version or 'unspecified'}?source={source}",
        "properties": [{"name": "agentbuilder:source-manifest", "value": source}],
    }


def python_lock_components(path: Path, source: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = REQUIREMENT.match(raw.strip())
        if match:
            result.append(component(match.group(1), match.group(2), "pypi", source))
    return result


def python_project_components(path: Path, source: str) -> list[dict[str, Any]]:
    # Keep the generator runnable on the local Python 3.9+ development floor
    # as well as CI's Python 3.12; stdlib tomllib only arrived in 3.11. The
    # repository's deployed package manifests use a static PEP 621 list.
    dependencies: list[str] = []
    in_project = False
    in_dependencies = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            in_dependencies = False
            continue
        if not in_project:
            continue
        if line.startswith("dependencies") and "[" in line:
            in_dependencies = True
            continue
        if in_dependencies:
            if line.startswith("]"):
                in_dependencies = False
                continue
            match = re.match(r'^\s*["\']([^"\']+)["\']', raw)
            if match:
                dependencies.append(match.group(1))
    result: list[dict[str, Any]] = []
    for dependency in dependencies:
        match = DEPENDENCY.match(str(dependency).split(";", 1)[0].strip())
        if not match:
            continue
        version = match.group(2).strip().lstrip("=") or "unconstrained"
        result.append(component(match.group(1), version, "pypi", source))
    return result


def npm_lock_components(path: Path, source: str) -> list[dict[str, Any]]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    packages = parsed.get("packages", {})
    result: list[dict[str, Any]] = []
    for package_path, detail in packages.items():
        if not package_path.startswith("node_modules/") or not isinstance(detail, dict):
            continue
        version = str(detail.get("version") or "")
        if not version:
            continue
        name = package_path.removeprefix("node_modules/")
        result.append(component(name, version, "npm", source))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    manifests = [root / "apps/api/requirements.lock"]
    manifests.extend(sorted((root / "packages").glob("*/pyproject.toml")))
    manifests.extend(
        root / relative
        for relative in (
            "apps/admin/package-lock.json",
            "apps/widget/package-lock.json",
            "apps/shopify-mcp/package-lock.json",
        )
    )
    missing = [path for path in manifests if not path.is_file()]
    if missing:
        raise SystemExit("Missing SBOM manifest(s): " + ", ".join(str(path) for path in missing))

    components: list[dict[str, Any]] = []
    for manifest in manifests:
        relative = manifest.relative_to(root).as_posix()
        if manifest.suffix == ".lock" and manifest.name == "requirements.lock":
            components.extend(python_lock_components(manifest, relative))
        elif manifest.suffix == ".toml":
            components.extend(python_project_components(manifest, relative))
        elif manifest.name == "package-lock.json":
            components.extend(npm_lock_components(manifest, relative))

    deduplicated = {(entry["bom-ref"], entry["name"], entry["version"]): entry for entry in components}
    manifest_hashes = [
        {"name": "agentbuilder:manifest-sha256", "value": f"{path.relative_to(root)}={sha256(path)}"}
        for path in manifests
    ]
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.UUID(hex=hashlib.sha256(''.join(item['value'] for item in manifest_hashes).encode()).hexdigest()[:32])}",
        "version": 1,
        "metadata": {
            # Deliberately deterministic: repository history is captured by the
            # release commit and CI run, not wall-clock content drift.
            "component": {"type": "application", "name": "agentbuilder", "version": os.getenv("GITHUB_SHA", "local")},
            "properties": manifest_hashes,
        },
        "components": sorted(deduplicated.values(), key=lambda entry: (entry["name"].lower(), entry["version"], entry["bom-ref"])),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Generated CycloneDX SBOM with {len(sbom['components'])} components: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
