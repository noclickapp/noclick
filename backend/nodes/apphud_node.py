"""Closed Apphud app-level S2S Analytics reads, including read-semantic POST queries."""
from __future__ import annotations

import json
import logging
import math
from contextvars import ContextVar
from datetime import datetime
from typing import Annotated, Literal, Union

from opentelemetry.instrumentation.utils import suppress_instrumentation
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_serializer, model_validator

from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
import httpx

NODE_TYPE = 'automation-apphud'
ROOT = 'https://api.apphud.com/api/public/v1'
MAX_BYTES = 2 * 1024 * 1024
Identifier = Annotated[str, StringConstraints(strict=True, pattern=r'^[A-Za-z0-9_-]{1,128}$')]
Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=255)]
Operation = Literal['list_charts', 'get_chart_options', 'get_filter_values', 'query_line_chart', 'query_column_chart']
OPERATIONS = ('list_charts', 'get_chart_options', 'get_filter_values', 'query_line_chart', 'query_column_chart')
Condition = Literal['equals', 'not_equals', 'contains', 'not_contains']
_private_http = ContextVar('apphud_private_http', default=False)


class _PrivateHTTPFilter(logging.Filter):
    def filter(self, record):
        return not _private_http.get()


for _logger in ('httpx', 'httpcore', 'httpcore.connection', 'httpcore.http11', 'httpcore.http2'):
    logging.getLogger(_logger).addFilter(_PrivateHTTPFilter())


def _text(value, limit=255, empty=False):
    if not isinstance(value, str) or len(value) > limit or not empty and not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('Malformed bounded Apphud metadata text.')
    return value


def _private(credential, value):
    if json.dumps(credential.api_key)[1:-1] in json.dumps(value, allow_nan=False, default=str):
        raise ValueError('Credential material cannot appear in native parameters or outputs.')


def _integer(value, maximum=1000000):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Expected a bounded nonnegative integer.')
    return value


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Expected a finite documented analytics number.')
    return value


def _timestamp(value):
    _text(value, 64)
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Use ISO-8601 timestamps with an explicit UTC offset.') from None
    if result.utcoffset() is None:
        raise ValueError('Use ISO-8601 timestamps with an explicit UTC offset.')
    return result


class ApphudAPIKeyCredential(BaseModel):
    credential_type: Literal['apphud_s2s_api_key'] = Field('apphud_s2s_api_key', json_schema_extra={'ui:hidden': True})
    api_key: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4096)] = Field(title='Existing App-level S2S API Key', repr=False, json_schema_extra={'ui:widget': 'password'})
    app_id: Annotated[str, StringConstraints(strict=True, pattern=r'^[A-Za-z0-9]{8}$')] = Field(title='Apphud Application ID', description='The eight-character application identifier from App settings. This is not a bundle ID. The fixed key/app pair is used on every chart request.')
    chart_ids: list[Identifier] = Field(default_factory=list, max_length=40, title='Allowed Chart IDs', description='Explicit local restrictions. Catalog discovery never extends this list; it does not prove account identity or paid access.')
    allowed_operations: list[Operation] = Field(min_length=1, max_length=5, title='Allowed Operations', description='List Charts is required for current protected discovery. All supported operations are analytics reads, including POST queries.')
    model_config = ConfigDict(extra='ignore', validate_assignment=True, title='Apphud App-level S2S API Key', json_schema_extra={'x-credential-url': 'https://docs.apphud.com/docs/analytics-api', 'x-credential-description': 'Supply an existing app-level S2S key, not an SDK or Customer API query key. Sent only in the Bearer header. Expert+ availability and this key’s entitlement remain unverified until protected reads succeed.'})

    @model_validator(mode='before')
    @classmethod
    def native_fields(cls, data):
        if not isinstance(data, dict) or set(data) - set(cls.model_fields) - {'token_version', 'updated_at'}:
            raise ValueError('Supply only native Apphud app-level credentials and explicit restrictions.')
        return data

    @field_validator('api_key')
    @classmethod
    def token_only(cls, value):
        value = clean_secret(value, field_name='Existing Apphud S2S API Key')
        if not value or any(char.isspace() or ord(char) < 33 or ord(char) == 127 for char in value):
            raise ValueError('Supply the raw header-safe key without a Bearer prefix or whitespace.')
        return value

    @model_validator(mode='after')
    def restrictions(self):
        if 'list_charts' not in self.allowed_operations or any(len(set(values)) != len(values) for values in (self.chart_ids, self.allowed_operations)):
            raise ValueError('Use distinct restrictions and preserve List Charts reachability.')
        _private(self, {'app_id': self.app_id, 'chart_ids': self.chart_ids})
        return self

    @model_serializer(mode='wrap')
    def preserve_tag(self, handler):
        result = handler(self)
        result['credential_type'] = self.credential_type
        return result


