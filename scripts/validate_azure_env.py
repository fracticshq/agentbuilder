#!/usr/bin/env python3
"""Validate NOVA Azure deployment environment before touching Azure resources."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PLACEHOLDER_PATTERNS = (
    re.compile(r"^\s*\.\.\.\s*$"),
    re.compile(r"^\s*replace[_-]?me\s*$", re.IGNORECASE),
    re.compile(r"^\s*change[_-]?me", re.IGNORECASE),
    re.compile(r"^\s*placeholder", re.IGNORECASE),
    re.compile(r"^\s*your[_-]", re.IGNORECASE),
    re.compile(r"^\s*<[^>]+>\s*$"),
    re.compile(r"^\s*GENERATE_", re.IGNORECASE),
)

SECRET_KEYS = {
    "SECRET_KEY",
    "ADMIN_API_KEY",
    "SETTINGS_ENCRYPTION_KEY",
    "PII_ENCRYPTION_KEY",
    "MCP_SERVICE_AUTH_TOKEN",
    "QDRANT_API_KEY",
    "MONGODB_URI",
    "REDIS_URL",
    "VOYAGE_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "STRAPI_API_TOKEN",
    "OPENAI_API_KEY",
    "QWEN_API_KEY",
    "FIRECRAWL_API_KEY",
    "ATLAS_PRIVATE_KEY",
    "SESSION_SECRET",
    "DATABASE_PASSWORD",
    "APP_KEYS",
    "API_TOKEN_SALT",
    "ADMIN_JWT_SECRET",
    "TRANSFER_TOKEN_SALT",
    "ENCRYPTION_KEY",
    "JWT_SECRET",
    "AGENTBUILDER_ADMIN_API_KEY",
}

ROOT_REQUIRED = [
    "SUBSCRIPTION_ID",
    "RESOURCE_GROUP",
    "ACR_NAME",
    "ACA_ENV",
]

SERVICE_REQUIRED = {
    "api": [
        "SECRET_KEY",
        "ADMIN_API_KEY",
        "SETTINGS_ENCRYPTION_KEY",
        "PII_ENCRYPTION_KEY",
        "MONGODB_URI",
        "REDIS_URL",
        "DEFAULT_LLM_PROVIDER",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_MODEL",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_VERSION",
        "VOYAGE_API_KEY",
        "VOYAGE_BASE_URL",
        "VOYAGE_MODEL",
        "VOYAGE_RERANK_MODEL",
        "VECTOR_BACKEND",
        "VECTOR_INDEX_NAME",
        "VECTOR_DIMENSIONS",
        "STRAPI_API_TOKEN",
        "MCP_SERVICE_AUTH_TOKEN",
    ],
    "admin": [],
    "widget": [],
    "shopify": [
        "SESSION_SECRET",
        "REDIS_URL",
        "MCP_SERVICE_AUTH_TOKEN",
    ],
    "strapi": [
        "DATABASE_HOST",
        "DATABASE_NAME",
        "DATABASE_USERNAME",
        "DATABASE_PASSWORD",
        "STRAPI_API_TOKEN",
        "APP_KEYS",
        "API_TOKEN_SALT",
        "ADMIN_JWT_SECRET",
        "TRANSFER_TOKEN_SALT",
        "ENCRYPTION_KEY",
        "JWT_SECRET",
    ],
}

OPTIONAL_DERIVED = {
    "api": ["STRAPI_URL", "SHOPIFY_MCP_URL", "CORS_ALLOW_ORIGINS"],
    "admin": ["API_BASE_URL", "WIDGET_BASE_URL"],
    "widget": ["API_BASE_URL"],
    "shopify": ["CORS_ALLOW_ORIGINS"],
    "strapi": ["AGENTBUILDER_API_URL", "REACT_APP_WS_BASE_URL"],
}

URL_RULES = {
    "MONGODB_URI": {"mongodb", "mongodb+srv"},
    "REDIS_URL": {"redis", "rediss"},
    "AZURE_OPENAI_ENDPOINT": {"https"},
    "VOYAGE_BASE_URL": {"https"},
    "STRAPI_URL": {"http", "https"},
    "SHOPIFY_MCP_URL": {"http", "https"},
    "CORS_ALLOW_ORIGINS": {"http", "https"},
    "API_BASE_URL": {"http", "https"},
    "WIDGET_BASE_URL": {"http", "https"},
    "AGENTBUILDER_API_URL": {"http", "https"},
    "REACT_APP_WS_BASE_URL": {"ws", "wss"},
}


@dataclass
class CheckResult:
    service: str
    key: str
    status: str
    detail: str
    value: str | None = None


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key] = value
    return values


def is_placeholder(value: str) -> bool:
    return any(pattern.match(value) for pattern in PLACEHOLDER_PATTERNS)


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def mask_or_show(key: str, value: str, show_secrets: bool) -> str:
    if key not in SECRET_KEYS:
        return value
    if show_secrets:
        return value
    return f"sha256:{fingerprint(value)} len:{len(value)}"


def validate_url_value(key: str, value: str) -> str | None:
    allowed_schemes = URL_RULES.get(key)
    if not allowed_schemes:
        return None

    candidates = [part.strip() for part in value.split(",") if part.strip()]
    if not candidates:
        return "empty URL list"

    for candidate in candidates:
        parsed = urlparse(candidate)
        if parsed.scheme not in allowed_schemes or not parsed.netloc:
            return f"expected {sorted(allowed_schemes)} URL, got {candidate!r}"
    return None


def validate_special_shape(key: str, value: str) -> str | None:
    if key in SECRET_KEYS and len(value) < 16:
        return "secret value is too short"
    if key == "APP_KEYS":
        keys = [part.strip() for part in value.split(",") if part.strip()]
        if len(keys) < 4:
            return "APP_KEYS must contain at least 4 comma-separated keys"
        if any(len(part) < 16 for part in keys):
            return "each APP_KEYS entry must be at least 16 characters"
    if key == "VECTOR_DIMENSIONS":
        try:
            if int(value) <= 0:
                return "must be a positive integer"
        except ValueError:
            return "must be an integer"
    return validate_url_value(key, value)


def check_key(
    service: str,
    key: str,
    env: dict[str, str],
    *,
    allow_missing_secrets: bool = False,
) -> CheckResult:
    value = env.get(key, "")
    if not value.strip():
        if allow_missing_secrets and key in SECRET_KEYS:
            return CheckResult(service, key, "external", "must already exist as an Azure Container App secret ref")
        return CheckResult(service, key, "missing", "value is required")
    if is_placeholder(value):
        return CheckResult(service, key, "invalid", "value still looks like a placeholder", value)
    shape_error = validate_special_shape(key, value)
    if shape_error:
        return CheckResult(service, key, "invalid", shape_error, value)
    return CheckResult(service, key, "ok", "configured", value)


def selected_services(service: str) -> list[str]:
    if service == "all":
        return ["api", "shopify", "admin", "widget", "strapi"]
    if service == "shopify-mcp":
        return ["shopify"]
    return [service]


def build_results(
    service: str,
    env: dict[str, str],
    *,
    allow_missing_secrets: bool = False,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for key in ROOT_REQUIRED:
        results.append(check_key("azure", key, env, allow_missing_secrets=allow_missing_secrets))

    for selected in selected_services(service):
        for key in SERVICE_REQUIRED[selected]:
            results.append(check_key(selected, key, env, allow_missing_secrets=allow_missing_secrets))
        for key in OPTIONAL_DERIVED.get(selected, []):
            value = env.get(key, "")
            if value.strip():
                shape_error = validate_special_shape(key, value)
                results.append(
                    CheckResult(
                        selected,
                        key,
                        "invalid" if shape_error else "ok",
                        shape_error or "configured",
                        value,
                    )
                )
            else:
                results.append(CheckResult(selected, key, "derived", "deploy script will derive this value"))

        if selected == "strapi":
            admin_key = env.get("AGENTBUILDER_ADMIN_API_KEY") or env.get("ADMIN_API_KEY") or ""
            if admin_key.strip():
                shape_error = validate_special_shape("AGENTBUILDER_ADMIN_API_KEY", admin_key)
                results.append(
                    CheckResult(
                        selected,
                        "AGENTBUILDER_ADMIN_API_KEY",
                        "invalid" if shape_error else "ok",
                        shape_error or "configured from AGENTBUILDER_ADMIN_API_KEY or ADMIN_API_KEY",
                        admin_key,
                    )
                )
            else:
                results.append(
                    CheckResult(
                        selected,
                        "AGENTBUILDER_ADMIN_API_KEY",
                        "external" if allow_missing_secrets else "missing",
                        "must already exist as an Azure Container App secret ref" if allow_missing_secrets else "required directly or via ADMIN_API_KEY",
                    )
                )

    return results


def print_results(results: list[CheckResult], show_secrets: bool) -> None:
    for result in results:
        label = result.status.upper().ljust(7)
        value_text = ""
        if result.value is not None:
            value_text = f" value={mask_or_show(result.key, result.value, show_secrets)}"
        print(f"[{label}] {result.service}.{result.key}: {result.detail}{value_text}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env.azure")
    parser.add_argument(
        "--service",
        default="all",
        choices=["all", "api", "admin", "widget", "shopify", "shopify-mcp", "strapi"],
    )
    parser.add_argument("--show-secrets", action="store_true")
    parser.add_argument(
        "--allow-missing-secrets",
        action="store_true",
        help="Allow required secret values to be absent locally when Azure Container App secret refs already exist.",
    )
    args = parser.parse_args()

    env = dict(os.environ)
    env.update(parse_env_file(Path(args.env_file)))

    results = build_results(
        args.service,
        env,
        allow_missing_secrets=args.allow_missing_secrets,
    )
    print_results(results, args.show_secrets)

    failures = [result for result in results if result.status in {"missing", "invalid"}]
    if failures:
        print(f"\nEnvironment validation failed with {len(failures)} issue(s).", file=sys.stderr)
        return 1

    print("\nEnvironment validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
