"""Tests for OIDC discovery-metadata and JWKS caching.

The OIDC login/callback flow re-fetched the provider discovery document and the
JWKS on every login, adding multiple network round-trips (~5.7s observed on a
real Rauthy login). These caches eliminate the metadata + JWKS fetches on the
hot path while keeping key-rotation correctness via a bounded refetch.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from joserfc.errors import JoseError

from app.services import oidc as oidc_service


def _json_client(payload):
    """A mocked httpx.AsyncClient whose get() returns `payload` as JSON."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json = MagicMock(return_value=payload)
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=resp)
    return client


@pytest.fixture(autouse=True)
def _clear_caches():
    oidc_service.reset_oidc_discovery_cache()
    yield
    oidc_service.reset_oidc_discovery_cache()


class TestProviderMetadataCache:
    _META = {
        "issuer": "https://id.example.com",
        "jwks_uri": "https://id.example.com/certs",
        "token_endpoint": "https://id.example.com/token",
    }

    async def test_second_call_within_ttl_served_from_cache(self):
        client = _json_client(self._META)
        with (
            patch("app.services.oidc.httpx.AsyncClient", return_value=client),
            patch("app.services.oidc.validate_oidc_url"),
            patch("app.services.oidc.time.monotonic", lambda: 0.0),
        ):
            r1 = await oidc_service.get_provider_metadata("https://id.example.com")
            r2 = await oidc_service.get_provider_metadata("https://id.example.com")

        assert r1 == self._META
        assert r2 == self._META
        assert client.get.await_count == 1  # second call hit the cache

    async def test_refetched_after_ttl_expires(self):
        client = _json_client(self._META)
        clock = {"t": 0.0}
        with (
            patch("app.services.oidc.httpx.AsyncClient", return_value=client),
            patch("app.services.oidc.validate_oidc_url"),
            patch("app.services.oidc.time.monotonic", lambda: clock["t"]),
        ):
            await oidc_service.get_provider_metadata("https://id.example.com")
            clock["t"] = oidc_service._METADATA_TTL + 1.0
            await oidc_service.get_provider_metadata("https://id.example.com")

        assert client.get.await_count == 2

    async def test_reset_forces_refetch(self):
        client = _json_client(self._META)
        with (
            patch("app.services.oidc.httpx.AsyncClient", return_value=client),
            patch("app.services.oidc.validate_oidc_url"),
            patch("app.services.oidc.time.monotonic", lambda: 0.0),
        ):
            await oidc_service.get_provider_metadata("https://id.example.com")
            oidc_service.reset_oidc_discovery_cache()
            await oidc_service.get_provider_metadata("https://id.example.com")

        assert client.get.await_count == 2

    async def test_distinct_issuers_cached_separately(self):
        client = _json_client(self._META)
        with (
            patch("app.services.oidc.httpx.AsyncClient", return_value=client),
            patch("app.services.oidc.validate_oidc_url"),
            patch("app.services.oidc.time.monotonic", lambda: 0.0),
        ):
            await oidc_service.get_provider_metadata("https://id.example.com")
            await oidc_service.get_provider_metadata("https://other.example.com")

        assert client.get.await_count == 2


class TestJwksCache:
    _URI = "https://id.example.com/certs"
    _JWKS = {"keys": [{"kid": "k1"}]}

    async def test_jwks_cached_within_ttl(self):
        client = _json_client(self._JWKS)
        with (
            patch("app.services.oidc.httpx.AsyncClient", return_value=client),
            patch("app.services.oidc.time.monotonic", lambda: 0.0),
        ):
            k1 = await oidc_service._get_jwks(self._URI)
            k2 = await oidc_service._get_jwks(self._URI)

        assert k1 == self._JWKS
        assert k2 == self._JWKS
        assert client.get.await_count == 1

    async def test_allow_refresh_bounded_by_min_interval(self):
        client = _json_client(self._JWKS)
        clock = {"t": 0.0}
        with (
            patch("app.services.oidc.httpx.AsyncClient", return_value=client),
            patch("app.services.oidc.time.monotonic", lambda: clock["t"]),
        ):
            await oidc_service._get_jwks(self._URI)  # fetch #1, cached at t=0
            # A refresh request too soon must NOT refetch (bounds bad-token spam).
            await oidc_service._get_jwks(self._URI, allow_refresh=True)
            assert client.get.await_count == 1
            # Past the min interval, a refresh request refetches.
            clock["t"] = oidc_service._JWKS_MIN_REFRESH_INTERVAL + 1.0
            await oidc_service._get_jwks(self._URI, allow_refresh=True)
            assert client.get.await_count == 2


class TestVerifyIdTokenRotation:
    _CONFIG = {"client_id": "client", "issuer_url": "https://id.example.com"}
    _METADATA = {"jwks_uri": "https://id.example.com/certs", "issuer": "https://id.example.com"}

    async def test_retries_once_with_refreshed_jwks_on_rotation(self):
        # Old keys fail to verify; a refreshed JWKS (rotation) verifies on retry.
        get_jwks = AsyncMock(side_effect=[{"keys": ["old"]}, {"keys": ["new"]}])
        decoded = MagicMock()
        decoded.claims = {"sub": "user-1"}
        decode = MagicMock(side_effect=[JoseError("bad signature"), decoded])
        with (
            patch("app.services.oidc._get_jwks", get_jwks),
            patch("app.services.oidc.jwt.decode", decode),
            patch("app.services.oidc.KeySet.import_key_set"),
            patch("app.services.oidc.JWTClaimsRegistry"),
        ):
            result = await oidc_service.verify_id_token(
                "id-token", self._CONFIG, self._METADATA, "nonce-1"
            )

        assert result == {"sub": "user-1"}
        assert get_jwks.await_count == 2  # cached attempt, then bounded refresh
        assert decode.call_count == 2

    async def test_returns_none_when_retry_also_fails(self):
        get_jwks = AsyncMock(side_effect=[{"keys": ["old"]}, {"keys": ["new"]}])
        decode = MagicMock(side_effect=[JoseError("bad"), JoseError("still bad")])
        with (
            patch("app.services.oidc._get_jwks", get_jwks),
            patch("app.services.oidc.jwt.decode", decode),
            patch("app.services.oidc.KeySet.import_key_set"),
            patch("app.services.oidc.JWTClaimsRegistry"),
        ):
            result = await oidc_service.verify_id_token(
                "id-token", self._CONFIG, self._METADATA, "nonce-1"
            )

        assert result is None
