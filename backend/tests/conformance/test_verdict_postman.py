"""The Postman tier cannot upgrade any OpenAPI or generated-response finding."""
import copy
import json
from pathlib import Path

import pytest

from tests.conformance import verdict as v


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The verdict's tests never reach the network: any real fetch fails the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("verdict tests must not touch the network")
    monkeypatch.setattr(v.httpx, "get", refuse)

@pytest.fixture
def evidence(tmp_path):
    (tmp_path / 'manifest.json').write_text(json.dumps({'test': {'format': 'postman'}}))
    def req(index):
        return {'contract_format': 'postman', 'postman_item': '0/0', 'published_responses': 2,
                'response_example': index, 'response_source': 'postman_example',
                'response_status': 200 + index, 'response_sha256': '0' * 64}
    report = {'provider': 'test', 'operations': [
        {'operation': 'create', 'passed': True, 'requests': [req(i)], 'failures': [], 'fixture_errors': []}
        for i in range(2)]}
    return report, tmp_path


def test_complete_postman_evidence_has_separate_state(evidence):
    report, catalog = evidence
    result = v.verdict(report, catalog, False)
    assert result['state'] == 'postman-checked' and result['ready'] is False
    assert result['operation_states'] == {'create': 'postman-checked'}
    assert not result['blocking']


@pytest.mark.parametrize('mutation', ['missing-example', 'no-examples', 'generated', 'parser', 'request', 'fixture', 'no-request', 'guard', 'wrong-pin'])
def test_incomplete_or_broken_evidence_is_blocking(evidence, mutation):
    report, catalog = evidence
    op = report['operations'][0]
    req = op['requests'][0]
    if mutation == 'missing-example': report['operations'].pop()
    if mutation == 'no-examples': req['published_responses'] = 0
    if mutation == 'generated': req['response_source'] = 'generated'
    if mutation == 'parser': op['failures'] = ['execution: parser failure']
    if mutation == 'request': op['failures'] = ['request: undocumented body field']
    if mutation == 'fixture': op['fixture_errors'] = ['no published example response']
    if mutation == 'no-request': op['requests'] = []
    if mutation == 'guard': op['passed'] = False
    if mutation == 'wrong-pin': req['spec_index'] = 1
    result = v.verdict(report, catalog, False)
    assert result['state'] == 'not-ready' and not result['ready'] and result['blocking']


def test_usual_input_source_audit_still_blocks(evidence, monkeypatch):
    report, catalog = evidence
    (catalog / 'inputs.json').write_text(json.dumps({'create': {'source': 'https://example.test/docs', 'config': {'name': 'published value'}}}))
    monkeypatch.setattr(v, 'page', lambda _: 'Unrelated text')
    result = v.verdict(report, catalog)
    assert result['state'] == 'not-ready'
    assert any('input create:' in b for b in result['blocking'])


@pytest.mark.parametrize('failures', [[], ['execution: parser failure'], ['request: bad query']])
def test_non_postman_output_is_byte_identical(evidence, failures):
    report, catalog = evidence
    (catalog / 'manifest.json').write_text(json.dumps({'test': {'format': 'openapi'}}))
    for op in report['operations']:
        op['requests'][0].pop('contract_format')
        op['requests'][0]['response_source'] = 'generated'
        op['failures'] = failures
    # A catalog without a Postman pin gets exactly the OpenAPI verdict, object and key order alike.
    assert json.dumps(v.verdict(report, catalog, False), indent=1) == json.dumps(v.openapi_verdict(report, catalog, False), indent=1)


def test_mixed_catalog_keeps_openapi_operation_bar(evidence):
    report, catalog = evidence
    (catalog / 'manifest.json').write_text(json.dumps({'test': {'specs': [{'format': 'postman'}, {'format': 'openapi'}]}}))
    op = {'operation': 'openapi_op', 'passed': False,
          'requests': [{'spec_index': 1, 'response_source': 'spec_example', 'response_status': 200}],
          'failures': ['execution: authored parser failure']}
    report['operations'].append(op)
    result = v.verdict(report, catalog, False)
    assert result['state'] == 'not-ready' and not result['ready']
    assert result['operation_states']['create'] == 'postman-checked'
    assert result['operation_states']['openapi_op'] == 'not-ready'
    op['failures'] = []
    op['passed'] = True
    result = v.verdict(report, catalog, False)
    assert result['state'] == 'postman-checked' and result['ready'] is False
    assert result['operation_states']['openapi_op'] == 'ready'


