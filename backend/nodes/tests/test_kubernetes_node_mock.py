"""Native execution against upstream manifests and pinned API route fixtures."""
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import ValidationError
from nodes import kubernetes_node as k
from nodes.core.run_op import run_node_operation
from nodes.core.base import ConfigValidationError
from nodes.core.credential_connect import shape_credential
from utils import ssrf

CASES = json.loads((Path(__file__).parent / 'fixtures/kubernetes/contract_examples.json').read_text())['cases']
TOKEN = 'fixture-bearer-not-live'
AUTH = {'credential_type': k.CREDENTIAL_TYPE, 'api_server_url': 'https://cluster.example.com:6443', 'token': TOKEN}
USER = '00000000-0000-4000-8000-000000000001'
RESOLVE_HOST = ssrf._resolve_host_addresses

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def wire(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        assert request.url.host == 'cluster.example.com' and request.url.port == 6443
        assert request.headers['Authorization'] == 'Bearer ' + TOKEN
        assert TOKEN not in str(request.url)
        status, body, *headers = replies.pop(0)
        if isinstance(body, str):
            return httpx.Response(status, text=body, headers=headers[0] if headers else {'content-type': 'text/plain'})
        return httpx.Response(status, json=body, headers=headers[0] if headers else {})
    native = ssrf.guarded_async_client
    def client(**kwargs):
        assert kwargs['verify'] is True and kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return native(**kwargs, transport=httpx.MockTransport(send))
    monkeypatch.setattr(k, 'guarded_async_client', client)
    return requests, replies

async def run(operation, config=None):
    return await run_node_operation(node_type='automation-kubernetes', operation=operation,
        arguments=deepcopy(CASES[operation]['config'] if config is None else config),
        credential_data=deepcopy(AUTH), user_id=USER)

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_all_25_operations_map_to_one_contract_operation(wire, operation):
    requests, replies = wire
    case = CASES[operation]
    replies.append((201 if case['method'] == 'POST' else 200, deepcopy(case['body'])))
    result = await run(operation)
    assert result['status'] == 'success'
    assert len(requests) == 1 and not replies
    request = requests[0]
    assert request.method == case['method']
    assert request.url.path == case['path'].format(**case['config'])
    assert case['contract_operation']
    if 'manifest_json' in case['config']:
        assert json.loads(request.content) == json.loads(case['config']['manifest_json'])
    elif 'patch_json' in case['config']:
        assert json.loads(request.content) == json.loads(case['config']['patch_json'])
        assert request.headers['content-type'] == 'application/merge-patch+json'
    elif operation == 'scale_deployment':
        assert json.loads(request.content)['spec'] == {'replicas': 3}
    elif operation == 'get_pod_logs':
        assert result['logs'] == case['body']
        assert request.headers['Accept'] == 'text/plain' and request.url.params['follow'] == 'false'
    if operation.startswith('list_'):
        assert request.url.params['limit'] == '100'
        assert result['continue_token'] == 'page-two' and result['items'][0]['name'] == 'nginx'

@pytest.mark.asyncio
async def test_paging_and_selectors(wire):
    requests, replies = wire
    replies.append((200, CASES['list_pods']['body']))
    await run('list_pods', {'namespace': 'default', 'limit': 25, 'continue_token': 'a/b+c==',
        'label_selector': 'app in (nginx,api)', 'field_selector': 'status.phase=Running'})
    assert dict(requests[0].url.params) == {'limit': '25', 'continue': 'a/b+c==',
        'labelSelector': 'app in (nginx,api)', 'fieldSelector': 'status.phase=Running'}

@pytest.mark.asyncio
async def test_dry_run_delete_is_only_a_request(wire):
    requests, replies = wire
    replies.append((202, {'apiVersion': 'v1', 'kind': 'Status', 'status': 'Success'}))
    result = await run('delete_pod', {'namespace': 'default', 'name': 'nginx', 'dry_run': True,
        'propagation_policy': 'Foreground', 'grace_period_seconds': 0})
    assert result['deletion_requested'] is True and 'deleted' not in result
    assert dict(requests[0].url.params) == {'dryRun': 'All', 'propagationPolicy': 'Foreground', 'gracePeriodSeconds': '0'}

@pytest.mark.asyncio
async def test_log_options(wire):
    requests, replies = wire
    replies.append((200, 'previous logs\n'))
    await run('get_pod_logs', {'namespace': 'default', 'name': 'nginx', 'container': 'nginx',
        'since_seconds': 60, 'tail_lines': 200, 'previous': True, 'timestamps': True})
    assert dict(requests[0].url.params) == {'tailLines': '200', 'previous': 'true', 'timestamps': 'true',
        'follow': 'false', 'container': 'nginx', 'sinceSeconds': '60'}

@pytest.mark.asyncio
@pytest.mark.parametrize('code', [401, 403, 404, 409, 422, 429, 500])
async def test_provider_errors_redact_token_and_are_never_retried(wire, code):
    requests, replies = wire
    replies.append((code, {'kind': 'Status', 'status': 'Failure', 'message': 'Forbidden token ' + TOKEN}))
    result = await run('list_namespaces')
    assert result['status'] == 'error' and result['http_status'] == code
    assert result['error'] == 'Forbidden token [redacted]' and len(requests) == 1

@pytest.mark.asyncio
async def test_redirect_never_receives_credentials(wire):
    requests, replies = wire
    replies.append((302, '', {'location': 'https://attacker.example/'}))
    assert (await run('list_namespaces'))['status'] == 'error'
    assert len(requests) == 1

@pytest.mark.asyncio
async def test_status_failure_cannot_prove_connection(wire):
    _, replies = wire
    replies.append((200, {'kind': 'Status', 'status': 'Failure', 'message': 'permission denied'}))
    assert (await run('list_namespaces'))['status'] == 'error'

@pytest.mark.asyncio
async def test_private_destination_blocked_before_http(wire, monkeypatch):
    requests, _ = wire
    import asyncio
    monkeypatch.setenv('OUTBOUND_ALLOW_PRIVATE_IPS', 'false')
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', RESOLVE_HOST)
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(return_value=[(2, 1, 6, '', ('127.0.0.1', 6443))]))
    with pytest.raises(ssrf.SSRFError):
        await run('list_namespaces')
    assert requests == []