class _Model(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)


def _op(value, title):
    return Field(value, title=title, json_schema_extra={'const': value, 'ui:hidden': True, 'x-display-name': title, 'x-category': 'Analytics', 'x-is-trigger': False})


class ApphudListChartsConfig(_Model):
    operation: Literal['list_charts'] = _op('list_charts', 'List App Charts')


class _ChartConfig(_Model):
    chart_id: Identifier = Field(title='Chart', json_schema_extra={'x-dynamic-options': {'field_name': 'chart_id', 'searchable': True, 'allow_custom': True}})


class ApphudGetChartOptionsConfig(_ChartConfig):
    operation: Literal['get_chart_options'] = _op('get_chart_options', 'Get Chart Options')


class ApphudFilterValue(_Model):
    condition: Condition
    value: Text


class ApphudFilter(_Model):
    id: Identifier
    condition: Condition | None = None
    values: list[ApphudFilterValue] = Field(min_length=1, max_length=20)


class ApphudGetFilterValuesConfig(_ChartConfig):
    operation: Literal['get_filter_values'] = _op('get_filter_values', 'Discover Filter Values')
    filter_id: Identifier = Field(title='Filter', json_schema_extra={'x-dynamic-options': {'field_name': 'filter_id', 'depends_on': ['chart_id'], 'searchable': True, 'allow_custom': True}})
    filters: list[ApphudFilter] = Field(default_factory=list, max_length=20, description='Different filters combine with AND. Values inside a filter combine with OR unless a negative filter-level condition changes this.')


class ApphudTimeRange(_Model):
    from_time: Text = Field(alias='from', title='From (ISO-8601 with Offset)')
    to: Text = Field(title='To (ISO-8601 with Same Offset)')

    @model_validator(mode='after')
    def ordered_offsets(self):
        start, end = _timestamp(self.from_time), _timestamp(self.to)
        if start.utcoffset() != end.utcoffset() or start >= end:
            raise ValueError('From must precede To; both timestamps must have the same UTC offset.')
        return self


class ApphudSegment(_Model):
    id: Identifier


class _QueryConfig(_ChartConfig):
    time_range: ApphudTimeRange
    additional: dict[Identifier, Text] = Field(default_factory=dict, max_length=20, description='Exact string keys and string values discovered from the current chart catalog. Required calculation parameters must be supplied; no guessed defaults.')
    filters: list[ApphudFilter] = Field(default_factory=list, max_length=20)


class ApphudQueryLineChartConfig(_QueryConfig):
    operation: Literal['query_line_chart'] = _op('query_line_chart', 'Query Line Chart')
    segments: list[ApphudSegment] = Field(default_factory=list, max_length=1, description='The API uses only the first segment for line charts; this node accepts at most one.')


class ApphudPagination(_Model):
    limit: Annotated[int, Field(strict=True, ge=1, le=2000)] = 100
    offset: Annotated[int, Field(strict=True, ge=0, le=1000000)] = 0


class ApphudSorting(_Model):
    field: Text = Field(description='Segment or a documented chart value name. The API validates chart-specific value names.')
    order: Literal['ASC', 'DESC'] = 'ASC'


