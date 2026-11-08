"""Mutation controls for the merge verdict; no real network or catalog edits."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.conformance import verdict as v

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The verdict's tests never reach the network: any real fetch fails the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("verdict tests must not touch the network")
    monkeypatch.setattr(v.httpx, "get", refuse)


@pytest.fixture
def case(tmp_path, monkeypatch):
    pages = {}
    calls = []

    def fetch(url):
        calls.append(url)
        return pages[url]

    monkeypatch.setattr(v, 'page', fetch)
    # An OpenAPI catalog: the verdict reads the manifest to tell it from a Postman one.
    (tmp_path / 'manifest.json').write_text(json.dumps({'test': {}}))
    report = {'provider': 'test', 'operations': []}

    def run(config=None, text='', *, body=None, source='https://docs.test/chosen', op=None, extra=None):
        pages[source] = text
        entry = {'source': source, **(extra or {})}
        if body is None:
            entry['config'] = config or {}
            name = 'inputs.json'
        else:
            entry['body'] = body
            name = 'witnesses.json'
        (tmp_path / name).write_text(json.dumps({'example': entry}))
        report['operations'] = [] if op is None else [op]
        return v.verdict(report, tmp_path)

    run.pages, run.calls, run.report, run.path = pages, calls, report, tmp_path
    return run


@pytest.mark.parametrize('field', ['body_json', 'query_json', 'form_json', 'json_editor'])
def test_serialized_documents_use_values_not_document_or_keys(case, field):
    config = {field: json.dumps({'absent_node_key': {'0': 'P10DISC'}})}
    assert case(config, 'coupon_ids[0]=P10DISC')['ready']
    assert not case(config, 'coupon_ids[0]=OTHER')['ready']


def test_nested_serialized_arrays_objects_and_long_document():
    doc = {'config': json.dumps({'nested': json.dumps([{'key': 'documented'}, 'second', 'third', 'fourth'])}),
           'long': 'x' * 100}
    assert v.leaves(doc, set(), keys=False) == {'documented', 'second', 'third'}
    assert 'key' in v.leaves(doc, set(), keys=True)


@pytest.mark.parametrize('value', ['plain text', '123', 'true', 'null', '"quoted"', '{invalid'])
def test_non_document_strings_unchanged(value):
    assert v.leaves(value, set(), keys=False) == {value}


def test_leaf_window_and_three_array_items_unchanged():
    assert v.leaves(['ab', 'abc', 'x' * 60, 'fourth'], set(), False) == {'abc', 'x' * 60}
    assert v.leaves(['x' * 61], set(), False) == set()
    assert v.leaves({'number': 123, 'bool': True, 'null': None}, set(), False) == set()


def test_source_is_only_the_url_given(case):
    case.pages['https://docs.test/different'] = 'secret-value'
    result = case({'body_json': '{"field":"secret-value"}'}, 'unrelated')
    assert not result['ready']
    assert case.calls == ['https://docs.test/chosen']


@pytest.mark.parametrize('text,value', [
    ('<pre><span>docu</span><span>mented</span></pre>', 'documented'),
    ('<pre>&quot;hello&quot; &amp; goodbye</pre>', '"hello" & goodbye'),
    ('<pre>one\n  two&#32;three</pre>', 'one two three'),
    ('<pre>&lt;html&gt;&lt;body&gt;hi&lt;/body&gt;&lt;/html&gt;</pre>', '<html><body>hi</body></html>'),
    ('plain documented text', 'documented'),
    ('# Documentation\n```html\n<img src="secret-value">\n```', 'secret-value'),
    ('{"description": "<div>example</div>", "id": "documented"}', 'documented'),
    ('openapi: 3.0.0\ndescription: <div>example</div>\nid: documented', 'documented'),
])
def test_rendered_page_positives(case, text, value):
    assert case({'value': value}, text)['ready']


@pytest.mark.parametrize('text', [
    '<div data-value="secret-value">unrelated</div>',
    '<script>"secret-value"</script><div>unrelated</div>',
    '<script type="application/json">{"v":"secret-value"}</script>',
    '<style>.x {content: "secret-value"}</style>',
    '<!-- secret-value --><p>unrelated</p>',
    '<template>secret-value</template>',
])
def test_legacy_raw_html_evidence_still_counts(case, text):
    assert v.page_forms(text)[0] == text
    assert case({'value': 'secret-value'}, text)['ready']


@pytest.mark.parametrize('value', ['Hi {{first_name:"there"}}', 'path\\file', 'café', 'line\nbreak'])
@pytest.mark.parametrize('render', [False, True])
def test_json_escaped_value_matches_fetched_or_rendered_text(case, value, render):
    escaped = json.dumps(value)[1:-1]
    assert value not in escaped
    text = escaped
    if render:
        from html import escape
        text = '<pre>' + ''.join('<span>' + escape(char) + '</span>' for char in escaped) + '</pre>'
        assert escaped not in text
    assert case({'value': value}, text)['ready']


def test_no_invented_match_across_block_boundaries(case):
    assert not case({'value': 'secret-value'}, '<div>secret-</div><div>value</div>')['ready']


def test_json_escaping_does_not_invent_missing_evidence(case):
    assert not case({'value': 'missing "quoted" value'}, 'different \\"quoted\\" value')['ready']


def test_evidence_union_reaches_threshold_across_forms(case):
    quoted = 'quoted "value"'
    config = dict(zip('abcde', ['plain-token', 'documented', quoted, 'missing-one', 'missing-two']))
    text = '<p>plain-token</p><pre>docu<span>mented</span></pre><script>' + json.dumps(quoted)[1:-1] + '</script>'
    assert v.matched(set(config.values()), text) == {'plain-token', 'documented', quoted}
    assert case(config, text)['ready']
    assert not case(config, '<p>plain-token</p><pre>docu<span>mented</span></pre>')['ready']


def test_response_keys_are_still_required(case):
    result = case(text='<pre>documented</pre>', body={'missing_one': 'documented', 'missing_two': 'documented'})
    assert not result['ready']
    assert '1/3' in result['blocking'][0]


def test_long_json_document_with_missing_values_blocks(case):
    document = json.dumps({'long_editor_field': 'missing-first', 'another_editor_field': 'missing-second'})
    assert len(document) > 60
    assert not case({'body_json': document}, 'unrelated page')['ready']


def test_serialized_response_still_requires_inner_keys(case):
    body = {'outer': '{"missing_one":"documented","missing_two":"documented"}'}
    assert not case(text='outer documented', body=body)['ready']
    assert case(text='outer missing_one missing_two documented', body=body)['ready']


def test_exact_threshold_unchanged(case):
    config = dict(zip('abcde', ['first', 'second', 'third', 'fourth', 'fifth']))
    assert case(config, 'first second third')['ready']
    assert not case(config, 'first second')['ready']


@pytest.mark.parametrize('source', ['', 'file:///tmp/example'])
def test_source_required(case, source):
    assert 'no source URL' in case({'field': 'documented'}, 'documented', source=source)['blocking'][0]


def test_unreadable_source_blocks(case, monkeypatch):
    def fail(url):
        raise RuntimeError('fetch failed')
    monkeypatch.setattr(v, 'page', fail)
    assert 'source unreadable (RuntimeError)' in case({'field': 'documented'})['blocking'][0]


def operation(**changes):
    return {'operation': 'local', 'requests': [], 'failures': [], 'fixture_errors': [], **changes}


def test_node_local_attestation_success(case):
    result = case(op=operation(node_local_ok=True))
    assert result['ready']
    assert result['stats']['local_ok'] == 1
    assert result['stats']['request_ok'] == 0
    assert result['stats']['generated_only'] == result['stats']['authored_parser_ok'] == 0


@pytest.mark.parametrize('attestation', [None, False, 'true', 1, {}, {'declared': True}])
def test_no_node_attestation_still_blocks(case, attestation):
    result = case(op=operation(node_local_ok=attestation))
    assert not result['ready']
    assert 'made no request' in result['blocking'][0]


def test_catalog_cannot_grant_local_exemption(case):
    result = case({'node_local_ok': True, 'local': True, 'conformance_local_operations': ['local']},
                  'local', op=operation(config={'node_local_ok': True}), extra={'node_local_ok': True})
    (case.path / 'manifest.json').write_text(json.dumps({'node_local_ok': True, 'local_operations': ['local']}))
    result = v.verdict(case.report, case.path)
    assert not result['ready']
    assert result['stats']['local_ok'] == 0


@pytest.mark.parametrize('changes', [
    {'failures': ['No HTTP request executed']},
    {'failures': ['execution: error']},
    {'failures': ['request: invalid']},
    {'fixture_errors': ['invalid fixture']},
])
def test_local_failure_is_never_exempt(case, changes):
    result = case(op=operation(node_local_ok=True, **changes))
    assert not result['ready']
    assert result['stats']['local_ok'] == 0


def test_local_attestation_does_not_skip_audit(case):
    assert not case({'value': 'missing-value'}, 'unrelated', op=operation(node_local_ok=True))['ready']


@pytest.mark.parametrize('changes,blocking,advisory', [
    ({'failures': ['request: rejected']}, True, False),
    ({'failures': ['No spec operation for GET /unknown']}, True, False),
    ({'failures': ['No route for GET /unknown']}, True, False),
    ({'fixture_errors': ['bad fixture']}, True, False),
    ({'failures': ['parser failed']}, True, False),
    ({'failures': ['parser failed'], 'requests': [{'response_status': 200, 'response_source': 'generated'}]}, False, True),
])
def test_existing_request_parser_fixture_rules(case, changes, blocking, advisory):
    op = operation(node_local_ok=True, requests=[{'response_status': 200, 'response_source': 'docs'}])
    op.update(changes)
    result = case(op=op)
    assert bool(result['blocking']) == blocking
    assert bool(result['advisory']) == advisory
    assert result['stats']['local_ok'] == 0


def test_skips_and_list_report_no_audit(case):
    report = {'provider': 'test', 'operations': [operation(skipped='trigger passthrough')]}
    result = v.verdict([report], case.path, audit=False)
    assert result['ready'] and result['stats']['skipped'] == 1
    assert result['stats']['operations'] == 0


def test_cli_shape_cache_and_no_audit(tmp_path):
    # The CLI reads source pages from CONFORMANCE_PAGES: a pre-filled cache keeps it offline.
    report = tmp_path / 'report.json'
    report.write_text(json.dumps([{'provider': 'test', 'operations': []}]))
    (tmp_path / 'manifest.json').write_text(json.dumps({'test': {}}))
    url = 'https://docs.test/chosen'
    (tmp_path / 'inputs.json').write_text(json.dumps({'example': {'source': url, 'config': {'body_json': '{"field":"documented"}'}}}))
    (tmp_path / 'pages').mkdir()
    (tmp_path / 'pages' / hashlib.sha256(url.encode()).hexdigest()[:24]).write_text('<pre>docu<span>mented</span></pre>')
    env = {**os.environ, 'CONFORMANCE_PAGES': str(tmp_path / 'pages')}
    cli = [sys.executable, '-m', 'tests.conformance.verdict', str(report), str(tmp_path)]
    result = json.loads(subprocess.check_output(cli, cwd=BACKEND, env=env))
    assert set(result) == {'provider', 'ready', 'blocking', 'advisory', 'stats'}
    assert result['ready']
    (tmp_path / 'inputs.json').write_text(json.dumps({'example': {'config': {'value': 'missing'}}}))
    result = json.loads(subprocess.check_output(cli + ['--no-audit'], cwd=BACKEND, env=env))
    assert result['ready']
