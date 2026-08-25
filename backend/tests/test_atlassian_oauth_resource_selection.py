import pytest
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "nodes" / "oauth" / "atlassian_oauth.py"
spec = importlib.util.spec_from_file_location("atlassian_oauth", MODULE_PATH)
atlassian_oauth = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(atlassian_oauth)
_select_jira_resource = atlassian_oauth._select_jira_resource
AtlassianSiteAccessError = atlassian_oauth.AtlassianSiteAccessError


RESOURCES = [
    {
        "id": "cloud-1",
        "name": "Engineering",
        "url": "https://engineering.atlassian.net",
        "scopes": ["read:jira-work"],
    },
    {
        "id": "cloud-2",
        "name": "Support",
        "url": "https://support.atlassian.net",
        "scopes": ["read:jira-work"],
    },
]


def test_select_jira_resource_matches_requested_subdomain():
    resource = _select_jira_resource(RESOURCES, "support")

    assert resource["id"] == "cloud-2"


def test_select_jira_resource_matches_requested_url():
    resource = _select_jira_resource(RESOURCES, "https://engineering.atlassian.net/browse/ABC")

    assert resource["id"] == "cloud-1"


def test_select_jira_resource_fails_when_requested_site_is_not_accessible():
    with pytest.raises(AtlassianSiteAccessError, match="does not have access to missing") as exc_info:
        _select_jira_resource(RESOURCES, "missing")

    assert exc_info.value.requested_site == "missing"
    assert exc_info.value.available_sites == RESOURCES
