#!/usr/bin/env python3
"""Create and validate a digest-pinned Agent Builder release-evidence record.

The record intentionally contains only immutable references: a source commit,
SBOM checksum, OCI image digests, optional signature/provenance references, and
the final deployment smoke report. It never accepts a mutable container tag as
release evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def git_commit(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def parse_named_value(raw: str, *, label: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"{label} must be NAME=VALUE")
    name, value = raw.split("=", 1)
    if not IMAGE_RE.fullmatch(name) or not value.strip():
        raise ValueError(f"Invalid {label}: {raw!r}")
    return name, value.strip()


def parse_image(raw: str) -> tuple[str, str, str]:
    name, reference = parse_named_value(raw, label="image")
    if "@" not in reference:
        raise ValueError(f"Image {name!r} must be an immutable OCI digest reference, not a tag")
    repository, digest = reference.rsplit("@", 1)
    if not repository or not DIGEST_RE.fullmatch(digest):
        raise ValueError(f"Image {name!r} has an invalid digest reference")
    return name, reference, digest


def read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {label}: {path}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return parsed


def valid_url(value: Any, *, allow_local: bool = False) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    if parsed.scheme == "https" and bool(parsed.netloc):
        return True
    return allow_local and parsed.scheme == "local"


def build_evidence(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root.resolve()
    sbom_path = resolve(root, args.sbom)
    sbom = read_json(sbom_path, label="SBOM")
    if sbom.get("bomFormat") != "CycloneDX":
        raise ValueError("SBOM must be CycloneDX")

    commit = args.commit or git_commit(root)
    if not COMMIT_RE.fullmatch(commit):
        raise ValueError("Release commit must be a full 40-character Git SHA")
    if not valid_url(args.ci_run_url, allow_local=args.allow_local_ci_url):
        raise ValueError("CI run URL must be an HTTPS URL")
    if not args.approved_by.strip():
        raise ValueError("An approver is required for release evidence")

    images: dict[str, dict[str, Any]] = {}
    for raw in args.image:
        name, reference, digest = parse_image(raw)
        if name in images:
            raise ValueError(f"Duplicate release image name: {name}")
        images[name] = {"reference": reference, "digest": digest, "attestations": {}}
    if not images:
        raise ValueError("At least one image is required")

    for raw in args.attestation:
        try:
            image_name, rest = parse_named_value(raw, label="attestation")
            kind, reference = rest.split("=", 1)
        except ValueError as exc:
            raise ValueError("Attestation must be IMAGE=signature|provenance=REFERENCE") from exc
        if image_name not in images or kind not in {"signature", "provenance"} or not reference.strip():
            raise ValueError(f"Invalid attestation: {raw!r}")
        images[image_name]["attestations"][kind] = reference.strip()

    evidence: dict[str, Any] = {
        "schema_version": 1,
        "release": {
            "commit": commit,
            "environment": args.environment,
            "ci_run_url": args.ci_run_url,
            "approved_by": args.approved_by,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        "sbom": {
            "path": display_path(root, sbom_path),
            "sha256": sha256(sbom_path),
        },
        "images": dict(sorted(images.items())),
    }
    if args.smoke_report:
        evidence["smoke"] = report_record(root, args.smoke_report, label="smoke report")
    if args.capacity_report:
        evidence["capacity"] = report_record(root, args.capacity_report, label="capacity report")
    return evidence


def report_record(root: Path, source: Path, *, label: str) -> dict[str, Any]:
    report_path = resolve(root, source)
    report = read_json(report_path, label=label)
    return {
        "path": display_path(root, report_path),
        "sha256": sha256(report_path),
        "passed": report.get("passed") is True,
    }


def validation_errors(
    evidence: dict[str, Any],
    *,
    root: Path,
    require_attestations: bool,
    require_smoke: bool,
    require_capacity: bool,
    expected_commit: str | None,
) -> list[str]:
    errors: list[str] = []
    if evidence.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    release = evidence.get("release")
    if not isinstance(release, dict):
        return [*errors, "release object is required"]
    commit = release.get("commit")
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        errors.append("release.commit must be a full 40-character Git SHA")
    if expected_commit and commit != expected_commit:
        errors.append(f"release.commit does not match expected commit {expected_commit}")
    if release.get("environment") not in {"staging", "production"}:
        errors.append("release.environment must be staging or production")
    if not valid_url(release.get("ci_run_url")):
        errors.append("release.ci_run_url must be HTTPS")
    if not isinstance(release.get("approved_by"), str) or not release["approved_by"].strip():
        errors.append("release.approved_by is required")

    sbom = evidence.get("sbom")
    if not isinstance(sbom, dict):
        errors.append("sbom object is required")
    else:
        sbom_path = resolve(root, Path(str(sbom.get("path") or "")))
        if not sbom_path.is_file():
            errors.append("SBOM path is unavailable for checksum validation")
        elif sbom.get("sha256") != sha256(sbom_path):
            errors.append("SBOM checksum does not match the evidence record")
        else:
            try:
                if read_json(sbom_path, label="SBOM").get("bomFormat") != "CycloneDX":
                    errors.append("SBOM is not CycloneDX")
            except ValueError as exc:
                errors.append(str(exc))

    images = evidence.get("images")
    if not isinstance(images, dict) or not images:
        errors.append("at least one image is required")
    else:
        for name, image in sorted(images.items()):
            if not IMAGE_RE.fullmatch(str(name)) or not isinstance(image, dict):
                errors.append(f"invalid image entry: {name}")
                continue
            reference = image.get("reference")
            digest = image.get("digest")
            if not isinstance(reference, str) or not isinstance(digest, str) or not reference.endswith(f"@{digest}"):
                errors.append(f"image {name} must use a matching immutable digest reference")
            elif not DIGEST_RE.fullmatch(digest):
                errors.append(f"image {name} has an invalid digest")
            attestations = image.get("attestations")
            if not isinstance(attestations, dict):
                errors.append(f"image {name} attestations must be an object")
            elif require_attestations and not {"signature", "provenance"}.issubset(attestations):
                errors.append(f"image {name} is missing signature and/or provenance evidence")

    smoke = evidence.get("smoke")
    if require_smoke and not isinstance(smoke, dict):
        errors.append("a passing deployment smoke report is required")
    if isinstance(smoke, dict):
        smoke_path = resolve(root, Path(str(smoke.get("path") or "")))
        if not smoke_path.is_file():
            errors.append("smoke report path is unavailable for checksum validation")
        elif smoke.get("sha256") != sha256(smoke_path):
            errors.append("smoke report checksum does not match the evidence record")
        elif smoke.get("passed") is not True:
            errors.append("smoke report did not pass")
    capacity = evidence.get("capacity")
    if require_capacity and not isinstance(capacity, dict):
        errors.append("a passing capacity report is required")
    if isinstance(capacity, dict):
        capacity_path = resolve(root, Path(str(capacity.get("path") or "")))
        if not capacity_path.is_file():
            errors.append("capacity report path is unavailable for checksum validation")
        elif capacity.get("sha256") != sha256(capacity_path):
            errors.append("capacity report checksum does not match the evidence record")
        elif capacity.get("passed") is not True:
            errors.append("capacity report did not pass")
    return errors


def command_create(args: argparse.Namespace) -> int:
    evidence = build_evidence(args)
    output = resolve(args.root.resolve(), args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote digest-pinned release evidence: {output}")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    evidence_path = resolve(root, args.evidence)
    evidence = read_json(evidence_path, label="release evidence")
    errors = validation_errors(
        evidence,
        root=root,
        require_attestations=args.require_attestations,
        require_smoke=args.require_smoke,
        require_capacity=args.require_capacity,
        expected_commit=args.expected_commit,
    )
    if errors:
        raise SystemExit("Release evidence validation failed:\n- " + "\n- ".join(errors))
    print(f"Release evidence validation passed: {evidence_path}")
    return 0


def command_annotate(args: argparse.Namespace) -> int:
    """Attach immutable registry evidence after a signer has published it."""
    root = args.root.resolve()
    evidence_path = resolve(root, args.evidence)
    evidence = read_json(evidence_path, label="release evidence")
    images = evidence.get("images")
    if not isinstance(images, dict):
        raise ValueError("release evidence has no image records")
    for raw in args.attestation:
        try:
            image_name, rest = parse_named_value(raw, label="attestation")
            kind, reference = rest.split("=", 1)
        except ValueError as exc:
            raise ValueError("Attestation must be IMAGE=signature|provenance=REFERENCE") from exc
        image = images.get(image_name)
        if not isinstance(image, dict) or kind not in {"signature", "provenance"} or not reference.strip():
            raise ValueError(f"Invalid attestation: {raw!r}")
        image.setdefault("attestations", {})[kind] = reference.strip()
    if args.capacity_report:
        evidence["capacity"] = report_record(root, args.capacity_report, label="capacity report")
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Updated release attestations: {evidence_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="write release evidence from immutable inputs")
    create.add_argument("--output", required=True, type=Path)
    create.add_argument("--sbom", required=True, type=Path)
    create.add_argument("--image", action="append", default=[], help="NAME=registry/image@sha256:...")
    create.add_argument("--attestation", action="append", default=[], help="IMAGE=signature|provenance=reference")
    create.add_argument("--smoke-report", type=Path)
    create.add_argument("--capacity-report", type=Path)
    create.add_argument("--commit")
    create.add_argument("--environment", choices=("staging", "production"), required=True)
    create.add_argument("--ci-run-url", required=True)
    create.add_argument("--approved-by", required=True)
    create.add_argument("--allow-local-ci-url", action="store_true", help="test-only support for local:// CI URLs")
    create.set_defaults(func=command_create)

    validate = subparsers.add_parser("validate", help="verify an existing release-evidence record")
    validate.add_argument("--evidence", required=True, type=Path)
    validate.add_argument("--expected-commit")
    validate.add_argument("--require-attestations", action="store_true")
    validate.add_argument("--require-smoke", action="store_true")
    validate.add_argument("--require-capacity", action="store_true")
    validate.set_defaults(func=command_validate)

    annotate = subparsers.add_parser("annotate", help="record registry signature and provenance references")
    annotate.add_argument("--evidence", required=True, type=Path)
    annotate.add_argument("--attestation", action="append", default=[], help="IMAGE=signature|provenance=reference")
    annotate.add_argument("--capacity-report", type=Path)
    annotate.set_defaults(func=command_annotate)

    args = parser.parse_args()
    try:
        return args.func(args)
    except ValueError as exc:
        raise SystemExit(f"Release evidence error: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
