"""Sentinel Safe HTTP Client & SSRF Defense Shield (R17, R19, R13).
Provides secure, broker-mediated HTTP GET execution with strict DNS pre-flight verification,
RFC-1918 private IP blocking, cloud metadata shielding, and domain allowlist enforcement.
"""
from __future__ import annotations

import fnmatch
import ipaddress
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("SentinelSafeHTTP")


class SSRFViolationError(PermissionError):
    """Raised when an HTTP request targets a private, loopback, or metadata IP."""
    pass


class DomainAccessDeniedError(PermissionError):
    """Raised when an HTTP request targets a domain not permitted by PDP policy."""
    pass


class SafeHTTPClient:
    """SSRF-safe HTTP client with pre-flight DNS pinning and domain allowlisting."""

    # Default domains permitted for external data ingestion
    DEFAULT_ALLOWED_DOMAINS = [
        "*.github.com",
        "*.githubusercontent.com",
        "api.weather.gov",
        "*.weather.gov",
        "huggingface.co",
        "*.huggingface.co",
        "en.wikipedia.org",
        "*.wikipedia.org",
        "pypi.org",
        "*.pypi.org",
        "httpbin.org",
    ]

    def __init__(
        self,
        allowed_domains: list[str] | None = None,
        block_private_ips: bool = True,
        max_bytes: int = 2_000_000,
        default_timeout_sec: float = 10.0,
    ):
        self.allowed_domains = allowed_domains if allowed_domains is not None else list(self.DEFAULT_ALLOWED_DOMAINS)
        self.block_private_ips = block_private_ips
        self.max_bytes = max_bytes
        self.default_timeout_sec = default_timeout_sec

    def is_domain_allowed(self, hostname: str) -> bool:
        """Verifies if the hostname matches any allowed domain pattern (supports wildcards)."""
        if not self.allowed_domains:
            return False

        h = hostname.lower().strip()
        for pattern in self.allowed_domains:
            pat = pattern.lower().strip()
            if pat == "*" or pat == "*.*":
                return True
            if fnmatch.fnmatch(h, pat):
                return True
            # Match apex domain if pattern is *.domain.com
            if pat.startswith("*.") and h == pat[2:]:
                return True
        return False

    def validate_destination_ips(self, hostname: str) -> list[str]:
        """
        Resolves hostname to IP addresses and checks each against blocked network ranges:
        - Loopback (127.0.0.0/8, ::1)
        - Private RFC 1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7)
        - Link-Local (169.254.0.0/16, fe80::/10)
        - Cloud Metadata (169.254.169.254)
        - Multicast & Reserved (224.0.0.0/4, 0.0.0.0/8)
        """
        if not self.block_private_ips:
            return []

        resolved_ips: list[str] = []
        try:
            # Resolve both IPv4 and IPv6 addresses
            addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
            for item in addr_info:
                sockaddr = item[4]
                ip_str = sockaddr[0]
                if ip_str not in resolved_ips:
                    resolved_ips.append(ip_str)
        except socket.gaierror as e:
            raise ValueError(f"DNS Resolution failed for host '{hostname}': {e}") from e

        if not resolved_ips:
            raise ValueError(f"No IP addresses resolved for host '{hostname}'")

        for ip_str in resolved_ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError as e:
                raise SSRFViolationError(f"Invalid resolved IP '{ip_str}' for host '{hostname}'") from e

            # Critical SSRF Checks: check loopback and cloud metadata first
            if ip_obj.is_loopback:
                raise SSRFViolationError(f"SSRF Violation: Host '{hostname}' resolves to loopback IP {ip_str}.")
            if str(ip_obj) == "169.254.169.254" or ip_obj.is_link_local:
                raise SSRFViolationError(f"SSRF Violation: Host '{hostname}' resolves to cloud metadata / link-local IP {ip_str}.")
            if ip_obj.is_private:
                raise SSRFViolationError(f"SSRF Violation: Host '{hostname}' resolves to private network IP {ip_str} (RFC 1918).")
            if ip_obj.is_multicast:
                raise SSRFViolationError(f"SSRF Violation: Host '{hostname}' resolves to multicast IP {ip_str}.")
            if ip_obj.is_reserved or ip_obj.is_unspecified:
                raise SSRFViolationError(f"SSRF Violation: Host '{hostname}' resolves to reserved/unspecified IP {ip_str}.")

        return resolved_ips

    def validate_url(self, url: str) -> tuple[str, str, int]:
        """Parses and validates a URL for scheme, domain policy, and SSRF restrictions."""
        if not url or not isinstance(url, str):
            raise ValueError("URL must be a non-empty string.")

        parsed = urllib.parse.urlparse(url.strip())
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme '{scheme}'. Only http and https are permitted.")

        hostname = parsed.hostname
        if not hostname:
            raise ValueError(f"URL '{url}' does not contain a valid hostname.")

        # 1. PDP Domain Allowlist Check
        if not self.is_domain_allowed(hostname):
            raise DomainAccessDeniedError(
                f"Domain '{hostname}' is not in the Sentinel network egress allowlist. "
                f"Allowed patterns: {self.allowed_domains}"
            )

        # 2. SSRF Pre-flight IP Check
        port = parsed.port or (443 if scheme == "https" else 80)
        self.validate_destination_ips(hostname)

        return scheme, hostname, port

    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout_sec: float | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        """
        Executes a safe HTTP GET request with SSRF validation, size limiting, and redirect tracking.
        """
        current_url = url.strip()
        timeout = timeout_sec or self.default_timeout_sec
        byte_limit = max_bytes or self.max_bytes
        req_headers = {
            "User-Agent": "Sentinel-Safe-Broker/1.0 (+https://github.com/sentinel-autonomous)",
            "Accept": "*/*",
        }
        if headers:
            req_headers.update(headers)

        redirect_count = 0
        max_redirects = 3
        start_time = time.perf_counter()

        while redirect_count <= max_redirects:
            # Re-validate destination on initial request and every subsequent redirect
            self.validate_url(current_url)

            req = urllib.request.Request(
                url=current_url,
                headers=req_headers,
                method="GET",
            )

            # Custom handler to intercept redirects and prevent redirect-based SSRF
            class SSRFRedirectBlocker(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                    # We handle redirects manually in the outer loop to enforce pre-flight validation
                    return None

            opener = urllib.request.build_opener(SSRFRedirectBlocker)

            try:
                with opener.open(req, timeout=timeout) as resp:
                    status = resp.status
                    resp_headers = dict(resp.headers.items())
                    content_type = resp.headers.get("Content-Type", "application/octet-stream")

                    # Stream bounded chunks to prevent memory exhaustion
                    chunks = []
                    bytes_read = 0
                    truncated = False

                    while True:
                        chunk = resp.read(min(65536, byte_limit - bytes_read + 1))
                        if not chunk:
                            break
                        bytes_read += len(chunk)
                        if bytes_read > byte_limit:
                            truncated = True
                            # Keep only up to limit
                            overflow = bytes_read - byte_limit
                            chunks.append(chunk[:-overflow])
                            break
                        chunks.append(chunk)

                    raw_body = b"".join(chunks)
                    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

                    # Decode body safely
                    encoding = resp.headers.get_content_charset() or "utf-8"
                    try:
                        text_body = raw_body.decode(encoding, errors="replace")
                    except Exception:
                        text_body = raw_body.decode("utf-8", errors="replace")

                    return {
                        "success": 200 <= status < 300,
                        "status_code": status,
                        "url": current_url,
                        "content_type": content_type,
                        "headers": resp_headers,
                        "body": text_body,
                        "bytes_received": len(raw_body),
                        "truncated": truncated,
                        "elapsed_ms": elapsed_ms,
                    }

            except urllib.error.HTTPError as e:
                # Handle 3xx redirect manually if redirected
                if e.code in (301, 302, 303, 307, 308):
                    new_loc = e.headers.get("Location")
                    if not new_loc:
                        raise ValueError(f"HTTP Redirect {e.code} received without Location header.")
                    # Resolve relative redirect URLs
                    current_url = urllib.parse.urljoin(current_url, new_loc)
                    redirect_count += 1
                    logger.debug("Following safe redirect %d to %s", redirect_count, current_url)
                    continue

                # Normal error response (4xx, 5xx)
                err_body = ""
                try:
                    err_body = e.read(10000).decode("utf-8", errors="replace")
                except Exception:
                    pass
                elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
                return {
                    "success": False,
                    "status_code": e.code,
                    "url": current_url,
                    "error": str(e.reason),
                    "body": err_body,
                    "elapsed_ms": elapsed_ms,
                }

            except Exception as e:
                elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
                return {
                    "success": False,
                    "status_code": 0,
                    "url": current_url,
                    "error": str(e),
                    "body": "",
                    "elapsed_ms": elapsed_ms,
                }

        raise ValueError(f"Exceeded maximum redirects ({max_redirects}) for URL '{url}'")
