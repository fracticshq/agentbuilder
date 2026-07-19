"""Network boundary for untrusted catalog feed URLs.

This module owns the SSRF checks and HTTP redirect handling for public JSON
feeds.  Callers may inject DNS and client implementations so service-level
compatibility wrappers can retain their established test seams.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from typing import Any, Optional
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "host.docker.internal",
    "kubernetes.default.svc",
}
_BLOCKED_HOSTNAME_SUFFIXES = (".localhost", ".local", ".internal", ".test", ".invalid")
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_MAX_JSON_FEED_REDIRECTS = 3
_JSON_FEED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AgentBuilder/1.0)",
    "Accept": "application/json",
}

PublicHostnameResolver = Callable[[str], Awaitable[None]]
JsonFeedUrlValidator = Callable[[str], Awaitable[str]]
HttpClientFactory = Callable[..., Any]


def _is_myshopify_hostname(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    store_name = host.removesuffix(".myshopify.com")
    return (
        host.endswith(".myshopify.com")
        and bool(store_name)
        and bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", store_name))
    )


def _validate_shopify_hostname(hostname: str) -> None:
    """Reject obvious local, private, and cloud-metadata destinations."""
    host = hostname.rstrip(".").lower()
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_HOSTNAME_SUFFIXES):
        raise ValueError
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ValueError


def normalize_shopify_store_url(value: Any) -> str:
    """Return a normalized Shopify store root URL or raise an actionable error."""
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("Shopify store URL is required, for example celavilifestyle.com.")

    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not hostname:
            raise ValueError
        if parsed.username or parsed.password:
            raise ValueError
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError
        host = hostname.rstrip(".").lower()
        _validate_shopify_hostname(host)
        port = f":{parsed.port}" if parsed.port else ""
    except (ValueError, TypeError):
        raise ValueError(
            "Enter a Shopify store root URL such as https://celavilifestyle.com or https://store.myshopify.com."
        ) from None

    return urlunsplit((parsed.scheme, f"{host}{port}", "", "", ""))


def normalize_authenticated_shopify_store_url(value: Any) -> str:
    """Require the canonical HTTPS Shopify host before sending an Admin token."""
    base_url = normalize_shopify_store_url(value)
    parsed = urlsplit(base_url)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or parsed.port is not None or not _is_myshopify_hostname(hostname):
        raise ValueError(
            "Authenticated Shopify sync requires the canonical HTTPS store hostname, for example https://store.myshopify.com."
        )
    return f"https://{hostname}"


def _is_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address is safe to use as an external HTTP destination."""
    return address.is_global


def _validate_public_hostname(hostname: str) -> None:
    """Reject local, reserved, and metadata hostnames before a DNS lookup."""
    host = hostname.rstrip(".").lower()
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_HOSTNAME_SUFFIXES):
        raise ValueError("URL must target a public host.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not _is_public_ip(address):
        raise ValueError("URL must target a public host.")


async def _resolve_public_hostname(hostname: str) -> None:
    """Resolve a hostname and reject DNS answers that point into private networks."""
    try:
        records = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            None,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("URL hostname could not be resolved.") from exc

    addresses = {record[4][0] for record in records if record[4]}
    if not addresses:
        raise ValueError("URL hostname could not be resolved.")

    for raw_address in addresses:
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise ValueError("URL hostname resolved to an invalid address.") from exc
        if not _is_public_ip(address):
            raise ValueError("URL hostname must resolve only to public addresses.")


async def validate_json_feed_url(
    value: Any,
    *,
    resolve_public_hostname: Optional[PublicHostnameResolver] = None,
    is_myshopify_hostname: Optional[Callable[[str], bool]] = None,
) -> str:
    """Validate a JSON feed URL, including its currently-resolved IP addresses."""
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError
        # Accessing .port intentionally validates malformed ports such as :abc.
        _ = parsed.port
    except (TypeError, ValueError):
        raise ValueError("JSON feed URL must be a public http or https URL.") from None

    host = hostname.rstrip(".").lower()
    _validate_public_hostname(host)
    check_myshopify_hostname = is_myshopify_hostname or _is_myshopify_hostname
    if check_myshopify_hostname(host) and parsed.path.rstrip("/") == "/products.json":
        raise ValueError("Shopify catalog sync must use the authenticated Admin GraphQL integration, not products.json.")
    await (resolve_public_hostname or _resolve_public_hostname)(host)
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))


async def fetch_json_feed_data(
    url: str,
    *,
    validate_url: Optional[JsonFeedUrlValidator] = None,
    client_factory: Optional[HttpClientFactory] = None,
) -> Any:
    """Fetch JSON after validating each initial and redirect destination.

    Redirects are explicitly followed only after validating the resolved target,
    which makes a private redirect target fail before an HTTP request is made.
    """
    validator = validate_url or validate_json_feed_url
    make_client = client_factory or httpx.AsyncClient
    request_url = await validator(url)
    async with make_client(timeout=30.0, follow_redirects=False) as client:
        for redirect_count in range(_MAX_JSON_FEED_REDIRECTS + 1):
            response = await client.get(request_url, headers=_JSON_FEED_HEADERS)
            is_redirect = bool(getattr(response, "is_redirect", False)) or response.status_code in _REDIRECT_STATUS_CODES
            if not is_redirect:
                break

            if redirect_count == _MAX_JSON_FEED_REDIRECTS:
                raise ValueError("Too many redirects when fetching JSON feed.")
            location = response.headers.get("Location")
            if not location:
                raise ValueError("JSON feed returned a redirect without a Location header.")
            request_url = await validator(urljoin(request_url, location))
        else:  # pragma: no cover - the loop always breaks or raises
            raise ValueError("Too many redirects when fetching JSON feed.")

        if not response.is_success:
            raise ValueError(f"HTTP {response.status_code} when fetching JSON feed")
        return response.json()
