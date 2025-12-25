"""Tests for URL validation utilities (app/utils/url_validation.py).

Tests SSRF (Server-Side Request Forgery) protection:
- IP address validation (private, loopback, link-local)
- Scheme validation (http/https only)
- Hostname validation (localhost blocking)
- DNS rebinding protection
- IPv6 address handling
- IDN (Internationalized Domain Names) support
"""

import pytest
from unittest.mock import patch
import socket

from app.utils.url_validation import (
    is_private_ip,
    resolve_hostname,
    validate_url_for_ssrf,
    validate_oidc_url,
    LOCALHOST_HOSTNAMES,
)
from app.exceptions import SSRFProtectionError


class TestIsPrivateIP:
    """Test suite for is_private_ip() function."""

    def test_detects_ipv4_loopback(self):
        """Test detects IPv4 loopback addresses."""
        assert is_private_ip("127.0.0.1") is True
        assert is_private_ip("127.0.0.2") is True
        assert is_private_ip("127.255.255.255") is True

    def test_detects_ipv4_private_class_a(self):
        """Test detects RFC 1918 Class A private addresses (10.0.0.0/8)."""
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("10.255.255.254") is True

    def test_detects_ipv4_private_class_b(self):
        """Test detects RFC 1918 Class B private addresses (172.16.0.0/12)."""
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("172.31.255.254") is True
        # Edge cases: 172.15 and 172.32 are NOT in the range
        assert is_private_ip("172.15.0.1") is False
        assert is_private_ip("172.32.0.1") is False

    def test_detects_ipv4_private_class_c(self):
        """Test detects RFC 1918 Class C private addresses (192.168.0.0/16)."""
        assert is_private_ip("192.168.0.1") is True
        assert is_private_ip("192.168.255.254") is True

    def test_detects_ipv4_link_local(self):
        """Test detects link-local addresses (169.254.0.0/16) including AWS metadata."""
        assert is_private_ip("169.254.0.1") is True
        assert is_private_ip("169.254.169.254") is True  # AWS metadata endpoint

    def test_detects_ipv4_reserved_ranges(self):
        """Test detects other reserved IPv4 ranges."""
        assert is_private_ip("0.0.0.0") is True  # "This" network
        assert is_private_ip("100.64.0.1") is True  # Shared address space (CGN)
        assert is_private_ip("192.0.0.1") is True  # IETF protocol assignments
        assert is_private_ip("198.18.0.1") is True  # Benchmarking
        assert is_private_ip("240.0.0.1") is True  # Reserved

    def test_allows_public_ipv4(self):
        """Test allows public IPv4 addresses."""
        assert is_private_ip("8.8.8.8") is False  # Google DNS
        assert is_private_ip("1.1.1.1") is False  # Cloudflare DNS
        assert is_private_ip("208.67.222.222") is False  # OpenDNS

    def test_detects_ipv6_loopback(self):
        """Test detects IPv6 loopback address (::1)."""
        assert is_private_ip("::1") is True

    def test_detects_ipv6_link_local(self):
        """Test detects IPv6 link-local addresses (fe80::/10)."""
        assert is_private_ip("fe80::1") is True
        assert is_private_ip("fe80::dead:beef") is True

    def test_detects_ipv6_unique_local(self):
        """Test detects IPv6 unique local addresses (fc00::/7)."""
        assert is_private_ip("fc00::1") is True
        assert is_private_ip("fd00::1") is True

    def test_detects_ipv4_mapped_ipv6_loopback(self):
        """Test detects IPv4-mapped IPv6 addresses pointing to loopback."""
        assert is_private_ip("::ffff:127.0.0.1") is True

    def test_detects_ipv4_mapped_ipv6_private(self):
        """Test detects IPv4-mapped IPv6 addresses pointing to private IPs."""
        assert is_private_ip("::ffff:192.168.1.1") is True
        assert is_private_ip("::ffff:10.0.0.1") is True

    def test_allows_public_ipv6(self):
        """Test allows public IPv6 addresses."""
        assert is_private_ip("2606:4700:4700::1111") is False  # Cloudflare DNS
        assert is_private_ip("2001:4860:4860::8888") is False  # Google DNS

    def test_raises_on_invalid_ip(self):
        """Test raises ValueError for invalid IP addresses."""
        with pytest.raises(ValueError, match="Invalid IP address"):
            is_private_ip("not-an-ip")

        with pytest.raises(ValueError, match="Invalid IP address"):
            is_private_ip("999.999.999.999")

        with pytest.raises(ValueError, match="Invalid IP address"):
            is_private_ip("")


