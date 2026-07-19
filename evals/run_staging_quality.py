#!/usr/bin/env python3
"""Validate privacy-safe staging-evaluation artifacts without network access.

``--validate-only`` is the CI-safe mode. Execution is intentionally absent in
this slice: even after explicit future authorization checks pass, the runner
fails closed instead of contacting an API, model, provider, or staging system.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

# ``python evals/run_staging_quality.py`` puts ``evals/`` rather than the
# repository root on sys.path. Add the root before importing the shared
# contract so this documented invocation works without installation.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.staging_quality_contract import (
    CASE_FIXTURE_PATH,
    REVIEW_RECORDS_PATH,
    FixtureValidationError,
    sanitized_summary,
    validate_artifacts,
)


EXECUTE_ENABLED_ENV = "STAGING_QUALITY_EXECUTE_ENABLED"
TARGET_ALLOWLIST_ENV = "STAGING_QUALITY_TARGET_ALLOWLIST"


class ExecutionNotAuthorizedError(RuntimeError):
    """Raised when a future staging execution has not been explicitly allowed."""


class ExecutionUnavailableError(RuntimeError):
    """Raised because this contract-only slice intentionally has no executor."""


def _parse_allowlist(value: str | None) -> frozenset[str]:
    if not value:
        return frozenset()
    return frozenset(item.strip() for item in value.split(",") if item.strip())


def require_explicit_execute_authorization(target_profiles: Sequence[str]) -> None:
    """Fail closed unless both a dedicated flag and every target allowlist entry exist."""
    if os.getenv(EXECUTE_ENABLED_ENV) != "1":
        raise ExecutionNotAuthorizedError(f"set {EXECUTE_ENABLED_ENV}=1 to request a future staging execution")
    allowlist = _parse_allowlist(os.getenv(TARGET_ALLOWLIST_ENV))
    missing = sorted(set(target_profiles) - allowlist)
    if missing:
        raise ExecutionNotAuthorizedError(
            f"{TARGET_ALLOWLIST_ENV} must explicitly allow: {', '.join(missing)}"
        )


def execute_is_unavailable(target_profiles: Sequence[str]) -> None:
    """Apply guards, then stop: this module has no network execution implementation."""
    require_explicit_execute_authorization(target_profiles)
    raise ExecutionUnavailableError(
        "staging execution is intentionally unavailable in this contract-only slice; no network calls were made"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate schemas and privacy constraints only; this is the CI-safe mode",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="reserved for a future externally authorized staging executor; always unavailable here",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="write an aggregate-only sanitized summary after successful validation",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=CASE_FIXTURE_PATH,
        help="path to the versioned synthetic case fixture",
    )
    parser.add_argument(
        "--reviews",
        type=Path,
        default=REVIEW_RECORDS_PATH,
        help="path to the versioned review-record fixture",
    )
    args = parser.parse_args(argv)
    if args.validate_only == args.execute:
        parser.error("choose exactly one mode: --validate-only or --execute")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        cases, reviews = validate_artifacts(args.cases, args.reviews)
        summary = sanitized_summary(cases, reviews)
    except FixtureValidationError as exc:
        print(f"Staging-quality artifact validation failed: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        return int(exc.code)

    print(
        f"Validated {summary['case_count']} synthetic staging case(s) and "
        f"{summary['review_count']} review record(s) in read_only mode.",
        flush=True,
    )
    if args.json_output:
        try:
            args.json_output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"Unable to write sanitized summary: {exc}", file=sys.stderr)
            return 1

    if args.execute:
        try:
            execute_is_unavailable([case.target_profile["profile"] for case in cases.cases])
        except (ExecutionNotAuthorizedError, ExecutionUnavailableError) as exc:
            print(f"Staging-quality execution blocked: {exc}", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