class ApphudQueryColumnChartConfig(_QueryConfig):
    operation: Literal['query_column_chart'] = _op('query_column_chart', 'Query Column Chart')
    segments: list[ApphudSegment] = Field(default_factory=list, max_length=2)
    pagination: ApphudPagination = Field(default_factory=ApphudPagination, description='One page only, up to 2000 rows. No total count is documented. Fewer than the requested limit finishes paging.')
    sorting: ApphudSorting | None = None


ApphudConfig = Annotated[Union[ApphudListChartsConfig, ApphudGetChartOptionsConfig, ApphudGetFilterValuesConfig, ApphudQueryLineChartConfig, ApphudQueryColumnChartConfig], Field(discriminator='operation')]


class ApphudFullConfig(NodeConfig):
    credentials: ApphudAPIKeyCredential | None = None
    config: ApphudConfig


def _credential(raw):
    if not isinstance(raw, dict) or raw.get('credential_type') != 'apphud_s2s_api_key':
        raise ValueError('Choose the native Apphud app-level S2S method.')
    try:
        return ApphudAPIKeyCredential.model_validate(raw)
    except ValueError:
        raise ValueError('Invalid native Apphud credential or application/chart restrictions.') from None


def _pairs(raw, value='value', label='label', limit=2000):
    if not isinstance(raw, list) or len(raw) > limit:
        raise ValueError('Expected a bounded option list.')
    rows = [{value: _text(row[value]), label: _text(row[label])} for row in raw if isinstance(row, dict)]
    if len(rows) != len(raw) or len({row[value] for row in rows}) != len(rows):
        raise ValueError('Malformed or duplicate option identities.')
    return rows


def _catalog(results):
    if not isinstance(results.get('chart_groups'), list) or len(results['chart_groups']) > 100:
        raise ValueError('Expected chart_groups in the current protected catalog.')
    groups, seen = [], set()
    for group in results['chart_groups']:
        name, charts = _text(group['name']), group['charts']
        if not isinstance(charts, list) or len(charts) > 500:
            raise ValueError('Malformed chart catalog group.')
        clean = []
        for chart in charts:
            identity = _text(chart['id'], 128)
            if identity in seen or chart['type'] not in ('line', 'column', 'stackedColumn', 'columnLine') or type(chart['is_locked']) is not bool:
                raise ValueError('Malformed, duplicate or unsupported chart metadata.')
            seen.add(identity)
            additional = chart['additional']
            if not isinstance(additional, list) or len(additional) > 20:
                raise ValueError('Malformed calculation definitions.')
            definitions = []
            for item in additional:
                if type(item['required']) is not bool:
                    raise ValueError('Malformed calculation requirement.')
                values = _pairs(item['values'], 'id', 'name')
                default = item.get('default_value')
                if default is not None and default not in {value['id'] for value in values}:
                    raise ValueError('Undocumented calculation default.')
                definitions.append({'id': _text(item['id']), 'name': _text(item['name']), 'required': item['required'], 'default_value': default, 'values': values})
            if len({item['id'] for item in definitions}) != len(definitions):
                raise ValueError('Duplicate calculation identities.')
            clean.append({'id': identity, 'name': _text(chart['name']), 'type': chart['type'], 'is_locked': chart['is_locked'], 'additional': definitions})
        groups.append({'name': name, 'charts': clean})
    return {'chart_groups': groups}