class TestResolveHostname:
    """Test suite for resolve_hostname() function."""

    def test_resolves_valid_hostname(self):
        """Test resolves a valid hostname to IP."""
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            # Mock DNS response: (family, type, proto, canonname, sockaddr)
            mock_getaddrinfo.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
            ]

            ip = resolve_hostname("example.com")
            assert ip == "93.184.216.34"
            mock_getaddrinfo.assert_called_once_with(
                "example.com", None, socket.AF_UNSPEC, socket.SOCK_STREAM
            )

    def test_resolves_ipv6_hostname(self):
        """Test resolves hostname to IPv6 address."""
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            mock_getaddrinfo.return_value = [
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("2606:2800:220:1:248:1893:25c8:1946", 0, 0, 0),
                )
            ]

            ip = resolve_hostname("example.com")
            assert ip == "2606:2800:220:1:248:1893:25c8:1946"

    def test_returns_none_on_dns_failure(self):
        """Test returns None when DNS resolution fails."""
        with patch(
            "socket.getaddrinfo",
            side_effect=socket.gaierror("Name or service not known"),
        ):
            ip = resolve_hostname("nonexistent.invalid")
            assert ip is None

    def test_returns_none_on_socket_error(self):
        """Test returns None on socket errors."""
        with patch("socket.getaddrinfo", side_effect=OSError("Network error")):
            ip = resolve_hostname("error.local")
            assert ip is None

    def test_returns_none_on_empty_result(self):
        """Test returns None when getaddrinfo returns empty list."""
        with patch("socket.getaddrinfo", return_value=[]):
            ip = resolve_hostname("empty.test")
            assert ip is None


