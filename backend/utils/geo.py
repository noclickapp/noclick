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
