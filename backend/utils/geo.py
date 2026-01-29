"""
Geo-IP utility for looking up country from IP address.
Uses the free ip-api.com service (no API key required, 45 requests/minute limit).
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Cache to avoid repeated lookups for the same IP
_ip_cache: dict[str, Optional[str]] = {}


async def get_country_from_ip(ip: str) -> Optional[str]:
    """
    Get country name from IP address using ip-api.com.

    Args:
        ip: IP address to lookup

    Returns:
        Country name (e.g., "United States") or None if lookup fails.
    """
    if not ip or ip in ('127.0.0.1', 'localhost', '::1'):
        return None

    # Check cache first
    if ip in _ip_cache:
        return _ip_cache[ip]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,country,countryCode"},
                timeout=5.0
            )

            data = response.json()
            if data.get("status") == "success":
                country = data.get("country")
                _ip_cache[ip] = country
                return country

            logger.debug(f"IP lookup failed for {ip}: {data.get('message', 'unknown error')}")
            _ip_cache[ip] = None
            return None

    except Exception as e:
        logger.debug(f"IP lookup error for {ip}: {e}")
        _ip_cache[ip] = None
        return None


def extract_client_ip(environ: dict) -> Optional[str]:
    """
    Extract client IP from WSGI/ASGI environ.

    Checks X-Forwarded-For header first (for proxied requests),
    then falls back to REMOTE_ADDR.

    Args:
        environ: WSGI/ASGI environment dict

    Returns:
        Client IP address or None if not found.
    """
    # Check X-Forwarded-For header (may contain multiple IPs)
    forwarded_for = environ.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        # Take the first IP (original client)
        return forwarded_for.split(',')[0].strip()

    # Check X-Real-IP header
    real_ip = environ.get('HTTP_X_REAL_IP')
    if real_ip:
        return real_ip.strip()

    # Fall back to REMOTE_ADDR
    return environ.get('REMOTE_ADDR')