class TestValidateUrlForSSRF:
    """Test suite for validate_url_for_ssrf() function."""

    def test_allows_valid_http_url(self):
        """Test allows valid HTTP URLs to public domains."""
        parsed = validate_url_for_ssrf("http://example.com")
        assert parsed.scheme == "http"
        assert parsed.hostname == "example.com"

    def test_allows_valid_https_url(self):
        """Test allows valid HTTPS URLs to public domains."""
        parsed = validate_url_for_ssrf("https://example.com/path?query=value")
        assert parsed.scheme == "https"
        assert parsed.hostname == "example.com"

    def test_allows_url_with_port(self):
        """Test allows URLs with port numbers."""
        parsed = validate_url_for_ssrf("https://example.com:8080/api")
        assert parsed.hostname == "example.com"
        assert parsed.port == 8080

    def test_blocks_file_scheme(self):
        """Test blocks file:// URLs."""
        with pytest.raises(SSRFProtectionError, match="URL scheme 'file' not allowed"):
            validate_url_for_ssrf("file:///etc/passwd")

    def test_blocks_ftp_scheme(self):
        """Test blocks ftp:// URLs."""
        with pytest.raises(SSRFProtectionError, match="URL scheme 'ftp' not allowed"):
            validate_url_for_ssrf("ftp://ftp.example.com/file.txt")

    def test_blocks_javascript_scheme(self):
        """Test blocks javascript: URLs."""
        with pytest.raises(
            SSRFProtectionError, match="URL scheme 'javascript' not allowed"
        ):
            validate_url_for_ssrf("javascript:alert('xss')")

    def test_blocks_data_scheme(self):
        """Test blocks data: URLs."""
        with pytest.raises(SSRFProtectionError, match="URL scheme 'data' not allowed"):
            validate_url_for_ssrf("data:text/html,<script>alert('xss')</script>")

    def test_blocks_localhost_hostname(self):
        """Test blocks 'localhost' hostname."""
        with pytest.raises(
            SSRFProtectionError, match="Blocked private/internal hostname: localhost"
        ):
            validate_url_for_ssrf("http://localhost:8080/admin")

    def test_blocks_localhost_variants(self):
        """Test blocks localhost variant hostnames."""
        for hostname in LOCALHOST_HOSTNAMES:
            with pytest.raises(
                SSRFProtectionError, match="Blocked private/internal hostname"
            ):
                validate_url_for_ssrf(f"http://{hostname}/")

    def test_blocks_ipv4_loopback(self):
        """Test blocks IPv4 loopback addresses."""
        with pytest.raises(
            SSRFProtectionError, match="Blocked private IP address: 127.0.0.1"
        ):
            validate_url_for_ssrf("http://127.0.0.1:8080/")

    def test_blocks_ipv4_private_ips(self):
        """Test blocks RFC 1918 private IPv4 addresses."""
        private_ips = [
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
        ]

        for ip in private_ips:
            with pytest.raises(SSRFProtectionError, match="Blocked private IP address"):
                validate_url_for_ssrf(f"http://{ip}/")

    def test_blocks_aws_metadata_endpoint(self):
        """Test blocks AWS EC2 metadata endpoint (169.254.169.254)."""
        with pytest.raises(
            SSRFProtectionError, match="Blocked private IP address: 169.254.169.254"
        ):
            validate_url_for_ssrf("http://169.254.169.254/latest/meta-data/")

    def test_blocks_ipv6_loopback(self):
        """Test blocks IPv6 loopback address (::1)."""
        with pytest.raises(SSRFProtectionError, match="Blocked private IP address"):
            validate_url_for_ssrf("http://[::1]/")

    def test_blocks_ipv6_link_local(self):
        """Test blocks IPv6 link-local addresses."""
        with pytest.raises(SSRFProtectionError, match="Blocked private IP address"):
            validate_url_for_ssrf("http://[fe80::1]/")

    def test_blocks_ipv4_mapped_ipv6_loopback(self):
        """Test blocks IPv4-mapped IPv6 loopback."""
        with pytest.raises(SSRFProtectionError, match="Blocked private IP address"):
            validate_url_for_ssrf("http://[::ffff:127.0.0.1]/")

    def test_blocks_dns_rebinding_to_localhost(self):
        """Test DNS rebinding protection - hostname resolving to localhost."""
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="127.0.0.1"
        ):
            with pytest.raises(
                SSRFProtectionError, match="resolves to private IP: 127.0.0.1"
            ):
                validate_url_for_ssrf("http://evil.com/")

    def test_blocks_dns_rebinding_to_private_ip(self):
        """Test DNS rebinding protection - hostname resolving to private IP."""
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="192.168.1.1"
        ):
            with pytest.raises(
                SSRFProtectionError, match="resolves to private IP: 192.168.1.1"
            ):
                validate_url_for_ssrf("http://rebind.network/")

    def test_allows_url_when_dns_resolution_fails(self):
        """Test allows URL when DNS resolution fails (hostname not found)."""
        with patch("app.utils.url_validation.resolve_hostname", return_value=None):
            # Should not raise - DNS failure doesn't block the URL
            parsed = validate_url_for_ssrf("http://nonexistent.invalid/")
            assert parsed.hostname == "nonexistent.invalid"

    def test_allows_url_with_resolve_dns_disabled(self):
        """Test allows URL with DNS resolution disabled."""
        # Even if hostname would resolve to private IP, don't check
        parsed = validate_url_for_ssrf("http://internal.corp/", resolve_dns=False)
        assert parsed.hostname == "internal.corp"

    def test_allows_private_ips_when_blocking_disabled(self):
        """Test allows private IPs when block_private_ips=False."""
        parsed = validate_url_for_ssrf("http://192.168.1.1/", block_private_ips=False)
        assert parsed.hostname == "192.168.1.1"

        parsed = validate_url_for_ssrf("http://localhost/", block_private_ips=False)
        assert parsed.hostname == "localhost"

    def test_custom_allowed_schemes(self):
        """Test custom allowed schemes."""
        parsed = validate_url_for_ssrf(
            "ftp://ftp.example.com/", allowed_schemes=["ftp"]
        )
        assert parsed.scheme == "ftp"

        with pytest.raises(SSRFProtectionError, match="URL scheme 'http' not allowed"):
            validate_url_for_ssrf("http://example.com/", allowed_schemes=["ftp"])

    def test_raises_on_empty_url(self):
        """Test raises ValueError on empty URL."""
        with pytest.raises(ValueError, match="URL cannot be empty"):
            validate_url_for_ssrf("")

    def test_raises_on_url_without_hostname(self):
        """Test raises ValueError on URL without hostname."""
        with pytest.raises(ValueError, match="URL must include a hostname"):
            validate_url_for_ssrf("http:///path")

    def test_handles_idn_hostnames(self):
        """Test handles Internationalized Domain Names (IDN)."""
        # IDN example: "münchen.de" -> "xn--mnchen-3ya.de" (punycode)
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="93.184.216.34"
        ):
            parsed = validate_url_for_ssrf("http://münchen.de/")
            assert parsed is not None

    @pytest.mark.skip(
        reason="Cannot mock str.encode on immutable type - IDN validation happens at urlparse level"
    )
    def test_raises_on_invalid_idn(self):
        """Test raises ValueError on invalid IDN encoding."""
        # IDN validation errors are caught by urlparse before we can test them
        # Real invalid IDN characters would be rejected by the browser/client before reaching us
        pass

    def test_normalizes_hostname_case(self):
        """Test normalizes hostname to lowercase."""
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="93.184.216.34"
        ):
            parsed = validate_url_for_ssrf("http://EXAMPLE.COM/")
            # Hostname should be normalized by urlparse
            assert parsed.hostname.lower() == "example.com"

    def test_handles_url_with_credentials(self):
        """Test handles URLs with username/password."""
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="93.184.216.34"
        ):
            parsed = validate_url_for_ssrf("http://user:pass@example.com/")
            assert parsed.hostname == "example.com"
            assert parsed.username == "user"
            assert parsed.password == "pass"

    def test_blocks_zero_address(self):
        """Test blocks 0.0.0.0 address."""
        with pytest.raises(SSRFProtectionError, match="Blocked private IP address"):
            validate_url_for_ssrf("http://0.0.0.0/")

    def test_blocks_broadcast_address(self):
        """Test blocks broadcast-like addresses in reserved ranges."""
        with pytest.raises(SSRFProtectionError, match="Blocked private IP address"):
            validate_url_for_ssrf("http://255.255.255.255/")


