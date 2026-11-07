"""Non-rotating Asset Panda access keys use staging's credential loading contract."""
import pytest
from nodes import asset_panda_node as p

KEY = {"credential_type": p.TYPE, "access_key_id": "test-key", "access_key_secret": "test-secret", "account_id": "account_1"}


@pytest.mark.asyncio
async def test_asset_panda_non_rotating_credentials_pass_through_refresh():
    assert await p.AssetPandaNode.freshen_credential(KEY, user_id="caller", credential_id="saved") is KEY


@pytest.mark.parametrize("change", [{"credential_type": "foreign"}, {"access_key_id": "bad key"}, {"account_id": "../other"}])
def test_asset_panda_invalid_credentials_fail_config_validation(change):
    result = p.AssetPandaNode.validate_config({"config": {"operation": "list_accounts"}, "credentials": {**KEY, **change}})
    assert result["valid"] is False
