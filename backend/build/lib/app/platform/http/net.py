from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def validate_public_https_url(url: str) -> bool:
    """Return True only for HTTPS URLs resolving entirely to public IPs."""
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM):
            if not _is_public_ip(item[4][0]):
                return False
        return True
    except Exception:
        return False
