"""Native dbt Administrative API metadata reads through account-scoped tokens.

Closed v3/v2 routes and parent witnesses keep catalog and run metadata scoped.
Artifact files are reduced to summaries; this node never starts warehouse work.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from contextvars import ContextVar
from datetime import datetime
from typing import Annotated, Literal, Optional, Union

from opentelemetry.instrumentation.utils import suppress_instrumentation
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_serializer, model_validator

from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = 'automation-dbt-cloud'
TAGS = ('dbt_cloud_service_token', 'dbt_cloud_pat')
MAX_BYTES = 2 * 1024 * 1024
ID = Annotated[str, StringConstraints(strict=True, pattern=r'^[1-9][0-9]{0,15}$')]
Region = Literal['us1', 'us2', 'us3', 'us5', 'eu1', 'eu2', 'eu3', 'eu4', 'au1', 'au2', 'jp1']
Operation = Literal['check_connection', 'list_accounts', 'get_account', 'list_projects', 'get_project', 'list_environments', 'get_environment', 'list_jobs', 'get_job', 'list_runs', 'get_run', 'get_run_status', 'list_run_artifacts', 'get_run_artifact_summary']
OPERATIONS = ('check_connection', 'list_accounts', 'get_account', 'list_projects', 'get_project', 'list_environments', 'get_environment', 'list_jobs', 'get_job', 'list_runs', 'get_run', 'get_run_status', 'list_run_artifacts', 'get_run_artifact_summary')
ARTIFACTS = ('manifest.json', 'run_results.json', 'catalog.json')
RUN_STATUSES = {1: 'queued', 2: 'starting', 3: 'running', 10: 'success', 20: 'error', 30: 'cancelled'}
_private_http = ContextVar('dbt_cloud_private_http', default=False)


class _PrivateHTTPFilter(logging.Filter):
    def filter(self, record):
        return not _private_http.get()


for _logger in ('httpx', 'httpcore', 'httpcore.connection', 'httpcore.http11', 'httpcore.http2'):
    logging.getLogger(_logger).addFilter(_PrivateHTTPFilter())


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)


class _TokenCredential(BaseModel):
    access_token: Annotated[str, StringConstraints(strict=True, min_length=12, max_length=4096)] = Field(title='Existing Account Token', repr=False, json_schema_extra={'ui:widget': 'password'})
    account_id: ID = Field(title='Account ID', description='This token must already belong to this account. Local ID restrictions are not provider permission introspection.')
    deployment: Literal['us_multi_tenant', 'cell'] = Field(title='Administrative API Deployment', description='Use the publisher-spec US host or a documented Account settings cell access URL. Other legacy/custom single-tenant/VPC hosts are outside this node.')
    region: Optional[Region] = Field(None, title='Cell Region')
    account_prefix: Optional[Annotated[str, StringConstraints(strict=True, min_length=1, max_length=63, pattern=r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$')]] = Field(None, title='Cell Account Prefix', description='Hostname prefix from Account settings, without scheme, path, port or dots.')
    project_ids: list[ID] = Field(min_length=1, max_length=100, title='Allowed Project IDs', description='Explicit local current restrictions. Listing projects filters to these IDs; saved restrictions never grow automatically.')
    allowed_operations: list[Operation] = Field(min_length=1, max_length=14, title='Allowed Read Operations', description='Local operation restrictions; actual permission sets and account API entitlement still come from dbt.')
    model_config = ConfigDict(extra='ignore', validate_assignment=True)

    @model_validator(mode='before')
    @classmethod
    def native_fields(cls, data):
        if not isinstance(data, dict) or set(data) - set(cls.model_fields) - {'token_version', 'updated_at'}:
            raise ValueError('Use only native token/account/deployment/project fields.')
        return data

    @field_validator('access_token')
    @classmethod
    def clean_token(cls, value):
        return clean_secret(value, field_name='Existing Account Token')

    @model_validator(mode='after')
    def native_scope(self):
        if (self.deployment == 'cell') != (self.region is not None and self.account_prefix is not None):
            raise ValueError('A cell requires its region and account prefix.')
        if self.deployment != 'cell' and (self.region is not None or self.account_prefix is not None):
            raise ValueError('Legacy multi-tenant deployments cannot carry a cell prefix or region.')
        if len(set(self.project_ids)) != len(self.project_ids) or len(set(self.allowed_operations)) != len(self.allowed_operations):
            raise ValueError('Supply distinct project and operation restrictions.')
        if 'check_connection' not in self.allowed_operations:
            raise ValueError('The protected account access check must be permitted.')
        return self

    @model_serializer(mode='wrap')
    def preserve_tag(self, handler):
        result = handler(self)
        result['credential_type'] = self.credential_type
        return result


class DbtCloudServiceTokenCredential(_TokenCredential):
    credential_type: Literal['dbt_cloud_service_token'] = Field('dbt_cloud_service_token', json_schema_extra={'ui:hidden': True})
    model_config = ConfigDict(title='dbt Cloud Service Token', json_schema_extra={'x-credential-url': 'https://docs.getdbt.com/docs/dbt-apis/service-tokens', 'x-credential-description': 'Existing service token with Administrative API read permissions on the supplied account/projects. Metadata-only/Semantic Layer permissions may not permit these endpoints. Plan/IP allowlist/role access must be checked in dbt.'})


class DbtCloudPersonalAccessTokenCredential(_TokenCredential):
    credential_type: Literal['dbt_cloud_pat'] = Field('dbt_cloud_pat', json_schema_extra={'ui:hidden': True})
    model_config = ConfigDict(title='dbt Cloud Personal Access Token', json_schema_extra={'x-credential-url': 'https://docs.getdbt.com/docs/dbt-apis/user-tokens', 'x-credential-description': 'Existing account-scoped PAT inheriting the creating user’s permissions. Deprecated user API keys are unsupported; this node does not mint, rotate, refresh or introspect tokens.'})


Credential = Union[DbtCloudServiceTokenCredential, DbtCloudPersonalAccessTokenCredential]


def _op(value, title):
    return Field(value, title=title, json_schema_extra={'const': value, 'ui:hidden': True, 'x-display-name': title, 'x-category': 'Administrative Metadata', 'x-is-trigger': False})


def _dynamic(field, parent=None):
    return {'x-dynamic-options': {'field_name': field, 'searchable': True, 'allow_custom': True, **({'depends_on': parent} if parent else {})}}


class DbtCloudCheckConfig(_Model):
    operation: Literal['check_connection'] = _op('check_connection', 'Check Protected Account Access')


class DbtCloudListAccountsConfig(_Model):
    operation: Literal['list_accounts'] = _op('list_accounts', 'List Current Account Metadata')


class DbtCloudAccountTarget(_Model):
    account_id: ID = Field(json_schema_extra=_dynamic('account_id'))


class DbtCloudGetAccountConfig(DbtCloudAccountTarget):
    operation: Literal['get_account'] = _op('get_account', 'Get Account Metadata')


class DbtCloudPage(_Model):
    limit: int = Field(25, ge=1, le=100, strict=True)
    offset: int = Field(0, ge=0, le=1000000, strict=True, description='One bounded page. Documented count/total_count drives continuation; URLs and inferred cursors are not followed.')


class DbtCloudListProjectsConfig(DbtCloudAccountTarget, DbtCloudPage):
    operation: Literal['list_projects'] = _op('list_projects', 'List Allowed Project Metadata')


class DbtCloudProjectTarget(DbtCloudAccountTarget):
    project_id: ID = Field(json_schema_extra=_dynamic('project_id', 'account_id'))


class DbtCloudGetProjectConfig(DbtCloudProjectTarget):
    operation: Literal['get_project'] = _op('get_project', 'Get Project Metadata')


class DbtCloudListEnvironmentsConfig(DbtCloudProjectTarget, DbtCloudPage):
    operation: Literal['list_environments'] = _op('list_environments', 'List Project Environment Metadata')


class DbtCloudEnvironmentTarget(DbtCloudProjectTarget):
    environment_id: ID = Field(json_schema_extra=_dynamic('environment_id', 'project_id'))


class DbtCloudGetEnvironmentConfig(DbtCloudEnvironmentTarget):
    operation: Literal['get_environment'] = _op('get_environment', 'Get Environment Metadata')


class DbtCloudListJobsConfig(DbtCloudEnvironmentTarget, DbtCloudPage):
    operation: Literal['list_jobs'] = _op('list_jobs', 'List Environment Job Definitions')


class DbtCloudJobTarget(DbtCloudEnvironmentTarget):
    job_id: ID = Field(json_schema_extra=_dynamic('job_id', 'environment_id'))


class DbtCloudGetJobConfig(DbtCloudJobTarget):
    operation: Literal['get_job'] = _op('get_job', 'Get Job Definition Metadata')


class DbtCloudListRunsConfig(DbtCloudJobTarget, DbtCloudPage):
    operation: Literal['list_runs'] = _op('list_runs', 'List Job Run Metadata')
    run_status: Optional[Literal[1, 2, 3, 10, 20, 30]] = Field(None, title='Run Status Filter')


class DbtCloudRunTarget(DbtCloudJobTarget):
    run_id: ID = Field(json_schema_extra=_dynamic('run_id', 'job_id'))


class DbtCloudGetRunConfig(DbtCloudRunTarget):
    operation: Literal['get_run'] = _op('get_run', 'Get Run Metadata')


class DbtCloudGetRunStatusConfig(DbtCloudRunTarget):
    operation: Literal['get_run_status'] = _op('get_run_status', 'Get Current Run Status')


class DbtCloudListArtifactsConfig(DbtCloudRunTarget):
    operation: Literal['list_run_artifacts'] = _op('list_run_artifacts', 'List Supported Run Artifacts')


class DbtCloudArtifactSummaryConfig(DbtCloudRunTarget):
    operation: Literal['get_run_artifact_summary'] = _op('get_run_artifact_summary', 'Get Projected JSON Artifact Summary')
    artifact: Literal['manifest.json', 'run_results.json', 'catalog.json'] = Field(description='Only these documented JSON files; no logs, SQL, arbitrary paths, binary/OTel files or media.')
    step: Optional[int] = Field(None, ge=1, le=100, strict=True, description='Documented 1-based step index. Omit for the last step; no execution or retry occurs.')


DbtCloudConfig = Annotated[Union[DbtCloudCheckConfig, DbtCloudListAccountsConfig, DbtCloudGetAccountConfig, DbtCloudListProjectsConfig, DbtCloudGetProjectConfig, DbtCloudListEnvironmentsConfig, DbtCloudGetEnvironmentConfig, DbtCloudListJobsConfig, DbtCloudGetJobConfig, DbtCloudListRunsConfig, DbtCloudGetRunConfig, DbtCloudGetRunStatusConfig, DbtCloudListArtifactsConfig, DbtCloudArtifactSummaryConfig], Field(discriminator='operation')]


class DbtCloudFullConfig(NodeConfig[DbtCloudConfig, Credential]):
    pass


def _credential(raw):
    if not isinstance(raw, dict) or raw.get('credential_type') not in TAGS:
        raise ValueError('Choose the distinct native dbt service-token or personal-token method.')
    model = DbtCloudServiceTokenCredential if raw['credential_type'] == TAGS[0] else DbtCloudPersonalAccessTokenCredential
    if set(raw) - set(model.model_fields) - {'token_version', 'updated_at'}:
        raise ValueError('Only native token/account/deployment/project restrictions are accepted.')
    try:
        return model.model_validate(raw)
    except ValueError:
        raise ValueError('Invalid native dbt account token or restriction.') from None


def _id(value):
    if type(value) is not int or not 1 <= value <= 9999999999999999:
        raise ValueError('Malformed documented resource identity.')
    return str(value)


def _text(value, limit=256):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or any(ord(char) < 32 for char in value):
        raise ValueError('Malformed bounded metadata text.')
    return value


def _private(credential, value):
    if credential.access_token in json.dumps(value, allow_nan=False):
        raise ValueError('Credential material cannot appear in native parameters or outputs.')


class _ProviderFailure(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__({401: 'dbt rejected authentication.', 403: 'dbt denied account, project, permission or IP access.', 404: 'dbt resource or artifact was not found.', 429: 'dbt rate limit reached; no automatic retry.'}.get(status, 'dbt returned an unsupported response status.'))


class DbtCloudNode(WorkflowNode):
    integration_type = 'automation-dbt-cloud'
    credential_provider_labels = {'dbt_cloud': 'dbt Cloud Account'}
    connection_evidence = ConnectionEvidence(operation='check_connection', noun='protected account API', proves='reachability')

    @classmethod
    def get_config_model(cls):
        return DbtCloudFullConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data.get('credentials'), dict):
            _credential(config_data['credentials'])
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            if isinstance(config_data.get('credentials'), dict):
                _credential(config_data['credentials'])
        except ValueError:
            return ValidationResult(valid=False, errors=['Choose the native dbt account token and current deployment/project restrictions.'])
        return super().validate_config(config_data)

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        credential = _credential(credential_data)
        try:
            await cls._dispatch(credential, DbtCloudCheckConfig())
        except _ProviderFailure as exc:
            return {'valid': False if exc.status in (401, 403) else None, 'error': str(exc)}
        except Exception:
            return {'valid': None, 'error': 'Protected account access remains unverified.'}
        return {'valid': True, 'proves': 'reachability', 'account_identity_verified': False}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        """Existing account tokens do not rotate automatically.

        Staging resolves saved-row access and lookup admission before this hook.
        """
        return _credential(credential_data).model_dump()

    @staticmethod
    def _host(credential):
        if credential.deployment == 'cell':
            return f'{credential.account_prefix}.{credential.region}.dbt.com'
        return 'cloud.getdbt.com'

    @classmethod
    async def _recheck(cls, authority, credential):
        if authority is not None:
            from utils.credentials import resolve_credential_with_owner_fallback
            current = await resolve_credential_with_owner_fallback(**authority)
            if not current or _credential(current).model_dump() != credential.model_dump():
                raise ValueError('Current saved dbt credential is unavailable or changed.')

    @classmethod
    async def _request(cls, credential, authority, route, config, *, collection=False):
        account = credential.account_id
        params = {}
        if route == 'accounts':
            path = '/api/v3/accounts/'
        elif route == 'account':
            path = f'/api/v2/accounts/{account}/'
        elif route == 'projects':
            path = f'/api/v3/accounts/{account}/projects/'
            if not collection: path += config.project_id + '/'
        elif route == 'environments':
            path = f'/api/v3/accounts/{account}/projects/{config.project_id}/environments/'
            if not collection: path += config.environment_id + '/'
        elif route in ('jobs', 'runs'):
            path = f'/api/v2/accounts/{account}/{route}/'
            if collection:
                params.update(project_id=config.project_id, environment_id=config.environment_id)
                if route == 'runs':
                    params['job_definition_id'] = config.job_id
                    if config.run_status is not None: params['status'] = config.run_status
            else:
                path += getattr(config, 'job_id' if route == 'jobs' else 'run_id') + '/'
        elif route in ('artifacts', 'artifact_summary'):
            path = f'/api/v2/accounts/{account}/runs/{config.run_id}/artifacts/'
            if route == 'artifact_summary':
                path += config.artifact
                if config.step is not None: params['step'] = config.step
        else:
            raise ValueError('Unsupported closed Administrative API route.')
        if collection:
            params.update(limit=config.limit, offset=config.offset)
        _private(credential, params)
        await cls._recheck(authority, credential)
        marker = _private_http.set(True)
        try:
            with suppress_instrumentation():
                async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                    async with client.stream('GET', 'https://' + cls._host(credential) + path, headers={'Authorization': 'Bearer ' + credential.access_token, 'Accept': 'application/json'}, params=params) as response:
                        if response.status_code != 200:
                            raise _ProviderFailure(response.status_code)
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_BYTES: raise ValueError('dbt response exceeds the native bound.')
                            chunks.append(chunk)
                        if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                            raise ValueError('This operation requires JSON; redirects, binary and text artifacts are unsupported.')
                        try:
                            payload = json.loads(b''.join(chunks), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
                        except (ValueError, UnicodeError):
                            raise ValueError('Malformed dbt JSON.') from None
                        if not isinstance(payload, dict): raise ValueError('Expected documented JSON object.')
                        if route != 'artifact_summary':
                            status = payload.get('status')
                            if not isinstance(status, dict) or status.get('is_success') is not True or type(status.get('code', 200)) is not int or status.get('code', 200) != 200 or 'data' not in payload:
                                raise ValueError('dbt error or malformed status envelope cannot report success.')
                            payload = payload['data'] if not collection else payload
            await cls._recheck(authority, credential)
            return payload
        finally:
            _private_http.reset(marker)

    @staticmethod
    def _record(raw, kind, config, account):
        if not isinstance(raw, dict): raise ValueError('Expected documented resource object.')
        row = {'id': _id(raw.get('id')), 'account_id': account}
        if kind == 'account':
            if row['id'] != account: raise ValueError('Account witness changed.')
            row['name'] = _text(raw.get('name'))
        else:
            if _id(raw.get('account_id')) != account: raise ValueError('Response account differs from current account.')
            if kind != 'projects':
                if _id(raw.get('project_id')) != config.project_id: raise ValueError('Response project parent changed.')
                row['project_id'] = config.project_id
            if kind in ('jobs', 'runs'):
                if _id(raw.get('environment_id')) != config.environment_id: raise ValueError('Response environment parent changed.')
                row['environment_id'] = config.environment_id
            if kind == 'runs':
                if _id(raw.get('job_definition_id')) != config.job_id: raise ValueError('Response job parent changed.')
                status = raw.get('status')
                if type(status) is not int or status not in RUN_STATUSES: raise ValueError('Unknown run status remains unverified.')
                row.update(job_id=config.job_id, status_code=status, run_status=RUN_STATUSES[status], is_complete=status in (10, 20, 30))
            else:
                row['name'] = _text(raw.get('name'))
                if 'state' in raw:
                    if type(raw['state']) is not int or raw['state'] not in (1, 2): raise ValueError('Malformed resource state.')
                    row['state'] = raw['state']
                if kind == 'environments':
                    if raw.get('type') not in ('development', 'deployment'): raise ValueError('Malformed environment type.')
                    row['type'] = raw['type']
                if kind == 'jobs':
                    if 'execute_steps' in raw:
                        if not isinstance(raw['execute_steps'], list) or len(raw['execute_steps']) > 100 or not all(isinstance(step, str) for step in raw['execute_steps']): raise ValueError('Malformed job step metadata.')
                        row['command_count'] = len(raw['execute_steps'])
                    if isinstance(raw.get('triggers'), dict) and type(raw['triggers'].get('schedule')) is bool:
                        row['schedule_enabled'] = raw['triggers']['schedule']
        for field in ('created_at', 'updated_at', 'started_at', 'finished_at'):
            if raw.get(field) is not None:
                value = _text(raw[field], 64)
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if parsed.tzinfo is None: raise ValueError('Metadata date requires timezone.')
                row[field] = value
        return row

    @staticmethod
    def _page(payload, config):
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), list) or len(payload['data']) > config.limit:
            raise ValueError('Expected bounded documented list envelope.')
        page = payload.get('extra', {}).get('pagination') if isinstance(payload.get('extra'), dict) else None
        if not isinstance(page, dict): raise ValueError('Documented pagination counts are required.')
        count, total = page.get('count'), page.get('total_count')
        ids = [_id(row.get('id')) for row in payload['data'] if isinstance(row, dict)]
        if len(ids) != len(payload['data']) or len(ids) != len(set(ids)) or type(count) is not int or type(total) is not int or count != len(ids) or not count <= total <= 2147483647 or count and config.offset + count > total or not count and config.offset < total:
            raise ValueError('Malformed page counts or duplicate resource identities.')
        next_offset = config.offset + count if count and config.offset + count < total else None
        if next_offset is not None and next_offset > 1000000: raise ValueError('Continuation exceeds the native offset bound.')
        return payload['data'], {'count': count, 'total_count': total, 'limit': config.limit, 'offset': config.offset, 'next_offset': next_offset, 'count_scope': 'provider query before local project restriction', 'continuation_verified': True}

    @staticmethod
    def _artifact_summary(raw, name):
        metadata = raw.get('metadata')
        if not isinstance(metadata, dict): raise ValueError('Artifact metadata is required.')
        result = {'artifact': name, 'raw_artifact_returned': False}
        if metadata.get('dbt_version') is not None:
            version = _text(metadata['dbt_version'], 64)
            if not re.fullmatch(r'[A-Za-z0-9.+_-]+', version): raise ValueError('Malformed artifact version.')
            result['dbt_version'] = version
        if name == 'run_results.json':
            rows = raw.get('results')
            if not isinstance(rows, list) or len(rows) > 10000 or not all(isinstance(row, dict) and isinstance(row.get('status'), str) for row in rows): raise ValueError('Malformed bounded run results artifact.')
            known = {'success', 'error', 'skipped', 'fail', 'warn', 'pass', 'runtime error', 'partial success', 'no-op'}
            result.update(result_count=len(rows), status_counts=dict(Counter(row['status'] if row['status'] in known else 'other' for row in rows)))
        else:
            fields = ('nodes', 'sources')
            for field in fields:
                records = raw.get(field)
                if not isinstance(records, dict) or len(records) > 10000 or not all(isinstance(row, dict) for row in records.values()): raise ValueError('Malformed bounded artifact resource map.')
                result[field + '_count'] = len(records)
        return result

    @classmethod
    async def _dispatch(cls, credential, config, authority=None):
        op = config.operation
        if op not in credential.allowed_operations or getattr(config, 'account_id', credential.account_id) != credential.account_id or hasattr(config, 'project_id') and config.project_id not in credential.project_ids:
            raise ValueError('Operation/account/project is outside current restrictions.')
        _private(credential, config.model_dump())
        account_raw = await cls._request(credential, authority, 'account', config)
        account = cls._record(account_raw, 'account', config, credential.account_id)
        result = {'status': 'success', 'action': op, 'account_identity_verified': False, 'account_access_verified': True, 'mutation_performed': False}
        if op == 'check_connection':
            result.update(proves='reachability', write_access_verified=False)
        elif op == 'get_account':
            result['record'] = account
        elif op == 'list_accounts':
            rows = await cls._request(credential, authority, 'accounts', config)
            if not isinstance(rows, list) or len(rows) > 100: raise ValueError('Expected bounded account list.')
            ids = [_id(row.get('id')) for row in rows if isinstance(row, dict)]
            if len(ids) != len(rows) or len(set(ids)) != len(ids) or credential.account_id not in ids: raise ValueError('Current account not present in protected list.')
            result.update(records=[cls._record(row, 'account', config, credential.account_id) for row in rows if str(row['id']) == credential.account_id], continuation_verified=False)
        else:
            witnesses = [('projects', 'project_id'), ('environments', 'environment_id'), ('jobs', 'job_id'), ('runs', 'run_id')]
            target = None
            for kind, field in witnesses:
                if hasattr(config, field):
                    raw = await cls._request(credential, authority, kind, config)
                    target = cls._record(raw, kind, config, credential.account_id)
                    if target['id'] != getattr(config, field): raise ValueError('Protected parent witness identity changed.')
            if op in ('get_project', 'get_environment', 'get_job', 'get_run'):
                result['record'] = target
            elif op == 'get_run_status':
                result['record'] = {key: target[key] for key in ('id', 'account_id', 'project_id', 'environment_id', 'job_id', 'status_code', 'run_status', 'is_complete')}
            elif op.startswith('list_') and op != 'list_run_artifacts':
                kind = op.removeprefix('list_')
                payload = await cls._request(credential, authority, kind, config, collection=True)
                rows, page = cls._page(payload, config)
                records = [cls._record(row, kind, config, credential.account_id) for row in rows]
                if kind == 'projects': records = [row for row in records if row['id'] in credential.project_ids]
                if kind == 'runs' and config.run_status is not None and any(row['status_code'] != config.run_status for row in records): raise ValueError('Run status filter was not respected.')
                result.update(records=records, **page)
            else:
                if not target['is_complete']: raise ValueError('Artifacts require a documented completed run witness.')
                if op == 'list_run_artifacts':
                    paths = await cls._request(credential, authority, 'artifacts', config)
                    if not isinstance(paths, list) or len(paths) > 10000 or not all(isinstance(item, str) and len(item) <= 1024 for item in paths): raise ValueError('Malformed bounded artifact list.')
                    result.update(artifacts=[name for name in ARTIFACTS if name in paths], other_artifact_count=sum(name not in ARTIFACTS for name in paths), projection='Only three supported JSON filenames; other artifact paths withheld.')
                else:
                    raw = await cls._request(credential, authority, 'artifact_summary', config)
                    result['summary'] = cls._artifact_summary(raw, config.artifact)
        if op != 'check_connection':
            result['api_versions'] = ['v3', 'v2']
        _private(credential, result)
        return result

    async def execute(self, inputs):
        try:
            if not isinstance(self.config, DbtCloudFullConfig) or self.config.credentials is None: raise ValueError('Native credential and config required.')
            credential = _credential(self.config.credentials.model_dump())
            if 'credentials' in self.node_data and _credential(self.node_data['credentials']).model_dump() != credential.model_dump():
                raise ValueError('Raw credential differs from its native parsed shape.')
            authority = None
            if self.node_data.get('credential_id'):
                from utils.database_pool import get_native_pool
                authority = dict(credential_id=self.node_data['credential_id'], user_id=self.user_id,
                    pool=getattr(self, '_approval_pool', None) or get_native_pool(),
                    org_id=getattr(self, 'organization_id', None), workflow_id=getattr(self, 'workflow_id', None))
            return await self._dispatch(credential, self.config.config, authority)
        except _ProviderFailure as exc:
            return {'status': 'error', 'error': str(exc), 'http_status': exc.status}
        except Exception as exc:
            return {'status': 'error', 'error': 'dbt Administrative API access remains unverified; check current account token, deployment, project/parent restrictions and documented JSON response.', 'error_type': type(exc).__name__}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None, limit=None):
        credential = _credential(credential_data)
        authority = None
        await cls._recheck(authority, credential)
        context = context or {}
        if page_token is not None and not re.fullmatch(r'0|[1-9][0-9]{0,5}|1000000', str(page_token)): raise ValueError('Use native bounded offset tokens, not URLs.')
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 100): raise ValueError('Use a bounded selector limit.')
        if field_name == 'account_id':
            result = await cls._dispatch(credential, DbtCloudCheckConfig(), authority)
            rows = [{'value': credential.account_id, 'label': credential.account_id, 'metadata': {'account_access_verified': True}}]
        else:
            models = {'project_id': DbtCloudListProjectsConfig, 'environment_id': DbtCloudListEnvironmentsConfig, 'job_id': DbtCloudListJobsConfig, 'run_id': DbtCloudListRunsConfig}
            model = models.get(field_name)
            if model is None: raise ValueError('Unsupported native dbt selector.')
            arguments = {'account_id': context.get('account_id'), 'offset': int(page_token or 0), 'limit': limit or 25}
            for parent in ('project_id', 'environment_id', 'job_id'):
                if parent in model.model_fields: arguments[parent] = context.get(parent)
            result = await cls._dispatch(credential, model.model_validate(arguments), authority)
            rows = [{'value': row['id'], 'label': row.get('name', row['id']), 'metadata': {key: row[key] for key in ('account_id', 'project_id', 'environment_id', 'job_id') if key in row}} for row in result['records']]
        if search:
            needle = _text(search, 100).casefold()
            rows = [row for row in rows if needle in row['label'].casefold() or needle in row['value']]
        _private(credential, rows)
        return {'options': rows, 'next_page_token': str(result['next_offset']) if result.get('next_offset') is not None else None}
