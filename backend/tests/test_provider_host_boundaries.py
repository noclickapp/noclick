"""Exact provider-host boundaries for credential-bearing integrations."""

import pytest

from nodes.confluence_node import ConfluenceApiTokenCredential, _wiki_base
from nodes.databricks_node import _normalize_host as _databricks_host
from nodes.freshsales_node import _build_base_url
from nodes.hex_node import _base_url
from nodes.jira_node import JiraAPITokenCredential, JiraNode, _jira_api_base_from_dict
from nodes.pinecone_node import _pinecone_data_host
from utils.ssrf import SSRFError


@pytest.mark.parametrize(
    "domain",
    [
        "tenant.atlassian.net@attacker.example",
        "tenant.atlassian.net.attacker.example",
        "attacker.example",
        "127.0.0.1#",
        "https://tenant.atlassian.net:8443",
    ],
)
def test_jira_api_token_domain_cannot_escape_atlassian(domain):
    credential = {
        "credential_type": "jira_api_token",
        "domain": domain,
        "email": "user@example.com",
        "api_token": "secret",
    }
    with pytest.raises(SSRFError):
        _jira_api_base_from_dict(credential)

    model = JiraAPITokenCredential(
        domain=domain,
        email="user@example.com",
        api_token="secret",
    )
    with pytest.raises(SSRFError):
        JiraNode._get_api_base(None, model)


def test_jira_api_token_domain_is_canonicalized():
    assert _jira_api_base_from_dict(
        {"credential_type": "jira_api_token", "domain": "https://Acme.atlassian.net/"}
    ) == "https://acme.atlassian.net/rest/api/3"


@pytest.mark.parametrize(
    "domain",
    [
        "tenant.atlassian.net@attacker.example",
        "tenant.atlassian.net.attacker.example",
        "attacker.example",
        "127.0.0.1#",
        "https://tenant.atlassian.net:8443",
    ],
)
def test_confluence_api_token_domain_cannot_escape_atlassian(domain):
    credential = ConfluenceApiTokenCredential(
        domain=domain,
        email="user@example.com",
        api_token="secret",
    )
    with pytest.raises(SSRFError):
        _wiki_base(credential)


def test_confluence_api_token_domain_is_canonicalized():
    credential = ConfluenceApiTokenCredential(
        domain="https://Acme.atlassian.net/wiki/",
        email="user@example.com",
        api_token="secret",
    )
    assert _wiki_base(credential) == "https://acme.atlassian.net/wiki"


@pytest.mark.parametrize(
    "host",
    [
        "app.hex.tech@attacker.example",
        "app.hex.tech.attacker.example",
        "attacker.example",
        "127.0.0.1#",
        "https://app.hex.tech:8443",
    ],
)
def test_hex_workspace_host_cannot_escape_provider(host):
    with pytest.raises(SSRFError):
        _base_url(host)


def test_hex_workspace_host_is_canonicalized():
    assert _base_url("https://EU.hex.tech/") == "https://eu.hex.tech/api/v1"


@pytest.mark.parametrize(
    "domain",
    [
        "acme.myfreshworks.com@attacker.example",
        "acme.myfreshworks.com.attacker.example",
        "attacker.example",
        "127.0.0.1#",
        "https://acme.myfreshworks.com:8443",
    ],
)
def test_freshsales_domain_cannot_escape_provider(domain):
    with pytest.raises(SSRFError):
        _build_base_url(domain)


def test_freshsales_domain_is_canonicalized():
    assert _build_base_url("https://Acme.myfreshworks.com/crm/sales/") == (
        "https://acme.myfreshworks.com/crm/sales"
    )


@pytest.mark.parametrize(
    "host",
    [
        "good.pinecone.io@attacker.example",
        "good.pinecone.io.attacker.example",
        "attacker.example",
        "127.0.0.1#",
        "https://good.pinecone.io",
        "good.pinecone.io:8443",
        "good.pinecone.io/path",
    ],
)
def test_pinecone_data_host_cannot_escape_provider(host):
    with pytest.raises(SSRFError):
        _pinecone_data_host(host)


@pytest.mark.parametrize(
    "host",
    ["docs-abc.svc.pinecone.io", "index.us-east-1.aws.pinecone.io"],
)
def test_pinecone_data_host_accepts_nested_provider_hosts(host):
    assert _pinecone_data_host(host) == host


@pytest.mark.parametrize(
    "host",
    [
        "workspace.cloud.databricks.com@attacker.example",
        "https://user@workspace.cloud.databricks.com",
        "http://workspace.cloud.databricks.com",
        "https://workspace.cloud.databricks.com:8443",
        "https://workspace.cloud.databricks.com/api/2.0",
        "https://workspace.cloud.databricks.com?redirect=attacker",
        "https://workspace.cloud.databricks.com#attacker",
    ],
)
def test_databricks_workspace_url_is_one_https_origin(host):
    with pytest.raises(SSRFError):
        _databricks_host(host)


def test_databricks_workspace_host_is_canonicalized():
    assert _databricks_host("WORKSPACE.cloud.databricks.com/") == (
        "https://workspace.cloud.databricks.com"
    )
