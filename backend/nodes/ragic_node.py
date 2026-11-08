"""Native Ragic date-versioned sheet reads with explicit numeric projections.

The documented header is Basic followed by the RAW API key. No base64 recipe,
query key, password session, arbitrary route, write or account identity exists.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import SSRFError, guarded_async_client

FAMILY = 'ragic_api_key'
VERSION = '2025-01-01'
Server = Literal['www.ragic.com','na3.ragic.com','ap5.ragic.com','eu2.ragic.com','ap8.ragic.com']
FieldId = Annotated[int, Field(strict=True,ge=1,le=9_007_199_254_740_991)]
UNKNOWN = 'No paired record/field witness supplied. Resource reachability, key validity and private-sheet permissions remain unknown.'


class RagicError(ValueError):
    def __init__(self,message,status_code=None):super().__init__(message);self.status_code=status_code


def text(value,maximum=4096,empty=False):
    if not isinstance(value,str) or (not empty and not value) or len(value)>maximum or value!=value.strip() or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError('Enter bounded text without controls or edge whitespace')
    return value


def segment(value):
    value=text(value,128)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*',value):raise ValueError('Enter one account or folder component, not a URL or path')
    return value


def record_id(value):
    if type(value) is int and value>=0:value=str(value)
    value=text(value,19)
    if not re.fullmatch(r'0|[1-9][0-9]*',value):raise ValueError('Enter a canonical nonnegative record ID')
    return value


def guard(data,stored=False):
    if not isinstance(data,dict) or ((stored or 'credential_type' in data) and data.get('credential_type')!=FAMILY):
        raise ValueError('Select a native Ragic API Key')


class RagicAPIKeyCredential(BaseModel):
    model_config=ConfigDict(title='Ragic API Key',extra='ignore',hide_input_in_errors=True,json_schema_extra={
        'x-credential-url':'https://www.ragic.com/intl/en/doc-http-api',
        'x-credential-instructions':'Paste the issued RAW API key, without Basic or base64 conversion. Select the exact documented regional server and supplied account/folder/sheet. Optional paired record and nonsensitive field IDs permit a protected scoped read. It proves resource reachability only, not principal/key validity/private-sheet access; without them no probe occurs. No login, query key, token mint or writes.'})
    credential_type: Literal['ragic_api_key'] = Field(FAMILY,json_schema_extra={'ui:hidden':True})
    api_key: str = Field(...,title='Raw API Key',json_schema_extra={'ui:widget':'password'})
    server: Server = Field(...,title='Ragic Server')
    account: str = Field(...,title='Account Component')
    folder: str = Field(...,title='Folder Component',description='One folder component from the existing sheet URL, without slash.')
    sheet_index: int = Field(...,ge=0,le=2_147_483_647,strict=True)
    witness_record_id: str|None = Field(None,title='Existing Witness Record ID')
    witness_field_id: FieldId|None = Field(None,title='Nonsensitive Witness Field ID',description='Paired with the record ID; fetch only this numeric field and discard its value.')

    @field_validator('api_key',mode='before')
    @classmethod
    def validate_api_key(cls,value):
        value=text(value,16384)
        if not value.isascii() or any(c.isspace() for c in value) or '://' in value or value.startswith(('Basic','Bearer')):raise ValueError('Paste the issued RAW API key without an authorization prefix')
        return value
    @field_validator('account','folder',mode='before')
    @classmethod
    def validate_components(cls,value):return segment(value)
    @field_validator('witness_record_id',mode='before')
    @classmethod
    def validate_record_witness(cls,value):return record_id(value) if value is not None else None
    @model_validator(mode='after')
    def validate_paired_witness(self):
        if (self.witness_record_id is None)!=(self.witness_field_id is None):raise ValueError('Supply both witness IDs or leave both absent')
        return self


def credential(data):
    guard(data)
    try:return RagicAPIKeyCredential.model_validate(data).model_dump(mode='json')
    except Exception:raise ValueError('Check the native API key, regional sheet scope and paired witness IDs') from None


class Config(BaseModel):model_config=ConfigDict(extra='forbid',hide_input_in_errors=True)
class CheckConnection(Config):operation: Literal['check_connection'] = Field('check_connection')


class Projection(Config):
    field_ids: list[FieldId] = Field(...,min_length=1,max_length=50,description='Only these numeric fields are requested and projected. Exclude signatures, files, credentials and sensitive fields.')
    confirm_safe_fields: Literal[True] = Field(...,description='Confirm the selected numeric field IDs contain nonsensitive scalar workflow data; no signatures/files/secrets/contact data.')
    @field_validator('field_ids')
    @classmethod
    def validate_unique_fields(cls,value):
        if len(value)!=len(set(value)):raise ValueError('Select each numeric field ID once')
        return value
    @field_validator('confirm_safe_fields',mode='before')
    @classmethod
    def validate_projection_confirmation(cls,value):
        if value is not True:raise ValueError('Confirm the chosen field projection is safe')
        return value


class Page(Projection):
    limit: int = Field(50,ge=1,le=1000,strict=True)
    max_pages: int = Field(10,ge=1,le=100,strict=True,description='Local continuation cap; one page per invocation, no automatic reads.')
    page_token: str|None = Field(None,max_length=8000,description='Native HMAC-bound offset continuation; never a raw offset or URL.')


class ListRecords(Page):operation: Literal['list_records'] = Field('list_records')
class GetRecord(Projection):
    operation: Literal['get_record'] = Field('get_record')
    record_id: str = Field(...,json_schema_extra={'x-resource-type':'ragic_record','x-dynamic-options':{'field_name':'record_id','depends_on':'field_ids','searchable':True,'allow_custom':True}})
    @field_validator('record_id',mode='before')
    @classmethod
    def validate_record_identity(cls,value):return record_id(value)


class Condition(Config):
    field_id: FieldId
    operator: Literal['eq','gte','lte','gt','lt','like','eqeq']
    value: str = Field(...,max_length=256,description='Empty value is supported. Native encoding preserves literal commas/percent sequences. Date filters use yyyy/MM/dd or yyyy/MM/dd HH:mm:ss.')
    @field_validator('value',mode='before')
    @classmethod
    def validate_condition_value(cls,value):return text(value,256,empty=True)


class SearchRecords(Page):
    operation: Literal['search_records'] = Field('search_records')
    full_text: str|None = Field(None,min_length=1,max_length=256,description='Documented fts search; no SQL or arbitrary query parameters.')
    conditions: list[Condition] = Field(default_factory=list,max_length=10,description='Repeated where filters; same-field eq/like act as OR, range comparisons as AND. Regex is omitted.')
    @field_validator('full_text',mode='before')
    @classmethod
    def validate_fts(cls,value):return text(value,256) if value is not None else None
    @model_validator(mode='after')
    def validate_search_scope(self):
        if not self.full_text and not self.conditions:raise ValueError('Supply full-text search or typed filter conditions')
        if any(c.field_id not in self.field_ids for c in self.conditions):raise ValueError('Filter only explicitly selected numeric fields')
        return self


RagicConfig=Annotated[Union[CheckConnection,ListRecords,GetRecord,SearchRecords],Field(discriminator='operation')]
class RagicNodeConfig(NodeConfig[RagicConfig,RagicAPIKeyCredential]):pass


def sheet_path(data):return '/'+data['account']+'/'+data['folder']+'/'+str(data['sheet_index'])


async def request(data,field_ids,identity=None,extra=()):
    guard(data,stored=True)
    route=sheet_path(data)+(('/'+identity) if identity is not None else '')
    params=[('api',''),('version',VERSION),('naming','EID'),('subtables','0'),*[('fetchDomainIds',str(v)) for v in field_ids],*extra]
    if data['api_key'] in route or data['api_key'] in json.dumps(params):raise RagicError('Resource inputs contain protected credential data')
    try:
        async with guarded_async_client(trust_env=False,follow_redirects=False,timeout=30) as client:
            response=await client.get('https://'+data['server']+route,headers={'Authorization':'Basic '+data['api_key'],'Accept':'application/json'},params=params)
    except (SSRFError,httpx.RequestError):raise RagicError('Ragic could not be reached; resource access remains unknown') from None
    guard(data,stored=True)
    if response.status_code!=200:raise RagicError(f'Ragic HTTP {response.status_code}: resource request was not accepted',response.status_code)
    if len(response.content)>2_000_000 or response.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json':raise RagicError('Provider returned oversized or non-JSON data')
    try:raw=response.json()
    except ValueError:raise RagicError('Provider returned unreadable JSON') from None
    if not isinstance(raw,dict) or any(k in raw for k in ('status','error','errors','taskId')):raise RagicError('Provider returned an unsuccessful or unsupported record envelope')
    return raw


def safe_cell(value,data):
    if value is None or type(value) is bool or type(value) is int:return value,False
    if type(value) is float:return (value,False) if math.isfinite(value) else (None,True)
    if isinstance(value,str) and len(value)<=4096 and data['api_key'] not in value and not any(ord(c)<32 and c not in '\n\t' for c in value) and not re.search(r'(?i)(?:[a-z][a-z0-9+.-]*://|(?:data|javascript|file):|www\.|<[^>]*>|(?:^|\s)//|/sims/|signature|apiKey=|sid=)',value):return value,False
    if isinstance(value,list) and len(value)<=100:
        projected=[safe_cell(v,data) for v in value if not isinstance(v,(dict,list))]
        if len(projected)==len(value) and not any(hidden for _,hidden in projected):return [v for v,_ in projected],False
    return None,True


def project(raw,field_ids,data,identity=None):
    items=[]
    for key,row in raw.items():
        if not isinstance(key,str) or record_id(key)!=key or not isinstance(row,dict) or type(row.get('_ragicId')) is not int or row['_ragicId']!=int(key):raise RagicError('Provider returned an unreadable keyed record identity')
        fields={};redacted=[]
        for field in field_ids:
            name=str(field)
            if name in row:
                fields[name],hidden=safe_cell(row[name],data)
                if hidden:redacted.append(field)
        items.append({'id':key,'fields':fields,'redacted_field_ids':redacted})
    if identity is not None and (len(items)!=1 or items[0]['id']!=identity):raise RagicError('Provider returned a different requested record')
    return items


def page_scope(data,config):
    return hashlib.sha256(json.dumps([config.model_dump(mode='json',exclude={'page_token'}),dict(data)],sort_keys=True,default=str).encode()).hexdigest()


def sign(data,cursor):return hmac.new(data['api_key'].encode('ascii'),json.dumps(cursor,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()


async def page(data,config):
    scope=page_scope(data,config);offset=0;ordinal=1;prior=None
    if config.page_token:
        try:
            cursor=json.loads(base64.urlsafe_b64decode(config.page_token.encode('ascii')))
            if not isinstance(cursor,dict) or set(cursor)!={'scope','offset','page','prior','sig'}:raise ValueError()
            sig=cursor.pop('sig')
            if not isinstance(sig,str) or not hmac.compare_digest(sig,sign(data,cursor)) or cursor['scope']!=scope or type(cursor['page']) is not int or not 2<=cursor['page']<=config.max_pages or type(cursor['offset']) is not int or cursor['offset']!=(cursor['page']-1)*config.limit or not re.fullmatch(r'[0-9a-f]{64}',cursor['prior']):raise ValueError()
            offset,ordinal,prior=cursor['offset'],cursor['page'],cursor['prior']
        except Exception:raise RagicError('Continuation belongs to a different key, sheet, projection, search or limit') from None
    extra=[('limit',str(config.limit)),('offset',str(offset))]
    if isinstance(config,SearchRecords):
        if config.full_text:extra.append(('fts',config.full_text))
        extra.extend(('where',str(c.field_id)+','+c.operator+','+quote(c.value,safe='')) for c in config.conditions)
    items=project(await request(data,config.field_ids,extra=extra),config.field_ids,data)
    if len(items)>config.limit:raise RagicError('Provider exceeded the requested record bound')
    fingerprint=hashlib.sha256(json.dumps([r['id'] for r in items]).encode()).hexdigest()
    if prior==fingerprint and items:raise RagicError('Provider repeated the previous offset page')
    full=len(items)==config.limit;truncated=full and ordinal>=config.max_pages;token=None
    if full and not truncated:
        cursor={'scope':scope,'offset':offset+config.limit,'page':ordinal+1,'prior':fingerprint};cursor['sig']=sign(data,cursor)
        token=base64.urlsafe_b64encode(json.dumps(cursor,separators=(',',':')).encode()).decode()
    return {'items':items,'requested_offset':offset,'requested_page':ordinal,'has_more':None,'may_have_more':full,'next_page_token':token,'truncated':truncated,'stop_reason':'local_page_cap' if truncated else 'short_page' if not full else None,'snapshot_consistency':'unverified'}


class RagicNode(WorkflowNode):
    integration_type = "automation-ragic"
    connection_evidence=ConnectionEvidence(operation='check_connection',noun='supplied record reachability',proves='reachability')
    edit_examples=['Read selected sheet fields','Search records by numeric field conditions','Read an existing record by its native ID']
    @classmethod
    def get_config_model(cls):return RagicNodeConfig
    @classmethod
    def parse_config(cls,config_data):
        try:
            if isinstance(config_data,dict) and config_data.get('credentials') is not None:guard(config_data['credentials'])
        except ValueError:raise ConfigValidationError('Select a native Ragic API Key') from None
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls,config_data):
        try:
            if isinstance(config_data,dict) and config_data.get('credentials') is not None:guard(config_data['credentials'])
        except ValueError:return {'valid':False,'errors':['Select a native Ragic API Key'],'satisfied_set':None}
        return super().validate_config(config_data)
    @classmethod
    def _extract_actionable_validation_error(cls,error,config_data):return 'Check the native API key, regional sheet scope, field projection and confirmation'
    @classmethod
    async def validate_credential_access(cls, data):
        try:
            data = credential(data)
            identity = data.get('witness_record_id')
            if identity is None:
                return {'valid': None, 'hint': UNKNOWN}
            project(await request(data, [data['witness_field_id']], identity),
                    [data['witness_field_id']], data, identity)
            return {'valid': True, 'hint': 'Supplied record reachable; key validity, principal and private-sheet access remain unknown.'}
        except (ValueError, TypeError, KeyError):
            return {'valid': False, 'error': 'Ragic credential or witness record could not be validated'}

    async def execute(self,inputs):
        if not self.config or not self.config.credentials:raise ValueError('Connect a native Ragic API Key')
        config=self.config.config
        try:
            data=credential(self.config.credentials.model_dump(mode='json'))
            if isinstance(config,CheckConnection):
                identity=data.get('witness_record_id')
                if identity is None:raise RagicError(UNKNOWN)
                project(await request(data,[data['witness_field_id']],identity),[data['witness_field_id']],data,identity)
                return {'status':'success','data':{'items':[],'identity_verified':False,'key_validity':'unknown','private_sheet_access':'unknown'},'verification':{'reachable':True,'proves':'reachability','account_label':None}}
            if isinstance(config,GetRecord):result=project(await request(data,config.field_ids,config.record_id),config.field_ids,data,config.record_id)[0]
            else:result=await page(data,config)
            return {'status':'success','action':config.operation,'data':result}
        except RagicError as exc:return {'status':'error','action':config.operation,'error':str(exc),'status_code':exc.status_code}
        except (ValueError,TypeError,KeyError):return {'status':'error','action':config.operation,'error':'Credential or projected record data could not be validated'}
    @classmethod
    async def load_field_options(cls,field_name,credential_data,context=None,page_token=None,search=None):
        if field_name!='record_id':return []
        if page_token:raise RagicError('Picker uses a complete bounded page; use list/search for continuation')
        credential_data=credential(credential_data)
        selected=context if isinstance(context,dict) else {}
        try:config=ListRecords(field_ids=selected.get('field_ids'),confirm_safe_fields=selected.get('confirm_safe_fields'),limit=1000,max_pages=1)
        except Exception:raise RagicError('Choose a confirmed safe numeric field projection before loading records') from None
        if search is not None:search=text(search,128)
        result=await page(credential_data,config)
        if result['may_have_more']:raise RagicError('Record picker may be incomplete; enter a record ID or use the paginated list')
        # Labels are native IDs only; no private field values become dropdown labels.
        return [{'label':row['id'],'value':row['id']} for row in result['items'] if search is None or search in row['id']]
