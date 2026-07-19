#!/usr/bin/env python3
"""Exercise the non-secret health contract of a deployed Agent Builder release.

The script is intentionally read-only. It proves that the public API is live,
ready against MongoDB and Redis, running with production-safe switches, and
that optional frontend and Shopify services point at the expected API.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def normalise_url(value: str, *, allow_http: bool) -> str:
    parsed = urlparse(value)
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme not in allowed_schemes or not parsed.netloc or parsed.query or parsed.fragment:
        scheme_hint = "HTTP(S)" if allow_http else "HTTPS"
        raise ValueError(f"Expected a plain {scheme_hint} service URL, got {value!r}")
    return value.rstrip("/")


def request(url: str, *, timeout: float, insecure_tls: bool) -> tuple[int, bytes, str]:
    context = ssl._create_unverified_context() if insecure_tls else None
    handlers = [NoRedirect()]
    if context:
        handlers.append(HTTPSHandler(context=context))
    opener = build_opener(*handlers)
    try:
        with opener.open(Request(url, method="GET", headers={"Accept": "application/json, text/plain, */*"}), timeout=timeout) as response:
            return response.status, response.read(), response.headers.get_content_type()
    except HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get_content_type()
    except URLError as exc:
        raise RuntimeError(f"request failed: {exc.reason}") from exc


def check(checks: list[dict[str, Any]], name: str, *, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": passed, "detail": detail})
    print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}")


def json_response(checks: list[dict[str, Any]], name: str, url: str, *, timeout: float, insecure_tls: bool) -> dict[str, Any] | None:
    try:
        status, body, _content_type = request(url, timeout=timeout, insecure_tls=insecure_tls)
    except RuntimeError as exc:
        check(checks, name, passed=False, detail=str(exc))
        return None
    if status != 200:
        check(checks, name, passed=False, detail=f"expected HTTP 200, got {status}")
        return None
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        check(checks, name, passed=False, detail="response is not valid JSON")
        return None
    if not isinstance(payload, dict):
        check(checks, name, passed=False, detail="response is not a JSON object")
        return None
    return payload


def check_api(args: argparse.Namespace, checks: list[dict[str, Any]]) -> None:
    api = args.api_url
    live = json_response(checks, "api.live", f"{api}/live", timeout=args.timeout, insecure_tls=args.insecure_tls)
    if live is not None:
        check(checks, "api.live.status", passed=live.get("status") == "alive", detail=f"status={live.get('status')!r}")

    ready = json_response(checks, "api.ready", f"{api}/ready", timeout=args.timeout, insecure_tls=args.insecure_tls)
    if ready is not None:
        dependencies = ready.get("dependencies") if isinstance(ready.get("dependencies"), dict) else {}
        ready_ok = ready.get("status") == "healthy" and dependencies.get("mongodb") == "healthy" and dependencies.get("redis") == "healthy"
        check(checks, "api.ready.dependencies", passed=ready_ok, detail=f"status={ready.get('status')!r}, dependencies={dependencies}")

    config = json_response(checks, "api.config", f"{api}/config-check", timeout=args.timeout, insecure_tls=args.insecure_tls)
    if config is not None:
        expected = {
            "environment": args.expected_environment,
            "debug": False,
            "mongodb_required": True,
            "redis_required": True,
            "admin_key_bypass_allowed": False,
            "metrics_enabled": True,
        }
        for key, value in expected.items():
            check(checks, f"api.config.{key}", passed=config.get(key) == value, detail=f"expected {value!r}, got {config.get(key)!r}")


def check_runtime_config(args: argparse.Namespace, checks: list[dict[str, Any]], *, name: str, url: str) -> None:
    try:
        status, body, _content_type = request(f"{url}/runtime-config.js", timeout=args.timeout, insecure_tls=args.insecure_tls)
    except RuntimeError as exc:
        check(checks, f"{name}.runtime_config", passed=False, detail=str(exc))
        return
    content = body.decode("utf-8", errors="replace")
    expected = args.api_url
    check(
        checks,
        f"{name}.runtime_config",
        passed=status == 200 and expected in content,
        detail=f"expected API URL {expected!r}; HTTP {status}",
    )


def check_shopify(args: argparse.Namespace, checks: list[dict[str, Any]]) -> None:
    try:
        status, body, _content_type = request(f"{args.shopify_url}/health", timeout=args.timeout, insecure_tls=args.insecure_tls)
    except RuntimeError as exc:
        check(checks, "shopify.health", passed=False, detail=str(exc))
        return
    check(checks, "shopify.health", passed=status == 200 and body.strip() == b"OK", detail=f"HTTP {status}, body={body[:40]!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--admin-url")
    parser.add_argument("--widget-url")
    parser.add_argument("--shopify-url")
    parser.add_argument("--expected-environment", default="production", choices=("staging", "production"))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-http", action="store_true", help="test-only support for non-TLS local endpoints")
    parser.add_argument("--insecure-tls", action="store_true", help="allow an untrusted TLS certificate")
    args = parser.parse_args()
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")
    try:
        args.api_url = normalise_url(args.api_url, allow_http=args.allow_http)
        for key in ("admin_url", "widget_url", "shopify_url"):
            if getattr(args, key):
                setattr(args, key, normalise_url(getattr(args, key), allow_http=args.allow_http))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    checks: list[dict[str, Any]] = []
    check_api(args, checks)
    if args.admin_url:
        check_runtime_config(args, checks, name="admin", url=args.admin_url)
    if args.widget_url:
        check_runtime_config(args, checks, name="widget", url=args.widget_url)
    if args.shopify_url:
        check_shopify(args, checks)

    passed = all(item["passed"] for item in checks)
    report = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "passed": passed,
        "api_url": args.api_url,
        "checks": checks,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote smoke report: {args.report}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