@pytest.mark.parametrize('field,value', [
    ('api_server_url', 'http://cluster.example.com'), ('api_server_url', 'https://user:password@cluster.example.com'),
    ('api_server_url', 'https://cluster.example.com/api/v1'), ('api_server_url', 'https://cluster.example.com/?token=secret'),
    ('api_server_url', 'https://cluster.example.com:0'), ('token', 'Bearer fixture-token'),
    ('token', 'fixture\r\nX-Injected: bad'), ('token', 'https://cluster.example.com'), ('token', '<token>'),
    ('ca_certificate', '-----BEGIN PRIVATE KEY-----\nwrong'), ('ca_certificate', '-----BEGIN CERTIFICATE-----\ninvalid')])
def test_invalid_credential_pastes(field, value):
    with pytest.raises(ValidationError):
        k.KubernetesBearerTokenCredential.model_validate({**AUTH, field: value})

def test_manual_credential_default_type():
    blob = {key: value for key, value in AUTH.items() if key != 'credential_type'}
    shaped, errors, resolved = shape_credential(k.CREDENTIAL_TYPE, blob)
    assert not errors and resolved[1] is k.KubernetesBearerTokenCredential
    assert k.KubernetesBearerTokenCredential.model_validate(shaped).credential_type == k.CREDENTIAL_TYPE
    assert k.KubernetesBearerTokenCredential.model_validate(blob).credential_type == k.CREDENTIAL_TYPE

@pytest.mark.parametrize('operation,updates', [
    ('get_pod', {'name': '../secrets'}), ('get_pod', {'namespace': 'default/pods'}), ('list_pods', {'limit': 0}),
    ('scale_deployment', {'replicas': -1}), ('create_pod', {'manifest_json': '[]'}),
    ('create_pod', {'manifest_json': '{"apiVersion":"v1","kind":"Secret","metadata":{"name":"secret"}}'}),
    ('create_pod', {'manifest_json': '{"apiVersion":"v1","kind":"Pod","metadata":{"name":"nginx","namespace":"another"}}'}),
    ('patch_configmap', {'patch_json': '{"metadata":{"namespace":"another"}}'}),
    ('patch_deployment', {'patch_json': '{"metadata":{"name":"another"}}'})])
def test_resource_scope_and_body_validation(operation, updates):
    with pytest.raises(ConfigValidationError):
        k.KubernetesNode.parse_config({'config': {'operation': operation, **CASES[operation]['config'], **updates}, 'credentials': AUTH})


def test_custom_ca_accepts_kubeconfig_base64_and_pem_with_tls_verification():
    import base64
    import ssl
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Kubernetes unit-test CA')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(1).not_valid_before(now)
        .not_valid_after(now + timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode('ascii'))
    encoded = base64.b64encode(cert.encode('ascii')).decode('ascii')
    for supplied in (cert, encoded):
        auth = k.KubernetesBearerTokenCredential.model_validate({**AUTH, 'ca_certificate': supplied})
        assert auth.ca_certificate == encoded
        context = ssl.create_default_context(cadata=base64.b64decode(auth.ca_certificate).decode('ascii'))
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
