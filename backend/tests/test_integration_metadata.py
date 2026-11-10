"""Generated integration facts come from backend credential and operation schemas.

Exercise title aliases, credential-free nodes, and declaration errors directly.
"""
import pytest

from scripts.generate_socket_types import integration_metadata


def test_credential_metadata_comes_from_schema():
    schema = {'properties': {'credentials': {'$ref': '#/$defs/ExampleCredential'}}, '$defs': {
        'ExampleCredential': {'title': 'Example API Key', 'properties': {
            'credential_type': {'const': 'example_api_key', 'default': 'example_api_key'},
        }},
    }}
    meta = integration_metadata('automation-example', schema, {'agentToolProvider': True})
    assert meta['credentialTypes'] == {'ExampleCredential': 'example_api_key', 'Example API Key': 'example_api_key'}
    assert meta['providerLabels'] == {'example': 'Example API Key'}
    assert meta['autoSelectCredential'] is True
    assert meta['nodeMeta'] == {'agentToolProvider': True}


def test_no_credentials_means_no_auto_select():
    meta = integration_metadata('automation-example', {}, {})
    assert meta['credentialTypes'] == meta['providerLabels'] == {}
    assert meta['autoSelectCredential'] is False


def test_a_node_can_decline_auto_select():
    schema = {'properties': {'credentials': {'$ref': '#/$defs/ExampleCredential'}}, '$defs': {
        'ExampleCredential': {'properties': {'credential_type': {'const': 'example_api_key'}}},
    }}
    meta = integration_metadata('automation-example', schema, {}, auto_select=False)
    assert meta['credentialTypes'] == {'ExampleCredential': 'example_api_key'}
    assert meta['autoSelectCredential'] is False


def test_ambiguous_credential_type_is_an_error():
    with pytest.raises(ValueError, match='single credential_type'):
        integration_metadata('automation-example', {'$defs': {'Bad': {'properties': {'credential_type': {}}}}}, {})


def test_multiple_methods_use_explicit_provider_display_name():
    schema = {'$defs': {
        'OAuth': {'title': 'Example OAuth', 'x-oauth-provider': 'example', 'properties': {'credential_type': {'const': 'example_oauth'}}},
        'PAT': {'title': 'Example Personal Token', 'properties': {'credential_type': {'const': 'example_pat'}}},
    }}
    with pytest.raises(ValueError, match='credential_provider_labels'):
        integration_metadata('automation-example', schema, {})
    assert integration_metadata('automation-example', schema, {}, {'example': 'Example Account'})['providerLabels'] == {'example': 'Example Account'}


@pytest.mark.parametrize('oauth_provider, expected_key', [('google', 'example'), ('microsoft', 'microsoft')])
def test_provider_key_matches_frontend_grouping(oauth_provider, expected_key):
    schema = {'$defs': {'ExampleOAuth': {'title': 'Example Account', 'x-oauth-provider': oauth_provider,
              'properties': {'credential_type': {'const': 'example_oauth'}}}}}
    assert integration_metadata('automation-example', schema, {})['providerLabels'] == {expected_key: 'Example Account'}
