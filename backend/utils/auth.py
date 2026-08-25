import asyncio
import logging
import os
import json
import base64
import time
from functools import lru_cache
from typing import Optional, Dict, Any
from http.cookies import SimpleCookie
import jwt
from jwt import PyJWKClient
from fastapi.security import HTTPBearer

security = HTTPBearer()
logger = logging.getLogger(__name__)

# Cache the JWK client to avoid repeated fetches
_jwk_client_cache = {}


def _format_relative_age(seconds: int) -> str:
    """Return a compact string like "1d, 2h, 10s ago" or "in 30s"."""
    sign = "ago" if seconds >= 0 else "in"
    remaining = abs(int(seconds))
    parts = []
    for label, unit in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if remaining < unit:
            continue
        value, remaining = divmod(remaining, unit)
        if value:
            parts.append(f"{value}{label}")
        if len(parts) == 3:
            break
    if not parts:
        parts.append("0s")
    if sign == "ago":
        return f"{', '.join(parts)} ago"
    return f"{sign} {', '.join(parts)}"


async def verify_token(token: str) -> Dict[str, Any]:
    """Verify JWT token using configured verification method
    
    Security: Uses ONLY the configured method (asymmetric OR symmetric), 
    never falls back between them to prevent downgrade attacks.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded and verified JWT payload
        
    Raises:
        jwt.InvalidTokenError: If token verification fails
    """
    try:
        logger.debug("Starting token verification")
        
        # Determine verification method based on configuration
        # Priority: JWK URL > Public Key/JWK > JWT Secret
        # NO FALLBACK between methods to prevent downgrade attacks
        
        # Check for asymmetric verification (JWK URL or public key)
        public_key = get_supabase_public_key()
        jwt_secret = get_supabase_jwt_secret()
        
        if public_key:
            # Use ONLY asymmetric verification
            if public_key.startswith('http'):
                # JWK URL - PyJWKClient handles algorithm detection securely
                logger.debug("Using JWK URL for verification")
                
                # Use cached client or create new one
                if public_key not in _jwk_client_cache:
                    logger.debug(f"Creating new JWK client")
                    _jwk_client_cache[public_key] = PyJWKClient(
                        public_key,
                        cache_keys=True,
                        max_cached_keys=16,
                        cache_jwk_set=True,
                        lifespan=300  # 5 minutes
                    )
                
                jwks_client = _jwk_client_cache[public_key]
                # PyJWKClient.get_signing_key_from_jwt does a blocking urllib GET
                # of the JWKS endpoint on cache miss (5-min lifespan), which stalls
                # the event loop through the TLS handshake on the auth hot path.
                # Off-load it; the client's internal caches are thread-safe.
                signing_key = await asyncio.to_thread(
                    jwks_client.get_signing_key_from_jwt, token
                )
                
                # PyJWKClient extracts algorithm from the key, not the JWT header
                # This prevents algorithm confusion attacks
                payload = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["ES256", "RS256", "EdDSA"],  # Only asymmetric algorithms
                    options={"verify_exp": True, "verify_aud": False}
                )
                logger.debug("Token verified with JWK")
                return payload
                
            elif public_key.startswith('{'):
                # JWK JSON for ES256 - explicitly use ES256
                logger.debug("Using JWK JSON for ES256 verification")
                jwk_dict = json.loads(public_key)
                pem_key = convert_jwk_to_pem(jwk_dict)
                
                # Force ES256 - don't trust JWT header
                payload = jwt.decode(
                    token,
                    pem_key,
                    algorithms=["ES256"],  # ONLY ES256, no algorithm confusion
                    options={"verify_exp": True, "verify_aud": False}
                )
                logger.debug("Token verified with ES256")
                return payload
                
            else:
                # PEM public key - determine algorithm from key type
                # For Supabase, this is typically RS256 or ES256
                logger.debug("Using PEM public key for verification")
                
                # Try RS256 first (most common for PEM keys)
                try:
                    payload = jwt.decode(
                        token,
                        public_key,
                        algorithms=["RS256"],  # Try RS256 only
                        options={"verify_exp": True, "verify_aud": False}
                    )
                    logger.debug("Token verified with RS256")
                    return payload
                except jwt.InvalidTokenError:
                    # If RS256 fails, try ES256
                    payload = jwt.decode(
                        token,
                        public_key,
                        algorithms=["ES256"],  # Try ES256 only
                        options={"verify_exp": True, "verify_aud": False}
                    )
                    logger.debug("Token verified with ES256")
                    return payload
                    
        elif jwt_secret:
            # Use ONLY symmetric verification - no fallback from asymmetric
            logger.debug("Using symmetric key for HS256 verification")
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],  # ONLY HS256, no algorithm confusion
                options={"verify_exp": True, "verify_aud": False}
            )
            logger.debug("Token verified with HS256")
            return payload
            
        else:
            # No keys configured - fail securely
            logger.error("No JWT verification keys configured")
            raise jwt.InvalidTokenError("No JWT verification keys configured")

    except jwt.InvalidTokenError as e:
        logger.error(f"Token verification failed")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during token verification")
        raise jwt.InvalidTokenError(f"Token verification error")

