import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.catalog import _require_catalog_brand_access
from app.auth.models import User, UserRole
from app.services import catalog_service


@pytest.mark.asyncio
async def test_json_feed_urls_reject_private_and_non_http_destinations():
    for url in (
        "http://127.0.0.1/feed.json",
        "http://[::1]/feed.json",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/computeMetadata/v1",
        "file:///etc/passwd",
        "https://user:password@example.com/feed.json",
    ):
        with pytest.raises(ValueError):
            await catalog_service.validate_json_feed_url(url)


@pytest.mark.asyncio
async def test_json_feed_urls_validate_dns_answers(monkeypatch):
    async def private_dns(_hostname):
        raise ValueError("URL hostname must resolve only to public addresses.")

    monkeypatch.setattr(catalog_service, "_resolve_public_hostname", private_dns)
    with pytest.raises(ValueError, match="public addresses"):
        await catalog_service.validate_json_feed_url("https://feed.example.com/catalog.json")


@pytest.mark.asyncio
async def test_json_feed_url_accepts_public_https_with_safe_dns(monkeypatch):
    resolved_hosts = []

    async def public_dns(hostname):
        resolved_hosts.append(hostname)

    monkeypatch.setattr(catalog_service, "_resolve_public_hostname", public_dns)
    assert await catalog_service.validate_json_feed_url("https://Feed.Example.com/catalog.json?format=json") == (
        "https://Feed.Example.com/catalog.json?format=json"
    )
    assert resolved_hosts == ["feed.example.com"]


@pytest.mark.asyncio
async def test_json_feed_rejects_private_redirect_before_following(monkeypatch):
    class Response:
        status_code = 302
        is_redirect = True
        headers = {"Location": "http://127.0.0.1/private-feed.json"}
        is_success = False

    class Client:
        def __init__(self):
            self.urls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, headers):
            self.urls.append(url)
            return Response()

    client = Client()

    async def public_dns(_hostname):
        return None

    monkeypatch.setattr(catalog_service, "_resolve_public_hostname", public_dns)
    monkeypatch.setattr(catalog_service.httpx, "AsyncClient", lambda **_kwargs: client)

    with pytest.raises(ValueError, match="public host"):
        await catalog_service.fetch_json_feed("https://feed.example.com/catalog.json")
    assert client.urls == ["https://feed.example.com/catalog.json"]


@pytest.mark.asyncio
async def test_catalog_operations_enforce_shared_brand_access_dependency():
    user = User(
        _id="user-1",
        email="brand-admin@example.com",
        username="brand-admin",
        password_hash="not-used-in-this-test",
        role=UserRole.BRAND_ADMIN,
        brands=["brand-a"],
    )

    assert await _require_catalog_brand_access("brand-a", user) is user
    with pytest.raises(HTTPException) as denied:
        await _require_catalog_brand_access("brand-b", user)
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_catalog_operations_reject_non_operator_roles_even_with_brand_access():
    user = User(
        _id="user-1",
        email="member@brand-a.example",
        username="member",
        password_hash="not-used-in-this-test",
        role=UserRole.USER,
        brands=["brand-a"],
    )

    with pytest.raises(HTTPException) as denied:
        await _require_catalog_brand_access("brand-a", user)
    assert denied.value.status_code == 403
