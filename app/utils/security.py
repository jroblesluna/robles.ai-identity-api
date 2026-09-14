"""Security helpers: URL/SSRF validation and (optional) API key auth.

These utilities harden the public endpoints without changing the request/response
contract used by the frontend when no API key is configured.
"""
import ipaddress
import os
import socket
from urllib.parse import urlparse

from fastapi import Header, HTTPException

# ── Outbound image fetch hardening (anti-SSRF) ──────────────────────────────
# Only allow fetching images from these hosts. Comma-separated env override.
# Defaults cover Firebase Storage download URLs and the project bucket.
_DEFAULT_ALLOWED_HOSTS = [
    "firebasestorage.googleapis.com",
    "storage.googleapis.com",
]

# Timeout (seconds) for any outbound image download.
IMAGE_FETCH_TIMEOUT = float(os.getenv("IMAGE_FETCH_TIMEOUT", "15"))


def _allowed_image_hosts() -> list[str]:
    extra = os.getenv("ALLOWED_IMAGE_HOSTS", "")
    hosts = list(_DEFAULT_ALLOWED_HOSTS)
    if extra.strip():
        hosts.extend(h.strip().lower() for h in extra.split(",") if h.strip())
    return hosts


def _resolves_to_private_ip(hostname: str) -> bool:
    """True if the hostname resolves to a private/loopback/link-local address."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # Cannot resolve -> treat as unsafe.
        return True
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            return True
    return False


def validate_image_url(url: str) -> tuple[bool, str]:
    """Validate a user-supplied image URL before fetching it server-side.

    Returns (is_valid, error_message). Blocks non-HTTPS schemes, disallowed
    hosts, and hostnames that resolve to internal/private IP ranges (SSRF).
    """
    if not url or not isinstance(url, str):
        return False, "Image URL is missing or not a string."

    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        return False, "Image URL must use http(s)."

    host = (parsed.hostname or "").lower()
    if not host:
        return False, "Image URL has no host."

    allowed = _allowed_image_hosts()
    if host not in allowed:
        return False, f"Image host '{host}' is not allowed."

    # Defense in depth: even an allowed host must not resolve to a private IP.
    if _resolves_to_private_ip(host):
        return False, "Image host resolves to a disallowed internal address."

    return True, ""


# ── Optional API key auth ───────────────────────────────────────────────────
# If API_KEY env var is set, protected endpoints require the X-API-Key header.
# If it is unset (e.g. local dev), auth is a no-op so nothing breaks.
_API_KEY = os.getenv("API_KEY", "").strip()


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency enforcing an API key when one is configured."""
    if not _API_KEY:
        return  # Auth disabled: no key configured.
    if x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")