@lru_cache()
def get_supabase_jwt_secret() -> Optional[str]:
    """Get the JWT secret key from environment variables (for backward compatibility)"""
    return os.getenv('SUPABASE_JWT_SECRET')

@lru_cache()
def get_supabase_public_key() -> Optional[str]:
    """Get the public key or JWK URL for asymmetric verification
    
    Returns:
        Either a PEM-formatted public key, JWK URL, JWK JSON, or None if not configured
    """
    # Check for JWK URL first (preferred for Supabase)
    jwk_url = os.getenv('SUPABASE_JWK_URL')
    if jwk_url:
        return jwk_url
    
    # Check for JWK JSON (for ES256)
    jwk_json = os.getenv('SUPABASE_PUBLIC_JWK')
    if jwk_json:
        return jwk_json  # Return as string, will be parsed in verify_token
    
    # Check for direct public key (PEM format)
    public_key = os.getenv('SUPABASE_PUBLIC_KEY')
    if public_key:
        # Handle multiline PEM format from environment variable
        # Replace literal \n with actual newlines
        public_key = public_key.replace('\\n', '\n')
        return public_key
    
    return None

def convert_jwk_to_pem(jwk_dict: dict) -> str:
    """Convert an ES256 JWK to PEM format
    
    Args:
        jwk_dict: JWK dictionary with x, y coordinates for EC key
        
    Returns:
        PEM formatted public key string
    """
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    
    # Decode the x and y coordinates (add padding if needed)
    x_b64 = jwk_dict['x']
    y_b64 = jwk_dict['y']
    
    # Add padding if necessary
    x_b64 += '=' * (4 - len(x_b64) % 4) if len(x_b64) % 4 else ''
    y_b64 += '=' * (4 - len(y_b64) % 4) if len(y_b64) % 4 else ''
    
    x_bytes = base64.urlsafe_b64decode(x_b64)
    y_bytes = base64.urlsafe_b64decode(y_b64)
    
    # Convert to integers
    x_int = int.from_bytes(x_bytes, 'big')
    y_int = int.from_bytes(y_bytes, 'big')
    
    # Create EC public key using P-256 curve (SECP256R1)
    public_numbers = ec.EllipticCurvePublicNumbers(
        x_int, y_int, ec.SECP256R1()
    )
    public_key_obj = public_numbers.public_key(default_backend())
    
    # Convert to PEM format
    pem = public_key_obj.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )
    
    return pem.decode('utf-8')

async def verify_socket_token(token: str) -> tuple[str, Dict[str, Any]]:
    """Verify a Supabase access token for socket auth; return (user_id, claims).

    Identity is the VERIFIED JWT's ``sub`` — never a client-supplied field
    (the retired cookie path took user_id from the unverified cookie blob).
    Raises jwt.ExpiredSignatureError (reject code ``token_expired`` — the
    client refreshes and reconnects) or jwt.InvalidTokenError
    (``token_invalid`` — definitive, client redirects to login).
    """
    if not token or not isinstance(token, str):
        raise jwt.InvalidTokenError("Missing token")
    claims = await verify_token(token)
    user_id = claims.get('sub')
    if not user_id:
        raise jwt.InvalidTokenError("Token has no sub claim")
    return str(user_id), claims