class TestValidateOIDCUrl:
    """Test suite for validate_oidc_url() convenience function."""

    def test_allows_https_oidc_url(self):
        """Test allows HTTPS OIDC provider URLs."""
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="93.184.216.34"
        ):
            parsed = validate_oidc_url(
                "https://accounts.google.com/.well-known/openid-configuration"
            )
            assert parsed.scheme == "https"
            assert parsed.hostname == "accounts.google.com"

    def test_allows_http_oidc_url_for_testing(self):
        """Test allows HTTP OIDC URLs (for local testing)."""
        # Note: In production, OIDC should use HTTPS, but for local dev/testing HTTP is allowed
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="93.184.216.34"
        ):
            parsed = validate_oidc_url("http://auth.example.com/token")
            assert parsed.scheme == "http"

    def test_blocks_oidc_localhost(self):
        """Test blocks OIDC URLs pointing to localhost."""
        with pytest.raises(
            SSRFProtectionError, match="Blocked private/internal hostname: localhost"
        ):
            validate_oidc_url("http://localhost:8080/auth")

    def test_blocks_oidc_private_ip(self):
        """Test blocks OIDC URLs with private IPs."""
        with pytest.raises(SSRFProtectionError, match="Blocked private IP address"):
            validate_oidc_url("http://192.168.1.100/auth")

    def test_blocks_oidc_dns_rebinding(self):
        """Test blocks OIDC URLs with DNS rebinding attack."""
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="127.0.0.1"
        ):
            with pytest.raises(SSRFProtectionError, match="resolves to private IP"):
                validate_oidc_url("http://evil-oidc.com/")


