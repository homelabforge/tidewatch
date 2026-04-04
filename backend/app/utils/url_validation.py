"""URL validation utilities for SSRF (Server-Side Request Forgery) protection.

This module provides comprehensive URL validation to prevent SSRF attacks where
user-controlled URLs could be used to access internal services, cloud metadata
endpoints, or other sensitive resources.

Security Features:
- Blocks private IP ranges (RFC 1918, RFC 4193)
- Blocks loopback addresses (localhost, 127.0.0.0/8, ::1)
- Blocks link-local addresses (169.254.0.0/16, fe80::/10)
- Blocks IPv4-mapped IPv6 addresses
- Validates URL schemes (http/https only)
- DNS rebinding protection via hostname resolution
- IDN (Internationalized Domain Names) handling

References:
- OWASP SSRF Prevention Cheat Sheet
- CWE-918: Server-Side Request Forgery (SSRF)
- RFC 1918: Private Address Space
- RFC 4193: Unique Local IPv6 Unicast Addresses
"""

import ipaddress
import logging
import os
import socket
from urllib.parse import ParseResult, urlparse

from app.exceptions import SSRFProtectionError

logger = logging.getLogger(__name__)

# Private IP ranges (RFC 1918, RFC 4193, and other reserved ranges)
PRIVATE_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),  # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),  # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),  # Private Class C
    ipaddress.ip_network("127.0.0.0/8"),  # Loopback
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local (AWS metadata: 169.254.169.254)
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local addresses
    ipaddress.ip_network("0.0.0.0/8"),  # "This" network
    ipaddress.ip_network("100.64.0.0/10"),  # Shared address space (CGN)
    ipaddress.ip_network("192.0.0.0/24"),  # IETF protocol assignments
    ipaddress.ip_network("198.18.0.0/15"),  # Benchmarking
    ipaddress.ip_network("240.0.0.0/4"),  # Reserved
]

# Localhost hostnames that should be blocked
LOCALHOST_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
}


def is_private_ip(ip_address: str) -> bool:
    """Check if an IP address is private, loopback, or link-local.

    Args:
        ip_address: IP address string (IPv4 or IPv6)

    Returns:
        True if the IP is private/internal, False otherwise

    Raises:
        ValueError: If ip_address is not a valid IP address
    """
    try:
        ip_obj = ipaddress.ip_address(ip_address)

        # Check against all private ranges
        for network in PRIVATE_IP_RANGES:
            if ip_obj in network:
                return True

        # Additional checks for IPv4-mapped IPv6 addresses
        # Example: ::ffff:127.0.0.1
        if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
            return is_private_ip(str(ip_obj.ipv4_mapped))

        return False

    except ValueError:
        # Not a valid IP address
        raise ValueError(f"Invalid IP address: {ip_address}")


def resolve_hostname(hostname: str) -> str | None:
    """Resolve a hostname to its IP address.

    This is used for DNS rebinding protection - we resolve the hostname
    at validation time to check if it points to a private IP.

    Args:
        hostname: Domain name to resolve

    Returns:
        IP address string if resolution succeeds, None otherwise
    """
    try:
        # getaddrinfo returns a list of tuples: (family, type, proto, canonname, sockaddr)
        # We take the first result's sockaddr[0] which is the IP address
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        if addr_info:
            # Extract IP from sockaddr (sockaddr format differs between IPv4/IPv6)
            ip_address = str(addr_info[0][4][0])
            return ip_address
    except (socket.gaierror, socket.herror, OSError):
        # DNS resolution failed
        return None
    return None


def validate_url_for_ssrf(
    url: str,
    allowed_schemes: list[str] | None = None,
    block_private_ips: bool = True,
    resolve_dns: bool = True,
) -> ParseResult:
    """Validate a URL against SSRF protection policies.

    Args:
        url: The URL to validate
        allowed_schemes: List of allowed URL schemes (default: ["http", "https"])
        block_private_ips: If True, block private/internal IP addresses (default: True)
        resolve_dns: If True, resolve hostnames to check for DNS rebinding (default: True)

    Returns:
        Parsed URL object if validation passes

    Raises:
        SSRFProtectionError: If URL fails any validation check
        ValueError: If URL is malformed
    """
    if not url:
        raise ValueError("URL cannot be empty")

    # Set defaults
    if allowed_schemes is None:
        allowed_schemes = ["http", "https"]

    # Parse URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"Invalid URL format: {e}")

    # Validate scheme
    if parsed.scheme not in allowed_schemes:
        raise SSRFProtectionError(
            f"URL scheme '{parsed.scheme}' not allowed. "
            f"Allowed schemes: {', '.join(allowed_schemes)}"
        )

    # Extract hostname (netloc may include port, e.g., "example.com:8080")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a hostname")

    # Normalize hostname (handle IDN - Internationalized Domain Names)
    try:
        # Convert IDN to ASCII (punycode)
        hostname_ascii = hostname.encode("idna").decode("ascii").lower()
    except (UnicodeError, UnicodeDecodeError):
        raise ValueError(f"Invalid hostname: {hostname}")

    # Check against localhost hostnames
    if block_private_ips and hostname_ascii in LOCALHOST_HOSTNAMES:
        raise SSRFProtectionError(f"Blocked private/internal hostname: {hostname_ascii}")

    # Check if hostname is an IP address
    is_ip = False
    try:
        # Try to parse as IP address
        ip_obj = ipaddress.ip_address(hostname_ascii.strip("[]"))  # Remove [] for IPv6
        is_ip = True

        # Check if IP is private/internal
        if block_private_ips and is_private_ip(str(ip_obj)):
            raise SSRFProtectionError(f"Blocked private IP address: {ip_obj}")
    except ValueError:
        # Not an IP address, it's a hostname
        pass

    # DNS resolution check (only for hostnames, not IP addresses)
    if resolve_dns and not is_ip and block_private_ips:
        resolved_ip = resolve_hostname(hostname_ascii)
        if resolved_ip:
            try:
                if is_private_ip(resolved_ip):
                    raise SSRFProtectionError(
                        f"Hostname '{hostname_ascii}' resolves to private IP: {resolved_ip}"
                    )
            except ValueError:
                # Resolution returned invalid IP, continue
                pass

    return parsed