async def extract_token_from_cookies(cookie_str: str) -> tuple[str, str]:
    """
    Extract access token and user ID from cookie string
    
    Security: Validates cookie format and safely parses without exposing details
    
    Args:
        cookie_str: Raw cookie string from auth payload
    Returns:
        tuple[str, str]: (access_token, user_id)
    """
    try:
        logger.debug("Extracting token from cookie string")
        
        # Validate input
        if not cookie_str or not isinstance(cookie_str, str):
            raise ValueError("Invalid cookie string")

        # Limit cookie string length to prevent DoS
        if len(cookie_str) > 50000:  # ~50KB max
            raise ValueError("Cookie string too large")

        now_ts = int(time.time())
        failure_reasons: list[str] = []

        # Parse cookies with validation (prefer SimpleCookie, fall back to manual parsing)
        cookies: Dict[str, str] = {}

        try:
            simple_cookie = SimpleCookie()
            simple_cookie.load(cookie_str)
            for key, morsel in simple_cookie.items():
                if key and len(key) <= 100:
                    cookies[key] = morsel.value
        except Exception as e:
            logger.debug(f"SimpleCookie parse failed: {str(e)}")

        if not cookies:
            for cookie_pair in cookie_str.split(';'):
                cookie_pair = cookie_pair.strip()
                if not cookie_pair or '=' not in cookie_pair:
                    continue

                key, value = cookie_pair.split('=', 1)

                if not key or not all(c.isalnum() or c in '-._' for c in key):
                    continue

                if len(key) <= 100:
                    cookies[key] = value

        # Find all Supabase auth token cookies
        auth_cookie_bases = []

        # Look for all auth token patterns (sb-xxxxx-auth-token or sb-xxxxx-auth-token.N)
        for key in cookies:
            # Validate Supabase cookie pattern
            if not key.startswith('sb-'):
                continue
                
            # Check for multipart cookie (sb-xxx-auth-token.0)
            if '-auth-token.' in key:
                parts = key.rsplit('-auth-token.', 1)
                if len(parts) == 2 and parts[1].isdigit():
                    base_key = f'{parts[0]}-auth-token'
                    if base_key not in auth_cookie_bases:
                        auth_cookie_bases.append(base_key)
            # Check for single-part cookie (sb-xxx-auth-token)
            elif key.endswith('-auth-token'):
                if key not in auth_cookie_bases:
                    auth_cookie_bases.append(key)

        if not auth_cookie_bases:
            logger.debug("No Supabase auth cookies found in request")
            raise ValueError("Authentication cookie not found")

        logger.debug(f"Found {len(auth_cookie_bases)} auth cookie(s): {auth_cookie_bases}")

        # Try each auth cookie until we find a valid one
        last_error = None
        for base_key in auth_cookie_bases:
            try:
                # Collect auth token parts for this cookie
                part_keys = [
                    key for key in cookies.keys()
                    if key.startswith(f'{base_key}.') and key[len(base_key) + 1:].isdigit()
                ]

                auth_parts = []
                if part_keys:
                    part_keys.sort(key=lambda k: int(k[len(base_key) + 1:]))
                    auth_parts = [cookies[k] for k in part_keys]
                elif base_key in cookies:
                    auth_parts = [cookies[base_key]]

                if not auth_parts:
                    logger.debug(f"No auth token parts found for {base_key}")
                    continue

                # Combine parts and handle base64 encoding
                auth_data = ''.join(auth_parts)

                # Remove base64 prefix if present
                if auth_data.startswith('base64-'):
                    auth_data = auth_data[7:]

                # Add padding if necessary for base64
                padding_needed = (4 - len(auth_data) % 4) % 4
                auth_data += '=' * padding_needed

                # Decode and parse JSON
                try:
                    decoded_bytes = base64.urlsafe_b64decode(auth_data)
                    # Limit decoded size to prevent JSON bombs
                    if len(decoded_bytes) > 10000:  # 10KB max for auth data
                        logger.debug(f"Auth data too large for {base_key}")
                        continue

                    cookie_data = json.loads(decoded_bytes)
                except (base64.binascii.Error, json.JSONDecodeError) as e:
                    logger.debug(f"Failed to decode auth data for {base_key}: {str(e)}")
                    continue

                # Extract required fields with validation
                if not isinstance(cookie_data, dict):
                    logger.debug(f"Invalid auth data structure for {base_key}")
                    continue

                token = cookie_data.get('access_token')
                user_data = cookie_data.get('user', {})

                if not isinstance(user_data, dict):
                    logger.debug(f"Invalid user data structure for {base_key}")
                    continue

                user_id = user_data.get('id')

                expires_at_raw = cookie_data.get('expires_at')
                expires_at_ts = None
                if isinstance(expires_at_raw, (int, float)):
                    expires_at_ts = int(expires_at_raw)
                elif isinstance(expires_at_raw, str):
                    if expires_at_raw.isdigit():
                        expires_at_ts = int(expires_at_raw)
                    else:
                        try:
                            expires_at_ts = int(float(expires_at_raw))
                        except ValueError:
                            expires_at_ts = None
                if expires_at_ts is None:
                    expires_in_raw = cookie_data.get('expires_in')
                    if isinstance(expires_in_raw, (int, float)):
                        expires_at_ts = int(time.time()) + int(expires_in_raw)

                # Validate extracted data
                if not token or not isinstance(token, str):
                    logger.debug(f"Invalid access token for {base_key}")
                    continue

                if not user_id or not isinstance(user_id, str):
                    logger.debug(f"Invalid user ID for {base_key}")
                    continue

                # Basic JWT format validation (header.payload.signature)
                if token.count('.') != 2:
                    logger.debug(f"Invalid token format for {base_key}")
                    continue

                is_expired = (
                    expires_at_ts is not None and expires_at_ts <= now_ts
                )
                if is_expired:
                    age = _format_relative_age(now_ts - (expires_at_ts or now_ts))
                    reason = (
                        f"Token for {base_key} is expired"
                        f" ({age}; expires_at={expires_at_ts}, now={now_ts})"
                    )
                    logger.debug(reason)
                    failure_reasons.append(reason)
                    continue

                # Try to verify this token
                try:
                    await verify_token(token)
                    # Token is valid and not expired!
                    logger.debug(f"Successfully verified token from {base_key}")
                    return token, user_id
                except jwt.InvalidTokenError as verify_error:
                    reason = (
                        f"Token from {base_key} failed verification: {str(verify_error)}"
                    )
                    logger.debug(reason)
                    failure_reasons.append(reason)
                    continue

            except Exception as e:
                reason = f"Error processing cookie {base_key}: {str(e)}"
                logger.debug(reason)
                failure_reasons.append(reason)
                last_error = e
                continue

        # None of the cookies worked
        if last_error:
            logger.debug(f"All auth cookies failed. Last error: {str(last_error)}")
        error_message = "No valid authentication cookie found"
        if failure_reasons:
            logger.debug("Summary of auth cookie failures: %s", failure_reasons)
            summary = "; ".join(failure_reasons[:3])
            if len(failure_reasons) > 3:
                summary += "; ..."
            error_message = f"{error_message} (reasons: {summary})"
        raise ValueError(error_message)
        
    except ValueError as e:
        # Re-raise ValueError with generic message (don't expose details)
        logger.debug(f"Cookie extraction failed: {str(e)}")
        message = str(e) or "Authentication failed"
        raise ValueError(f"Authentication failed: {message}")
    except Exception as e:
        # Log unexpected errors but don't expose details
        logger.error(f"Unexpected error in cookie extraction")
        raise ValueError("Authentication failed")