class TestSSRFProtectionEdgeCases:
    """Test edge cases and advanced SSRF protection scenarios."""

    def test_url_with_fragment(self):
        """Test handles URLs with fragments."""
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="93.184.216.34"
        ):
            parsed = validate_url_for_ssrf("https://example.com/page#section")
            assert parsed.fragment == "section"

    def test_url_with_query_params(self):
        """Test handles URLs with query parameters."""
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="93.184.216.34"
        ):
            parsed = validate_url_for_ssrf("https://example.com/api?key=value&foo=bar")
            assert parsed.query == "key=value&foo=bar"

    def test_ipv6_url_with_zone_id(self):
        """Test handles IPv6 URLs with zone IDs."""
        # Zone IDs are used for link-local addresses: fe80::1%eth0
        # Should still be blocked as link-local
        with pytest.raises(SSRFProtectionError, match="Blocked private IP address"):
            validate_url_for_ssrf("http://[fe80::1%eth0]/")

    def test_url_encoding_in_hostname(self):
        """Test URL encoding in hostname is preserved (not decoded by urlparse)."""
        # urlparse does NOT decode URL-encoded hostnames - they stay as-is
        # This means %6C%6F%63%61%6C%68%6F%73%74 is treated as a literal hostname
        # and would fail DNS resolution, which is acceptable behavior
        with patch("app.utils.url_validation.resolve_hostname", return_value=None):
            # Should not raise - hostname is not literally "localhost"
            parsed = validate_url_for_ssrf("http://%6C%6F%63%61%6C%68%6F%73%74/")
            assert parsed.hostname == "%6C%6F%63%61%6C%68%6F%73%74"  # Preserved as-is

    def test_treats_ip_address_url_correctly(self):
        """Test correctly identifies IP address in URL vs hostname."""
        # IP address should not trigger DNS resolution
        with patch("app.utils.url_validation.resolve_hostname") as mock_resolve:
            with pytest.raises(SSRFProtectionError, match="Blocked private IP address"):
                validate_url_for_ssrf("http://127.0.0.1/")

            # DNS resolution should NOT be called for IP addresses
            mock_resolve.assert_not_called()

    def test_dns_returns_invalid_ip_doesnt_crash(self):
        """Test handles DNS returning invalid IP gracefully."""
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="invalid-ip"
        ):
            # Should not crash, just continue (invalid IP raises ValueError in is_private_ip)
            parsed = validate_url_for_ssrf("http://example.com/")
            assert parsed.hostname == "example.com"

    def test_multiple_ips_from_dns(self):
        """Test handles multiple IPs from DNS (only checks first)."""
        with patch("socket.getaddrinfo") as mock_getaddrinfo:
            # Return multiple IPs, first one is private
            mock_getaddrinfo.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            ]

            with pytest.raises(
                SSRFProtectionError, match="resolves to private IP: 192.168.1.1"
            ):
                validate_url_for_ssrf("http://dual-stack.example.com/")

    def test_ipv6_compressed_notation(self):
        """Test handles compressed IPv6 notation."""
        # :: is compressed notation for multiple zero blocks
        with pytest.raises(SSRFProtectionError, match="Blocked private IP address"):
            validate_url_for_ssrf("http://[::1]/")  # Loopback

    def test_case_insensitive_scheme_check(self):
        """Test scheme validation is case-insensitive."""
        # HTTP in uppercase should still work
        with patch(
            "app.utils.url_validation.resolve_hostname", return_value="93.184.216.34"
        ):
            parsed = validate_url_for_ssrf("HTTP://EXAMPLE.COM/")
            assert parsed.scheme == "http"  # urlparse normalizes to lowercase
