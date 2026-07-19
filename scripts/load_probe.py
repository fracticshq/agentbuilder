#!/usr/bin/env python3
"""Run a bounded, read-only capacity probe against a health endpoint.

This is an edge/readiness probe, not an LLM or RAG benchmark. It safely
measures the public serving path before a staging/production promotion without
creating conversations, calling providers, or consuming tenant data.
"""

from __future__ import annotations

import argparse
import json
import math
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPSHandler, Request, build_opener


def normalise_url(value: str, *, allow_http: bool) -> str:
    parsed = urlparse(value)
    schemes = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme not in schemes or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("--url must be an HTTPS URL without query or fragment")
    return value


def request_once(url: str, *, timeout: float, insecure_tls: bool) -> tuple[bool, float, str]:
    started = time.perf_counter()
    handlers = []
    if insecure_tls:
        handlers.append(HTTPSHandler(context=ssl._create_unverified_context()))
    opener = build_opener(*handlers)
    try:
        with opener.open(Request(url, method="GET", headers={"Accept": "application/json"}), timeout=timeout) as response:
            body = response.read()
            return response.status == 200, (time.perf_counter() - started) * 1000, f"HTTP {response.status}, {len(body)} bytes"
    except HTTPError as exc:
        return False, (time.perf_counter() - started) * 1000, f"HTTP {exc.code}"
    except URLError as exc:
        return False, (time.perf_counter() - started) * 1000, f"transport: {exc.reason}"


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 2)


def run_probe(url: str, *, requests: int, concurrency: int, timeout: float, insecure_tls: bool) -> dict[str, Any]:
    results: list[tuple[bool, float, str]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(request_once, url, timeout=timeout, insecure_tls=insecure_tls) for _ in range(requests)]
        for future in as_completed(futures):
            results.append(future.result())
    latencies = [item[1] for item in results]
    failures = [item[2] for item in results if not item[0]]
    return {
        "requests": requests,
        "successes": requests - len(failures),
        "failures": len(failures),
        "error_rate": round(len(failures) / requests, 6),
        "latency_ms": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
            "max": round(max(latencies), 2) if latencies else 0.0,
        },
        "failure_samples": failures[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="typically https://<api-host>/ready")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--max-p95-ms", type=float, default=3000.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-http", action="store_true", help="test-only support for local endpoints")
    parser.add_argument("--insecure-tls", action="store_true", help="allow an untrusted TLS certificate")
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.concurrency > args.requests:
        raise SystemExit("requests must be positive and concurrency must be between 1 and requests")
    if args.timeout <= 0 or args.max_p95_ms <= 0 or not 0 <= args.max_error_rate <= 1:
        raise SystemExit("timeout and max-p95-ms must be positive; max-error-rate must be between 0 and 1")
    try:
        url = normalise_url(args.url, allow_http=args.allow_http)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    result = run_probe(url, requests=args.requests, concurrency=args.concurrency, timeout=args.timeout, insecure_tls=args.insecure_tls)
    passed = result["error_rate"] <= args.max_error_rate and result["latency_ms"]["p95"] <= args.max_p95_ms
    report = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "passed": passed,
        "url": url,
        "thresholds": {"max_p95_ms": args.max_p95_ms, "max_error_rate": args.max_error_rate},
        "result": result,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote load probe report: {args.report}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
