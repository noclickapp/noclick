"""Voiceflow PAT validation on staging's standard credential-loading path.

Malformed credentials must be rejected without exposing their secret values.
"""
import pytest
from nodes.voiceflow_node import credential_shape

@pytest.mark.parametrize("change", [{"personal_access_token": "not-a-pat"}, {"workspace_id": "bad/path"}, {"environment_alias": "https://example.com"}])
def test_invalid_credential_is_sanitized(change):
    data = {"personal_access_token": "vfp_SYNTHETIC_VOICEFLOW_TOKEN", "workspace_id": "workspace-one", "project_id": "project-one", "environment_alias": "main", **change}
    with pytest.raises(ValueError, match="current Voiceflow personal token credential is invalid"):
        credential_shape(data)
