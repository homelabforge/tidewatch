"""Tests for ChangelogFetcher SSRF hardening (N1).

Covers: private/metadata targets blocked before any request, public + trusted-host
targets allowed, redirects disabled, oversize bodies truncated codepoint-safely,
and GitHub release tags percent-encoded.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.changelog import MAX_CHANGELOG_BYTES, ChangelogFetcher


def _mock_client(response=None, capture=None):
    """Return a patch target for httpx.AsyncClient.

    Records constructor kwargs into ``capture`` and yields a client whose ``.get``
    returns ``response``.
    """
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=response)

    def factory(*args, **kwargs):
        if capture is not None:
            capture["kwargs"] = kwargs
        return client

    return factory, client


def _url_response(text="release notes", status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


def _github_response(body="release notes", status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(
        return_value={"body": body, "name": "v1.0.0", "html_url": "https://x/releases/v1"}
    )
    return resp


class TestFetchURLSSRF:
    async def test_blocks_private_ip(self):
        fetcher = ChangelogFetcher()
        factory, client = _mock_client()
        with patch("app.services.changelog.httpx.AsyncClient", factory):
            result = await fetcher._fetch_url("http://10.0.0.5/CHANGELOG.md")
        assert result is None
        client.get.assert_not_called()

    async def test_blocks_metadata_endpoint(self):
        fetcher = ChangelogFetcher()
        factory, client = _mock_client()
        with patch("app.services.changelog.httpx.AsyncClient", factory):
            result = await fetcher._fetch_url("http://169.254.169.254/latest/meta-data/")
        assert result is None
        client.get.assert_not_called()

    async def test_allows_public(self):
        fetcher = ChangelogFetcher()
        factory, client = _mock_client(response=_url_response("public notes"))
        with (
            patch("app.services.changelog.httpx.AsyncClient", factory),
            patch("app.services.changelog.validate_integration_url"),
        ):
            result = await fetcher._fetch_url("https://example.com/CHANGELOG.md")
        assert result is not None
        assert result.raw_text == "public notes"
        client.get.assert_awaited_once()

    async def test_allows_trusted_host(self, monkeypatch):
        """A private IP is fetched when listed in TIDEWATCH_TRUSTED_HOSTS."""
        monkeypatch.setenv("TIDEWATCH_TRUSTED_HOSTS", "10.0.0.5")
        fetcher = ChangelogFetcher()
        factory, client = _mock_client(response=_url_response("internal notes"))
        with patch("app.services.changelog.httpx.AsyncClient", factory):
            result = await fetcher._fetch_url("http://10.0.0.5/CHANGELOG.md")
        assert result is not None
        assert result.raw_text == "internal notes"

    async def test_redirects_disabled(self):
        fetcher = ChangelogFetcher()
        capture: dict = {}
        factory, _ = _mock_client(response=_url_response(), capture=capture)
        with (
            patch("app.services.changelog.httpx.AsyncClient", factory),
            patch("app.services.changelog.validate_integration_url"),
        ):
            await fetcher._fetch_url("https://example.com/CHANGELOG.md")
        assert capture["kwargs"]["follow_redirects"] is False

    async def test_truncates_oversize_body(self):
        fetcher = ChangelogFetcher()
        oversize = "x" * (MAX_CHANGELOG_BYTES + 5000)
        factory, _ = _mock_client(response=_url_response(oversize))
        with (
            patch("app.services.changelog.httpx.AsyncClient", factory),
            patch("app.services.changelog.validate_integration_url"),
        ):
            result = await fetcher._fetch_url("https://example.com/CHANGELOG.md")
        assert result is not None
        assert len(result.raw_text.encode("utf-8")) <= MAX_CHANGELOG_BYTES

    async def test_truncation_no_unicode_crash(self):
        """Truncating mid-multibyte must not raise and must yield valid text."""
        fetcher = ChangelogFetcher()
        # "€" is 3 UTF-8 bytes; choose a count that pushes past the cap and is
        # guaranteed to split a codepoint at the byte boundary.
        body = "€" * (MAX_CHANGELOG_BYTES // 3 + 1000)
        factory, _ = _mock_client(response=_url_response(body))
        with (
            patch("app.services.changelog.httpx.AsyncClient", factory),
            patch("app.services.changelog.validate_integration_url"),
        ):
            result = await fetcher._fetch_url("https://example.com/CHANGELOG.md")
        assert result is not None
        assert len(result.raw_text.encode("utf-8")) <= MAX_CHANGELOG_BYTES
        # Re-encoding must round-trip cleanly (no lone surrogate / partial byte).
        result.raw_text.encode("utf-8")


class TestFetchGithubReleaseQuoting:
    async def test_tag_is_percent_encoded(self):
        fetcher = ChangelogFetcher()
        factory, client = _mock_client(response=_github_response("notes"))
        with patch("app.services.changelog.httpx.AsyncClient", factory):
            await fetcher._fetch_github_release("owner/repo", "feat/x?y")
        called_url = client.get.call_args.args[0]
        assert "feat%2Fx%3Fy" in called_url
        assert "feat/x?y" not in called_url

    async def test_redirects_disabled(self):
        fetcher = ChangelogFetcher()
        capture: dict = {}
        factory, _ = _mock_client(response=_github_response("notes"), capture=capture)
        with patch("app.services.changelog.httpx.AsyncClient", factory):
            await fetcher._fetch_github_release("owner/repo", "1.0.0")
        assert capture["kwargs"]["follow_redirects"] is False
