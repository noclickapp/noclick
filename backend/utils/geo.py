"""Optional Geo-IP lookup for operator-configured login notifications."""

import logging
import os
import ipaddress
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Cache to avoid repeated lookups for the same IP
_ip_cache: dict[str, Optional[str]] = {}


async def get_country_from_ip(ip: str) -> Optional[str]:
    """
    Get a country name from an operator-configured HTTPS Geo-IP endpoint.

    Args:
        ip: IP address to lookup

    Returns:
        Country name (e.g., "United States") or None if lookup fails.
    """
    if not ip or ip in ('127.0.0.1', 'localhost', '::1'):
        return None
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return None

    # IP addresses are personal data.  Never send one to an implicit vendor:
    # an operator who wants geo on their Slack login notifications must opt in
    # with an HTTPS endpoint such as ``https://geo.example.com/json/{ip}``.
    endpoint_template = (os.getenv("GEOIP_LOOKUP_URL") or "").strip()
    if not endpoint_template:
        return None
    if not endpoint_template.startswith("https://"):
        logger.warning("GEOIP_LOOKUP_URL must use HTTPS; geo lookup disabled")
        return None
    endpoint = endpoint_template.replace("{ip}", ip)

    # Check cache first
    if ip in _ip_cache:
        return _ip_cache[ip]

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                endpoint,
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

    Checks various headers used by different proxies/load balancers,
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

    # Check CF-Connecting-IP (Cloudflare)
    cf_ip = environ.get('HTTP_CF_CONNECTING_IP')
    if cf_ip:
        return cf_ip.strip()

    # Check True-Client-IP (Akamai, Cloudflare Enterprise)
    true_client = environ.get('HTTP_TRUE_CLIENT_IP')
    if true_client:
        return true_client.strip()

    # Fall back to REMOTE_ADDR
    return environ.get('REMOTE_ADDR')
