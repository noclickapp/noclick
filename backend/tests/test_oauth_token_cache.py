from utils.oauth_token_cache import OAuthTokenCache, oauth_authority_digest


def test_authority_digest_is_canonical_and_contains_no_raw_secret():
    first = oauth_authority_digest(
        provider="test", client_id="client", client_secret="raw-secret"
    )
    reordered = oauth_authority_digest(
        client_secret="raw-secret", client_id="client", provider="test"
    )
    changed = oauth_authority_digest(
        provider="test", client_id="client", client_secret="other-secret"
    )

    assert first == reordered
    assert first != changed
    assert len(first) == 64
    assert "raw-secret" not in first


def test_missing_provider_expiry_uses_a_conservative_bounded_ttl():
    cache = OAuthTokenCache(
        refresh_skew_seconds=60,
        missing_expiry_ttl_seconds=300,
    )
    cache.put("digest", "token", expires_in=None, now=1000.0)

    assert cache.get("digest", now=1239.9) == "token"
    assert cache.get("digest", now=1240.0) is None


def test_invalid_or_already_expired_provider_ttl_is_not_cached():
    for expires_in in (0, -1, True, "invalid", float("inf")):
        cache = OAuthTokenCache()
        cache.put("digest", "token", expires_in=expires_in, now=1000.0)
        assert cache.get("digest", now=1000.0) is None