def test_skipping_every_operation_cannot_claim_openapi_ready(evidence):
    report, catalog = evidence
    for op in report["operations"]:
        op["skipped"] = "trigger passthrough"
    result = v.verdict(report, catalog, False)
    assert result["state"] == "not-ready" and result["ready"] is False


@pytest.mark.parametrize('page_text', ['Unrelated docs', 'https://api.example.com.evil.com/v1', 'https://api.example.com/v10'])
def test_host_binding_requires_its_url_on_its_own_page(evidence, monkeypatch, page_text):
    report, catalog = evidence
    binding = {'value': 'https://api.example.com/v1', 'source': 'https://docs.example.com/reference'}
    (catalog / 'manifest.json').write_text(json.dumps({'test': {'format': 'postman', 'host_bindings': {'base': binding}}}))
    report['host_bindings'] = [{'spec_index': 0, 'variable': 'base', **binding}]
    for op in report['operations']:
        op['requests'][0]['host_bindings'] = [{'variable': 'base', **binding}]
    monkeypatch.setattr(v, 'page', lambda _: page_text)
    result = v.verdict(report, catalog)
    assert result['state'] == 'not-ready'
    assert any('source page does not show bound URL' in b for b in result['blocking'])


def test_host_binding_report_cannot_change_its_pin(evidence):
    report, catalog = evidence
    binding = {'value': 'https://api.example.com/v1', 'source': 'https://docs.example.com/reference'}
    (catalog / 'manifest.json').write_text(json.dumps({'test': {'format': 'postman', 'host_bindings': {'base': binding}}}))
    report['host_bindings'] = [{'spec_index': 0, 'variable': 'base', **binding}]
    report['operations'][0]['requests'][0]['host_bindings'] = [
        {'variable': 'base', **binding, 'value': 'https://different.example.com/v1'}]
    result = v.verdict(report, catalog, False)
    assert result['state'] == 'not-ready'
    assert any('not declared by its Postman pin' in b for b in result['blocking'])
    report.pop('host_bindings')
    assert any('differ between report and catalog' in b for b in v.verdict(report, catalog, False)['blocking'])


def test_non_bound_postman_output_is_byte_identical(evidence):
    report, catalog = evidence
    expected = {'provider': 'test', 'ready': False, 'blocking': [], 'advisory': [],
        'stats': {'operations': 2, 'skipped': 0, 'request_ok': 2, 'authored_parser_ok': 2,
                  'generated_only': 0, 'local_ok': 0},
        'state': 'postman-checked', 'operation_states': {'create': 'postman-checked'}}
    assert json.dumps(v.verdict(report, catalog, False), indent=1) == json.dumps(expected, indent=1)


def test_catalog_bindings_never_grant_openapi_ready(evidence):
    report, catalog = evidence
    binding = {'value': 'https://api.example.com/v1', 'source': 'https://docs.example.com/reference'}
    manifest = {'test': {'specs': [{'format': 'postman', 'host_bindings': {'base': binding}}, {'format': 'openapi'}]}}
    (catalog / 'manifest.json').write_text(json.dumps(manifest))
    report['host_bindings'] = [{'spec_index': 0, 'variable': 'base', **binding}]
    for op in report['operations']:
        op['requests'][0].update(contract_format='openapi', spec_index=1, response_source='spec_example')
    result = v.verdict(report, catalog, False)
    assert result['ready'] is False and result['state'] == 'postman-checked'
    (catalog / 'manifest.json').write_text(json.dumps({'test': {'format': 'openapi'}}))
    result = v.verdict(report, catalog, False)
    assert result['ready'] is False and result['state'] == 'not-ready'