def _options(results):
    segments, filters = results.get('segment_groups'), results.get('filter_groups')
    if not isinstance(segments, list) or not isinstance(filters, list) or len(segments) > 100 or len(filters) > 100:
        raise ValueError('Expected current chart segment/filter groups.')
    segment_groups, filter_groups = [], []
    for group in segments:
        if type(group['only_one']) is not bool:
            raise ValueError('Malformed segment restriction.')
        segment_groups.append({'label': _text(group['label']), 'only_one': group['only_one'], 'options': _pairs(group['options'])})
    for group in filters:
        rows = group['filters']
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError('Malformed filter definitions.')
        filter_groups.append({'name': _text(group['name']), 'filters': [{'id': _text(item['id']), 'name': _text(item['name']), 'conditions': _pairs(item['conditions']), 'values': _pairs(item['values'])} for item in rows]})
    segment_ids = [item['value'] for group in segment_groups for item in group['options']]
    filter_ids = [item['id'] for group in filter_groups for item in group['filters']]
    if len(set(segment_ids)) != len(segment_ids) or len(set(filter_ids)) != len(filter_ids):
        raise ValueError('Ambiguous current segment or filter identities.')
    additional = results.get('additional')
    if not isinstance(additional, dict) or len(additional) > 20:
        raise ValueError('Expected calculation option metadata.')
    return {'segment_groups': segment_groups, 'filter_groups': filter_groups, 'additional': {_text(key): _pairs(values) for key, values in additional.items()}}


def _values(raw):
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError('Malformed bounded metric values.')
    rows = []
    for value in raw:
        if value['type'] not in ('money', 'percent', 'simple'):
            raise ValueError('Unsupported metric type.')
        rows.append({'name': _text(value['name']), 'type': value['type'], 'value': _number(value['value'])})
    return rows


def _series(results, config):
    if config.operation == 'query_line_chart':
        lines = results.get('lines')
        if not isinstance(lines, list) or len(lines) > 2000:
            raise ValueError('Expected bounded chart lines, including an empty list.')
        rows = []
        for line in lines:
            if not isinstance(line['points'], list) or len(line['points']) > 190:
                raise ValueError('The response exceeds the documented 190-point limit.')
            points = []
            for point in line['points']:
                _timestamp(point['point'])
                if type(point['is_predict']) is not int or point['is_predict'] not in (0, 1):
                    raise ValueError('Malformed forecast indicator.')
                points.append({'point': point['point'], 'is_predict': point['is_predict'], 'values': _values(point['values'])})
            rows.append({'name': _text(line['name']), 'cnt': _integer(line['cnt'], 10**15), 'points': points})
        return {'lines': rows}
    rows = results.get('rows')
    if not isinstance(rows, list) or len(rows) > config.pagination.limit:
        raise ValueError('Column response exceeds the requested single-page bound.')
    clean = []
    for row in rows:
        if not isinstance(row['segments'], list) or len(row['segments']) > 2:
            raise ValueError('Malformed column segments.')
        segments = []
        for segment in row['segments']:
            if type(segment['in_progress']) is not bool:
                raise ValueError('Malformed period indicator.')
            segments.append({'name': _text(segment['name']), 'value': _text(segment['value']), 'in_progress': segment['in_progress']})
        clean.append({'segments': segments, 'values': _values(row['values'])})
    return {'rows': clean}


