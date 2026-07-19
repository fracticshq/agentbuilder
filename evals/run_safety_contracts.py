#!/usr/bin/env python3
"""Run the versioned deterministic safety-contract regression suite.

This runner deliberately does not score model output or contact external
services.  It validates the versioned fixture, verifies that every contract
case points to a real API regression test, then invokes those test nodes.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "evals" / "cases" / "v1" / "safety_contracts.json"
CASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SUITE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
NODE_ID_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TEST_ROOT = Path("apps/api/tests")


class FixtureValidationError(ValueError):
    """Raised when a golden fixture cannot safely describe a test suite."""


@dataclass(frozen=True)
class RegressionTest:
    """An API test node that proves one deterministic safety contract."""

    path: Path
    nodeid: str

    @property
    def pytest_target(self) -> str:
        return f"{self.path.as_posix()}::{self.nodeid}"


@dataclass(frozen=True)
class SafetyContractCase:
    """Validated record from ``safety_contracts.json``."""

    case_id: str
    suite: str
    given: str
    expect: str
    regression_tests: tuple[RegressionTest, ...]


def _require_string(record: dict[str, Any], field: str, *, context: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise FixtureValidationError(f"{context}.{field} must be a non-empty string")
    return value.strip()


def _validate_test_reference(value: Any, *, context: str) -> RegressionTest:
    if not isinstance(value, dict):
        raise FixtureValidationError(f"{context} must be an object")
    if set(value) != {"path", "nodeid"}:
        raise FixtureValidationError(f"{context} must contain only path and nodeid")

    raw_path = _require_string(value, "path", context=context)
    nodeid = _require_string(value, "nodeid", context=context)
    path = Path(raw_path)

    if path.is_absolute() or ".." in path.parts or path.suffix != ".py":
        raise FixtureValidationError(f"{context}.path must be a repository-relative Python file")
    if path.parts[: len(TEST_ROOT.parts)] != TEST_ROOT.parts:
        raise FixtureValidationError(f"{context}.path must point to an API test under {TEST_ROOT}")
    if not NODE_ID_PATTERN.fullmatch(nodeid) or not nodeid.startswith("test_"):
        raise FixtureValidationError(f"{context}.nodeid must be a single test function name")

    resolved_path = REPO_ROOT / path
    if not resolved_path.is_file():
        raise FixtureValidationError(f"{context}.path does not exist: {raw_path}")

    try:
        module = ast.parse(resolved_path.read_text(encoding="utf-8"), filename=str(resolved_path))
    except SyntaxError as exc:
        raise FixtureValidationError(f"{context}.path has invalid Python syntax: {raw_path}") from exc

    declared_tests = {
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if nodeid not in declared_tests:
        raise FixtureValidationError(f"{context}.nodeid is not a test in {raw_path}: {nodeid}")

    return RegressionTest(path=path, nodeid=nodeid)


def load_cases(fixture_path: Path = FIXTURE_PATH) -> tuple[SafetyContractCase, ...]:
    """Load and strictly validate the v1 safety-contract fixture."""
    try:
        raw_fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FixtureValidationError(f"fixture does not exist: {fixture_path}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureValidationError(f"fixture is not valid JSON: {fixture_path}: {exc.msg}") from exc

    if not isinstance(raw_fixture, list) or not raw_fixture:
        raise FixtureValidationError("fixture must be a non-empty JSON array of cases")

    cases: list[SafetyContractCase] = []
    seen_ids: set[str] = set()
    seen_targets: set[str] = set()
    required_fields = {"id", "suite", "given", "expect", "regression_tests"}

    for index, raw_case in enumerate(raw_fixture):
        context = f"cases[{index}]"
        if not isinstance(raw_case, dict):
            raise FixtureValidationError(f"{context} must be an object")
        if set(raw_case) != required_fields:
            raise FixtureValidationError(
                f"{context} must contain exactly: {', '.join(sorted(required_fields))}"
            )

        case_id = _require_string(raw_case, "id", context=context)
        suite = _require_string(raw_case, "suite", context=context)
        given = _require_string(raw_case, "given", context=context)
        expect = _require_string(raw_case, "expect", context=context)
        if not CASE_ID_PATTERN.fullmatch(case_id):
            raise FixtureValidationError(f"{context}.id must be lower-kebab-case: {case_id}")
        if not SUITE_PATTERN.fullmatch(suite):
            raise FixtureValidationError(f"{context}.suite must be lower_snake_case: {suite}")
        if case_id in seen_ids:
            raise FixtureValidationError(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)

        raw_tests = raw_case.get("regression_tests")
        if not isinstance(raw_tests, list) or not raw_tests:
            raise FixtureValidationError(f"{context}.regression_tests must be a non-empty array")
        tests = tuple(
            _validate_test_reference(test, context=f"{context}.regression_tests[{test_index}]")
            for test_index, test in enumerate(raw_tests)
        )
        for test in tests:
            if test.pytest_target in seen_targets:
                raise FixtureValidationError(
                    f"regression test is referenced by more than one case: {test.pytest_target}"
                )
            seen_targets.add(test.pytest_target)

        cases.append(
            SafetyContractCase(
                case_id=case_id,
                suite=suite,
                given=given,
                expect=expect,
                regression_tests=tests,
            )
        )

    return tuple(cases)


def selected_cases(cases: Sequence[SafetyContractCase], case_ids: Sequence[str]) -> tuple[SafetyContractCase, ...]:
    """Filter validated cases while rejecting misspelled case IDs."""
    if not case_ids:
        return tuple(cases)

    requested = set(case_ids)
    available = {case.case_id for case in cases}
    unknown_ids = sorted(requested - available)
    if unknown_ids:
        raise FixtureValidationError(f"unknown case id(s): {', '.join(unknown_ids)}")
    return tuple(case for case in cases if case.case_id in requested)


def run_regression_tests(cases: Sequence[SafetyContractCase]) -> int:
    """Run the real, deterministic API tests referenced by the selected cases."""
    targets = [test.pytest_target for case in cases for test in case.regression_tests]
    environment = os.environ.copy()
    environment.setdefault("USE_AZURE_KEYVAULT", "false")
    command = [sys.executable, "-m", "pytest", "-q", *targets]
    print("Running deterministic regression tests:", flush=True)
    for target in targets:
        print(f"  - {target}", flush=True)
    completed = subprocess.run(command, cwd=REPO_ROOT, env=environment, check=False)
    return completed.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        dest="case_ids",
        help="run one case by ID; repeat to run multiple cases",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the fixture and regression-test references without running pytest",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        cases = selected_cases(load_cases(), args.case_ids)
    except FixtureValidationError as exc:
        print(f"Safety-contract fixture validation failed: {exc}", file=sys.stderr)
        return 1

    reference_count = sum(len(case.regression_tests) for case in cases)
    print(
        f"Validated {len(cases)} safety-contract case(s) with {reference_count} regression test reference(s).",
        flush=True,
    )
    if args.validate_only:
        return 0

    return run_regression_tests(cases)


if __name__ == "__main__":
    raise SystemExit(main())