def _get_trusted_hosts() -> set[str]:
    """Get trusted hosts from TIDEWATCH_TRUSTED_HOSTS env var.

    Returns:
        Set of trusted hostnames, IPs, or CIDR ranges.
    """
    raw = os.environ.get("TIDEWATCH_TRUSTED_HOSTS", "")
    return {h.strip() for h in raw.split(",") if h.strip()} if raw else set()


def _is_trusted(hostname: str, trusted_hosts: set[str]) -> bool:
    """Check if a hostname matches any trusted host entry.

    Supports exact hostname match, exact IP match, and CIDR range match.
    Also resolves hostnames via DNS to check if resolved IPs match.

    Args:
        hostname: Hostname or IP to check.
        trusted_hosts: Set of trusted hostnames, IPs, or CIDR strings.

    Returns:
        True if the hostname is trusted.
    """
    if not trusted_hosts:
        return False

    # Exact hostname/IP match
    if hostname in trusted_hosts:
        return True

    # Check if hostname is an IP in a trusted CIDR
    try:
        ip = ipaddress.ip_address(hostname)
        for trusted in trusted_hosts:
            if "/" in trusted:
                try:
                    if ip in ipaddress.ip_network(trusted, strict=False):
                        return True
                except ValueError:
                    continue
    except ValueError:
        pass

    # DNS resolution — check if resolved IPs match trusted entries
    try:
        for _, _, _, _, addr in socket.getaddrinfo(hostname, None):
            resolved_ip = ipaddress.ip_address(addr[0])
            if str(resolved_ip) in trusted_hosts:
                return True
            for trusted in trusted_hosts:
                if "/" in trusted:
                    try:
                        if resolved_ip in ipaddress.ip_network(trusted, strict=False):
                            return True
                    except ValueError:
                        continue
    except (socket.gaierror, ValueError, OSError):
        pass

    return False


def validate_integration_url(url: str, trusted_hosts: set[str] | None = None) -> ParseResult:
    """Validate a URL for outbound integration requests.

    Used for webhooks, self-hosted APIs (VulnForge, ntfy, Gotify), and any
    admin-configured URL that triggers an outbound HTTP request. Blocks private
    IPs unless the hostname/IP matches a trusted host from TIDEWATCH_TRUSTED_HOSTS.

    Args:
        url: Integration URL to validate.
        trusted_hosts: Override for trusted hosts (defaults to env var).

    Returns:
        Parsed URL object if validation passes.

    Raises:
        SSRFProtectionError: If URL fails SSRF validation.
        ValueError: If URL is malformed.
    """
    if trusted_hosts is None:
        trusted_hosts = _get_trusted_hosts()

    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    skip_private_block = _is_trusted(hostname, trusted_hosts)

    if skip_private_block and trusted_hosts:
        logger.debug("SSRF check: trusting %s (matched trusted hosts)", hostname)

    return validate_url_for_ssrf(
        url,
        allowed_schemes=["http", "https"],
        block_private_ips=not skip_private_block,
        resolve_dns=True,
    )


def validate_smtp_host(hostname: str, trusted_hosts: set[str] | None = None) -> None:
    """Validate an SMTP hostname is not a private IP (unless trusted).

    Args:
        hostname: SMTP server hostname or IP.
        trusted_hosts: Override for trusted hosts (defaults to env var).

    Raises:
        SSRFProtectionError: If hostname resolves to a private IP and is not trusted.
    """
    if trusted_hosts is None:
        trusted_hosts = _get_trusted_hosts()

    if _is_trusted(hostname, trusted_hosts):
        return

    # Check if hostname itself is a private IP
    try:
        if is_private_ip(hostname):
            raise SSRFProtectionError(f"SMTP host is a private IP: {hostname}")
    except ValueError:
        pass  # Not an IP literal — resolve it

    try:
        for _, _, _, _, addr in socket.getaddrinfo(hostname, None):
            ip_str = str(addr[0])
            if is_private_ip(ip_str):
                raise SSRFProtectionError(
                    f"SMTP host '{hostname}' resolves to private IP: {ip_str}"
                )
    except socket.gaierror:
        raise SSRFProtectionError(f"Cannot resolve SMTP host: {hostname}")


def validate_oidc_url(url: str, trusted_hosts: set[str] | None = None) -> ParseResult:
    """Validate a URL for OIDC provider endpoints.

    Delegates to validate_integration_url with the same trusted-hosts policy.

    Args:
        url: OIDC provider URL (e.g., issuer, token endpoint, userinfo endpoint).
        trusted_hosts: Override for trusted hosts (defaults to env var).

    Returns:
        Parsed URL object if validation passes.

    Raises:
        SSRFProtectionError: If URL fails SSRF validation.
        ValueError: If URL is malformed.
    """
    return validate_integration_url(url, trusted_hosts)