class _ProviderFailure(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__({400: 'Apphud rejected the analytics parameters.', 401: 'Apphud rejected the S2S key.', 403: 'Apphud denied application or chart/plan access.', 408: 'Apphud query timed out; narrow the range or filters.', 429: 'Apphud rate limit reached; no retry performed.'}.get(status, 'Apphud did not return a verified HTTP 200 JSON analytics response.'))


class ApphudNode(WorkflowNode):
    integration_type = NODE_TYPE
    credential_type = 'apphud_s2s_api_key'
    connection_evidence = ConnectionEvidence(noun='application analytics', operation='list_charts', proves='reachability')

    @classmethod
    def get_config_model(cls):
        return ApphudFullConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data.get('credentials'), dict):
            credential = _credential(config_data['credentials'])
            _private(credential, {key: value for key, value in config_data.items() if key != 'credentials'})
        return super().parse_config(config_data)

    @classmethod
    def _extract_actionable_validation_error(cls, error, config_data):
        return 'Choose a documented Apphud analytics operation, current allowed chart and bounded query fields.'

    @classmethod
    def validate_config(cls, config_data):
        try:
            if isinstance(config_data.get('credentials'), dict):
                credential = _credential(config_data['credentials'])
                _private(credential, {key: value for key, value in config_data.items() if key != 'credentials'})
        except ValueError:
            return ValidationResult(valid=False, errors=['Choose native Apphud app-level S2S credentials and current restrictions.'])
        return super().validate_config(config_data)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        credential = _credential(credential_data)
        await cls._dispatch(credential, ApphudListChartsConfig())
        return {'valid': True, 'proves': 'reachability'}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Static API keys need no refresh; staging owns credential admission.
        return _credential(credential_data).model_dump()

    @classmethod
    async def _wire(cls, credential, authority, route, method='GET', body=None):
        routes = {'chart/list': 'GET', 'chart/options': 'GET', 'chart/filter': 'POST', 'chart/query/line': 'POST', 'chart/query/column': 'POST'}
        if routes.get(route) != method or body is not None and 'app_id' in body:
            raise ValueError('Unsupported closed analytics route or application override.')
        params = {'app_id': credential.app_id, **(body or {})}
        _private(credential, params)
        marker = _private_http.set(True)
        try:
            with suppress_instrumentation():
                async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                    kwargs = {'params': params} if method == 'GET' else {'json': params}
                    async with client.stream(method, ROOT + '/' + route, headers={'Authorization': 'Bearer ' + credential.api_key, 'Accept': 'application/json'}, **kwargs) as response:
                        if response.status_code != 200:
                            raise _ProviderFailure(response.status_code)
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_BYTES:
                                raise ValueError('Apphud response exceeds the native byte bound.')
                            chunks.append(chunk)
                        if response.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                            raise ValueError('Expected analytics JSON, not text, media or redirects.')
                        try:
                            payload = json.loads(b''.join(chunks), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
                        except (ValueError, UnicodeError):
                            raise ValueError('Malformed Apphud JSON.') from None
            if not isinstance(payload, dict) or payload.get('errors', True) is not None or not isinstance(payload.get('data'), dict):
                raise ValueError('Apphud errors or a missing success envelope leave analytics unverified.')
            data = payload['data']
            if not isinstance(data.get('results'), dict) or 'meta' not in data or data['meta'] is not None and not isinstance(data['meta'], dict):
                raise ValueError('Expected data.results and nullable data.meta.')
            meta = None if data['meta'] is None else ({'axis_x': _text(data['meta']['axis_x'])} if 'axis_x' in data['meta'] else {})
            return data['results'], meta
        finally:
            _private_http.reset(marker)

    @classmethod
    async def _chart(cls, credential, authority, chart_id):
        if chart_id not in credential.chart_ids:
            raise ValueError('Chart is outside current explicit restrictions.')
        catalog = _catalog((await cls._wire(credential, authority, 'chart/list'))[0])
        charts = [chart for group in catalog['chart_groups'] for chart in group['charts'] if chart['id'] == chart_id]
        if len(charts) != 1 or charts[0]['is_locked']:
            raise ValueError('The current app catalog does not grant this chart.')
        return charts[0]

    @classmethod
    def _check_filters(cls, filters, options):
        definitions = [item for group in options['filter_groups'] for item in group['filters']]
        if len({item['id'] for item in definitions}) != len(definitions) or len({item.id for item in filters}) != len(filters):
            raise ValueError('Duplicate filter identities.')
        for item in filters:
            matches = [definition for definition in definitions if definition['id'] == item.id]
            if len(matches) != 1:
                raise ValueError('Filter is absent from current chart options.')
            definition = matches[0]
            conditions = {value['value'] for value in definition['conditions']}
            if item.condition is not None and item.condition not in conditions or any(value.condition not in conditions for value in item.values):
                raise ValueError('Filter condition is absent from current chart options.')
            allowed = {value['value'] for value in definition['values']}
            if allowed and any(value.value not in allowed for value in item.values):
                raise ValueError('Static filter value is absent from current chart options.')

    @classmethod
    async def _dispatch(cls, credential, config, authority=None):
        if config.operation not in credential.allowed_operations:
            raise ValueError('Operation is outside current explicit restrictions.')
        _private(credential, config.model_dump(by_alias=True))
        meta, page = None, None
        if config.operation == 'list_charts':
            raw, meta = await cls._wire(credential, authority, 'chart/list')
            results = _catalog(raw)
            for group in results['chart_groups']:
                group['charts'] = [chart for chart in group['charts'] if chart['id'] in credential.chart_ids]
        else:
            chart = await cls._chart(credential, authority, config.chart_id)
            raw, meta = await cls._wire(credential, authority, 'chart/options', body={'chart_id': config.chart_id})
            options = _options(raw)
            if config.operation == 'get_chart_options':
                results = options
            else:
                cls._check_filters(config.filters, options)
                # Enumerated comparisons use protected current app/chart values.
                # Free-form numeric representation is not specified by the guide.
                for applied in config.filters:
                    definition = next(item for group in options['filter_groups'] for item in group['filters'] if item['id'] == applied.id)
                    if not definition['values']:
                        current, _ = await cls._wire(credential, authority, 'chart/filter', 'POST', {'chart_id': config.chart_id, 'filter_id': applied.id, 'filters': []})
                        if current.get('id') != applied.id or current.get('input_type') not in ('text', 'number'):
                            raise ValueError('Applied filter values have an unverified parent or input type.')
                        values = _pairs(current['values'])
                        if values and any(value.value not in {row['value'] for row in values} for value in applied.values):
                            raise ValueError('Applied filter value is absent from protected discovery.')
                        if not values and current['input_type'] != 'text':
                            raise ValueError('Free-form numeric filter representation remains undocumented.')
                body = config.model_dump(by_alias=True, exclude_none=True)
                body.pop('operation')
                if 'segments' in body and not body['segments']:
                    # Omission has documented defaults: aggregate line or the
                    # chart's first available column segment. Empty is unknown.
                    body.pop('segments')
                if config.operation == 'get_filter_values':
                    definitions = [item['id'] for group in options['filter_groups'] for item in group['filters']]
                    if config.filter_id not in definitions:
                        raise ValueError('Requested filter is absent from this current chart.')
                    raw, meta = await cls._wire(credential, authority, 'chart/filter', 'POST', body)
                    if raw.get('id') != config.filter_id or raw.get('input_type') not in ('text', 'number'):
                        raise ValueError('Returned filter identity or input type differs.')
                    results = {'id': config.filter_id, 'values': _pairs(raw['values']), 'input_type': raw['input_type']}
                else:
                    line = config.operation == 'query_line_chart'
                    if line != (chart['type'] == 'line'):
                        raise ValueError('Use the query endpoint documented for this current chart type.')
                    definitions = {item['id']: item for item in chart['additional']}
                    if set(config.additional) - set(definitions) or any(item['required'] and key not in config.additional for key, item in definitions.items()):
                        raise ValueError('Supply only current calculation keys and all required string values.')
                    for key, value in config.additional.items():
                        if value not in {row['id'] for row in definitions[key]['values']}:
                            raise ValueError('Calculation value is absent from the current chart catalog.')
                    segment_ids = [segment.id for segment in config.segments]
                    groups = options['segment_groups']
                    if len(set(segment_ids)) != len(segment_ids) or any(identity not in {row['value'] for group in groups for row in group['options']} for identity in segment_ids):
                        raise ValueError('Segment is absent from current chart options.')
                    if any(group['only_one'] and len(set(segment_ids) & {row['value'] for row in group['options']}) > 1 for group in groups):
                        raise ValueError('This current segment group permits only one selection.')
                    view_by = config.additional.get('view_by')
                    if line and view_by and view_by.isdecimal() and int(view_by) > 0:
                        duration = (_timestamp(config.time_range.to) - _timestamp(config.time_range.from_time)).total_seconds()
                        if math.ceil(duration / int(view_by)) > 190:
                            raise ValueError('The requested range exceeds 190 estimated line buckets.')
                    raw, meta = await cls._wire(credential, authority, 'chart/query/line' if line else 'chart/query/column', 'POST', body)
                    results = _series(raw, config)
                    if not line:
                        page = {'offset': config.pagination.offset, 'limit': config.pagination.limit, 'next_offset': config.pagination.offset + len(results['rows']) if len(results['rows']) == config.pagination.limit else None, 'total_count': None, 'automatic_paging_performed': False}
        result = {'status': 'success', 'action': config.operation, 'data': {'results': results, 'meta': meta}, 'errors': None, 'configured_app_id': credential.app_id, 'configured_app_reachability_verified': True, 'provider_account_identity_verified': False, 'local_scope_auto_extended': False, 'expert_plus_entitlement_inferred': False, 'read_semantic_post': config.operation in ('get_filter_values', 'query_line_chart', 'query_column_chart')}
        if page is not None:
            result['pagination'] = page
        _private(credential, result)
        return result

    async def execute(self, inputs):
        try:
            if not isinstance(self.config, ApphudFullConfig) or self.config.credentials is None:
                raise ValueError('Native Apphud credential and config required.')
            credential = self.config.credentials
            return await self._dispatch(credential, self.config.config)
        except _ProviderFailure as exc:
            return {'status': 'error', 'error': str(exc), 'http_status': exc.status, 'automatic_retry_performed': False}
        except Exception as exc:
            return {'status': 'error', 'error': 'Apphud current application or analytics access remains unverified; check native credentials, restrictions and documented response shapes.', 'error_type': type(exc).__name__, 'automatic_retry_performed': False}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None, limit=None):
        credential = _credential(credential_data)
        authority = None
        context = context or {}
        allowed = {'operation', 'chart_id', 'filter_id', 'chart_id__label', 'filter_id__label', '_user_id', 'filters', 'time_range', 'additional', 'segments', 'pagination', 'sorting'}
        if field_name not in ('chart_id', 'filter_id') or page_token is not None or limit is not None and (type(limit) is not int or not 1 <= limit <= 100):
            raise ValueError('Unsupported analytics selector or cursor.')
        if not isinstance(context, dict) or set(context) - allowed or context.get('operation') not in (None, *OPERATIONS):
            raise ValueError('Selector context cannot override current credential/application authority.')
        if context.get('operation') is not None and context['operation'] not in credential.allowed_operations:
            raise ValueError('Selector operation is outside current explicit restrictions.')
        _private(credential, {key: value for key, value in context.items() if key != '_user_id'})
        if context.get('chart_id') not in (None, '') and context['chart_id'] not in credential.chart_ids:
            raise ValueError('Selector chart is outside current explicit restrictions.')
        if search:
            _text(search, 100)
            _private(credential, search)
        if field_name == 'chart_id':
            raw = _catalog((await cls._wire(credential, authority, 'chart/list'))[0])
            rows = [{'value': item['id'], 'label': item['name'], 'metadata': {'chart_type': item['type'], 'is_locked': item['is_locked'], 'proves': 'reachability'}} for group in raw['chart_groups'] for item in group['charts'] if item['id'] in credential.chart_ids and not item['is_locked']]
        else:
            chart_id = context.get('chart_id')
            if not chart_id:
                raise ValueError('Select the explicitly allowed parent chart first.')
            await cls._chart(credential, authority, chart_id)
            raw = _options((await cls._wire(credential, authority, 'chart/options', body={'chart_id': chart_id}))[0])
            rows = [{'value': item['id'], 'label': item['name'], 'metadata': {'chart_id': chart_id, 'proves': 'reachability'}} for group in raw['filter_groups'] for item in group['filters']]
            if context.get('filter_id') not in (None, '') and context['filter_id'] not in {row['value'] for row in rows}:
                raise ValueError('Selector filter differs from current parent chart options.')
        if search:
            rows = [row for row in rows if search.casefold() in row['label'].casefold()]
        _private(credential, rows)
        # Native discovery is bounded, not a provider cursor. No full-catalog claim.
        return {'options': rows[:limit or 100], 'next_page_token': None, 'metadata': {'truncated': len(rows) > (limit or 100), 'provider_account_identity_verified': False}}
