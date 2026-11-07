"""Company-only People Data Labs enrichment and one-page search workflows.

Explicit runs can consume provider credits. Connection checks use the free Company Cleaner API without issuing a paid
enrichment/search request or claiming account identity or company entitlement.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback
from utils.ssrf import SSRFError, guarded_async_client

API = "https://api.peopledatalabs.com/v5"
FAMILY = "people_data_labs_api_key"
UNVERIFIED = "Company Cleaner accepted the API key. Company enrichment/search access and credits remain unverified."
FieldName = Literal["name", "display_name", "website", "industry", "size", "type", "ticker", "founded", "employee_count", "linkedin_url", "linkedin_slug", "location.country", "location.region", "location.locality", "location.metro", "tags"]
FilterField = Literal["id", "name", "website", "industry", "size", "type", "ticker", "founded", "employee_count", "linkedin_slug", "location.country", "location.region", "location.locality", "location.metro", "tags"]
Scalar = Union[StrictStr, StrictInt, StrictFloat, StrictBool]
MATCH_FIELDS = ("pdl_id", "name", "ticker", "website", "profile", "locality", "region", "country")


class PDLError(ValueError):
    def __init__(self, message, status_code=None, kind=None):
        super().__init__(message)
        self.status_code, self.kind = status_code, kind


def text(value, maximum=4096):
    if not isinstance(value, str) or not value or len(value)>maximum or value!=value.strip() or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError("Enter bounded text without edge whitespace or control characters")
    return value


def guard(data, stored=False):
    if not isinstance(data, dict) or ((stored or "credential_type" in data) and data.get("credential_type")!=FAMILY):
        raise ValueError("Select a native People Data Labs API key")


class PeopleDataLabsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="People Data Labs API Key", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.peopledatalabs.com/docs/authentication",
        "x-credential-instructions": "Paste an issued API key without a header prefix. It is sent only in X-Api-Key. Saving checks the key with the free Company Cleaner API. Enrichment/search access and credits remain unverified until an explicit operation. No account identity or token mint is inferred."})
    credential_type: Literal["people_data_labs_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key(cls, value):
        value=text(value,16384)
        if not value.isascii() or any(c.isspace() for c in value) or "://" in value:
            raise ValueError("Paste the issued key without a prefix or URL")
        return value


def credential(data):
    guard(data)
    try:return PeopleDataLabsAPIKeyCredential.model_validate(data).model_dump(mode="json")
    except Exception:raise ValueError("Check the native People Data Labs API key") from None


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class CheckConnection(Config):
    operation: Literal["check_connection"] = Field("check_connection", description="Checks API-key reachability with the free Company Cleaner API; does not verify enrichment/search access or credits.")


class CreditRead(Config):
    confirm_credit_use: Literal[True] = Field(..., description="This explicit request can consume People Data Labs company credits. Search charges per returned record; no automatic paging or retry occurs.")
    fields: list[FieldName] = Field(default_factory=lambda:["name","website","industry","size","employee_count","location.country"], min_length=1, max_length=16, description="Native output allowlist. Search's SQL projection is ignored by the vendor; unselected fields are removed locally.")

    @field_validator("confirm_credit_use",mode="before")
    @classmethod
    def validate_credit_confirmation(cls,value):
        if value is not True:raise ValueError("Confirm the provider credit use")
        return value

    @field_validator("fields")
    @classmethod
    def validate_unique_fields(cls,value):
        if len(set(value))!=len(value):raise ValueError("Choose each company field once")
        return value


class EnrichCompany(CreditRead):
    operation: Literal["enrich_company"] = Field("enrich_company")
    pdl_id: str|None = Field(None, title="Company PDL ID or LinkedIn Slug", json_schema_extra={"x-resource-type":"people_data_labs_company"}, description="Takes precedence over all other match inputs. No paid picker request is sent.")
    name: str|None = None
    ticker: str|None = None
    website: str|None = None
    profile: str|None = None
    locality: str|None = None
    region: str|None = None
    country: str|None = None
    min_likelihood: int = Field(6, ge=1, le=10, strict=True, description="Native default 6; vendor default is 2. A score is confidence, not an exact identity guarantee.")
    include_if_matched: bool = Field(True, strict=True)

    @field_validator(*MATCH_FIELDS,mode="before")
    @classmethod
    def validate_match_text(cls,value):return text(value,1024) if value is not None else None

    @model_validator(mode="after")
    def validate_required_company_input(self):
        if not any(getattr(self,k) for k in MATCH_FIELDS[:5]):raise ValueError("Set company PDL ID, name, ticker, website or profile")
        return self


class RangeBounds(Config):
    gt: StrictInt|StrictFloat|None = None
    gte: StrictInt|StrictFloat|None = None
    lt: StrictInt|StrictFloat|None = None
    lte: StrictInt|StrictFloat|None = None
    @model_validator(mode="after")
    def validate_range_bounds(self):
        if not self.model_dump(exclude_none=True):raise ValueError("Set at least one numeric range bound")
        return self


class ExistsClause(Config):
    field: FilterField


class CompanyClause(Config):
    term: dict[FilterField, Scalar]|None = Field(None, min_length=1, max_length=1)
    terms: dict[FilterField, list[Scalar]]|None = Field(None, min_length=1, max_length=1)
    exists: ExistsClause|None = None
    bool_query: BoolClause|None = Field(None, alias="bool")
    match: dict[FilterField, StrictStr]|None = Field(None, min_length=1, max_length=1)
    range: dict[Literal["employee_count","founded"], RangeBounds]|None = Field(None, min_length=1, max_length=1)
    match_phrase: dict[FilterField, StrictStr]|None = Field(None, min_length=1, max_length=1)
    wildcard: dict[FilterField, StrictStr]|None = Field(None, min_length=1, max_length=1)
    prefix: dict[FilterField, StrictStr]|None = Field(None, min_length=1, max_length=1)
    match_all: dict[str, str]|None = Field(None, max_length=0)
    @model_validator(mode="after")
    def validate_single_query_type(self):
        if sum(v is not None for v in self.model_dump().values())!=1:raise ValueError("Each company query clause needs exactly one supported query type")
        return self


class BoolClause(Config):
    must: list[CompanyClause]|None = Field(None, min_length=1, max_length=100)
    must_not: list[CompanyClause]|None = Field(None, min_length=1, max_length=100)
    filter: list[CompanyClause]|None = Field(None, min_length=1, max_length=100)
    should: list[CompanyClause]|None = Field(None, min_length=1, max_length=100)
    @model_validator(mode="after")
    def validate_nonempty_bool(self):
        if not self.model_dump(exclude_none=True):raise ValueError("Set at least one boolean company clause")
        return self


CompanyClause.model_rebuild()


class CompanyQuery(Config):
    query: CompanyClause
    @model_validator(mode="after")
    def validate_query_bounds(self):
        def visit(value,depth=0):
            if depth>20:raise ValueError("Company query nesting exceeds the native bound")
            if isinstance(value,dict):
                for v in value.values():visit(v,depth+1)
            elif isinstance(value,list):
                if not 1<=len(value)<=100:raise ValueError("Query arrays must have 1 to 100 elements")
                for v in value:visit(v,depth+1)
            elif isinstance(value,str):text(value,1024)
            elif type(value) is float and not math.isfinite(value):raise ValueError("Query numeric values must be finite")
        raw=self.model_dump(mode="json",by_alias=True,exclude_none=True);visit(raw)
        if len(json.dumps(raw))>30000:raise ValueError("Company query exceeds the native size bound")
        return self


class SearchCompanies(CreditRead):
    operation: Literal["search_companies"] = Field("search_companies")
    query: CompanyQuery|None = None
    sql: str|None = Field(None, description="SELECT * FROM company WHERE ... only. Vendor ignores projection and LIMIT; use Size and native fields. No legacy from, joins, aggregations or extra statements.")
    size: int = Field(10, ge=1, le=100, strict=True)
    max_pages: int = Field(10, ge=1, le=100, strict=True, description="Native continuation cap; each run still requests exactly one page. This is not a vendor total-result limit.")
    page_token: str|None = Field(None,max_length=16000,description="Native bound continuation from this exact query/key/size/fields; raw vendor scroll tokens are not accepted.")
    @field_validator("sql",mode="before")
    @classmethod
    def validate_company_sql(cls,value):
        if value is None:return None
        value=text(value,10000)
        if not re.match(r"(?is)^SELECT\s+\*\s+FROM\s+company\s+WHERE\s+\S",value):raise ValueError("Use SELECT * FROM company WHERE followed by a company filter")
        # Inspect SQL syntax outside escaped single-quoted values, not their content.
        syntax=re.sub(r"'(?:''|[^'])*'","''",value)
        if syntax.count("'")%2 or ";" in syntax or "--" in syntax or "/*" in syntax or re.search(r"(?i)\b(SELECT|LIMIT|OFFSET|UNION|JOIN|INSERT|UPDATE|DELETE|DROP|INTO|FROM)\b",syntax.split('WHERE',1)[-1] if 'WHERE' in syntax else re.split(r'(?i)\bWHERE\b',syntax,maxsplit=1)[-1]):
            raise ValueError("Use one company filter without LIMIT, offsets, joins or additional statements")
        return value
    @model_validator(mode="after")
    def validate_exactly_one_search(self):
        if (self.query is None)==(self.sql is None):raise ValueError("Set exactly one typed company query or company SQL")
        return self


PeopleDataLabsConfig=Annotated[Union[CheckConnection,EnrichCompany,SearchCompanies],Field(discriminator="operation")]
class PeopleDataLabsNodeConfig(NodeConfig[PeopleDataLabsConfig,PeopleDataLabsAPIKeyCredential]):pass


async def freshen(data, **kwargs):
    """Reload saved API keys through staging's shared owner-fallback loader."""
    if kwargs.get("credential_id"):
        if not kwargs.get("user_id"):
            raise PDLError("Current saved-key access requires an authenticated actor")
        data = await resolve_credential_with_owner_fallback(
            kwargs["credential_id"], kwargs["user_id"], kwargs.get("pool"),
            org_id=kwargs.get("organization_id"), workflow_id=kwargs.get("workflow_id"),
        )
        if not data:
            raise PDLError("The saved People Data Labs key is unavailable")
        guard(data, stored=True)
    return credential(data)


def safe(value,data,maximum=4096):
    if not isinstance(value,str) or len(value)>maximum or any(ord(c)<32 or ord(c)==127 for c in value) or data["api_key"] in value:raise PDLError("Provider returned unreadable or protected company metadata")
    return value


def company(raw,fields,data):
    if not isinstance(raw,dict):raise PDLError("Provider returned unreadable company metadata")
    identity=safe(raw.get("id"),data,128)
    if not re.fullmatch(r"[A-Za-z0-9_-]+",identity):raise PDLError("Provider returned unreadable company identity")
    out={"id":identity}
    for field in fields:
        parent,sep,child=field.partition('.');value=raw.get(parent)
        if sep:
            if value is None:value=None
            elif not isinstance(value,dict):raise PDLError("Provider returned unreadable company location")
            else:value=value.get(child)
        if field not in raw and not sep:continue
        if value is None:out[field]=None
        elif field in {"founded","employee_count"}:
            if type(value) is not int or value<0 or field=="founded" and value>9999:raise PDLError("Provider returned unreadable company counts")
            out[field]=value
        elif field=="tags":
            if not isinstance(value,list) or len(value)>100:raise PDLError("Provider returned unreadable company tags")
            out[field]=[safe(v,data,1024) for v in value]
        else:
            value=safe(value,data)
            if field in {"website","linkedin_url"}:
                parsed=urlsplit(value if '://' in value else 'https://'+value)
                if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise PDLError("Provider returned unsupported company URL metadata")
            out[field]=value
    return out


async def request(data,route,params):
    guard(data, stored=True)
    if data['api_key'] in json.dumps(params):raise PDLError("A company input contains protected credential data")
    try:
        async with guarded_async_client(trust_env=False,follow_redirects=False,timeout=30) as client:
            response=await client.get(API+'/'+route,headers={"X-Api-Key":data['api_key'],"Accept":"application/json","Content-Type":"application/json"},params=params)
    except (SSRFError,httpx.RequestError):raise PDLError("Company API request could not be reached; acceptance is unverified") from None
    if response.status_code not in {200,404}:raise PDLError(f"Company API HTTP {response.status_code}: request not accepted",response.status_code,{400:'invalid_request',401:'authentication',402:'credits_exhausted',405:'method',429:'rate_limit'}.get(response.status_code,'provider_failure'))
    if len(response.content)>2_000_000 or response.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json':raise PDLError("Provider returned oversized or non-JSON company metadata")
    try:raw=response.json()
    except ValueError:raise PDLError("Provider returned unreadable company JSON") from None
    if not isinstance(raw,dict) or type(raw.get('status')) is not int or raw['status']!=response.status_code:raise PDLError("Provider returned inconsistent company response status")
    if response.status_code==404:
        if not isinstance(raw.get('error'),dict) or raw['error'].get('type')!='not_found' or raw.get('data') or 'id' in raw:raise PDLError("Provider returned an unverified no-match response",404)
        return None
    if 'error' in raw or 'errors' in raw:raise PDLError("Provider returned an unsuccessful company response")
    return raw


async def check_connection(data):
    # PDL's own quickstart example; Cleaner is free and requires an active key:
    # https://docs.peopledatalabs.com/docs/quickstart-cleaner-apis
    # https://docs.peopledatalabs.com/docs/cleaner-apis-reference
    raw = await request(data, 'company/clean', {'website': 'peopledatalabs.com'})
    if raw is None:
        raise PDLError("Company Cleaner could not verify the API key")
    # Parse the documented company shape, but never present this public record
    # as account identity or evidence of paid company enrichment/search access.
    company(raw, ['name', 'website'], data)
    return {'proof': UNVERIFIED}


def continuation_scope(data,config):
    body=config.model_dump(mode='json',by_alias=True,exclude_none=True,exclude={'page_token','confirm_credit_use'})
    return hashlib.sha256(json.dumps([body,data['api_key']],sort_keys=True).encode()).hexdigest()


def continuation_signature(data,token):
    message=json.dumps(token,sort_keys=True,separators=(',',':')).encode()
    return hmac.new(data['api_key'].encode('ascii'),message,hashlib.sha256).hexdigest()


class PeopleDataLabsNode(WorkflowNode):
    integration_type = "automation-people-data-labs"
    connection_evidence=ConnectionEvidence(operation="check_connection",noun="company API access",proves="reachability")
    edit_examples=["Enrich company by website","Search company firmographics","Check API key using the free Company Cleaner"]
    @classmethod
    def get_config_model(cls):return PeopleDataLabsNodeConfig
    @classmethod
    def parse_config(cls,config_data):
        try:
            if isinstance(config_data,dict) and config_data.get('credentials') is not None:guard(config_data['credentials'])
        except ValueError:raise ConfigValidationError("Select a native People Data Labs API key") from None
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls,config_data):
        try:
            if isinstance(config_data,dict) and config_data.get('credentials') is not None:guard(config_data['credentials'])
        except ValueError:return {'valid':False,'errors':['Select a native People Data Labs API key'],'satisfied_set':None}
        return super().validate_config(config_data)
    @classmethod
    def _extract_actionable_validation_error(cls,error,config_data):return "Check the native company query, key and explicit credit confirmation"
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await freshen(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
    @classmethod
    async def validate_credential(cls, data):
        result = await check_connection(credential(data))
        return {'valid': True, 'hint': result['proof']}
    @classmethod
    async def validate_credential_access(cls, data):
        return await cls.validate_credential(data)

    async def execute(self,inputs):
        if not self.config or not self.config.credentials:raise ValueError("Connect a native People Data Labs API key")
        config=self.config.config
        try:
            nested=self.node_data.get('config') or {};cid=self.node_data.get('credential_id')
            if isinstance(nested,dict) and nested.get('credential_id'):
                if cid and cid!=nested['credential_id']:raise PDLError("Saved credential selection is ambiguous")
                cid=nested['credential_id']
            data=await freshen(self.config.credentials.model_dump(mode='json'),credential_id=cid,pool=self.node_data.get('_approval_pool'),user_id=self.user_id,organization_id=self.organization_id,workflow_id=self.workflow_id)
            if config.operation=='check_connection':
                return {'status': 'success', 'action': config.operation, 'data': await check_connection(data)}
            result=await self._operation(data,config)
            return {'status':'success','action':config.operation,'data':result}
        except PDLError as exc:return {'status':'error','action':config.operation,'error':str(exc),'status_code':exc.status_code,'error_kind':exc.kind}
        except (ValueError,TypeError,KeyError):return {'status':'error','action':config.operation,'error':'Company credential, authority or response could not be validated'}

    async def _operation(self,data,config):
        if config.operation=='enrich_company':
            effective=('pdl_id',) if config.pdl_id else MATCH_FIELDS[1:]
            params={k:getattr(config,k) for k in effective if getattr(config,k) is not None}
            params.update(min_likelihood=config.min_likelihood,include_if_matched='true' if config.include_if_matched else 'false',data_include=','.join(sorted({'id','linkedin_slug',*config.fields})))
            raw=await request(data,'company/enrich',params)
            if raw is None:return {'matched':False,'company':None,'likelihood':None,'request_status':404}
            if 'data' in raw or type(raw.get('likelihood')) is not int or not config.min_likelihood<=raw['likelihood']<=10:raise PDLError("Provider returned an unreadable single-company enrichment envelope")
            row=company(raw,config.fields,data)
            if config.pdl_id and config.pdl_id not in (row['id'],raw.get('linkedin_slug')):raise PDLError("Provider returned a different requested company ID or slug")
            matched=raw.get('matched')
            if matched is not None and (not isinstance(matched,list) or len(matched)>100 or any(not isinstance(k,str) or k not in effective or k not in params for k in matched)):raise PDLError("Provider returned unsupported matched-input diagnostics")
            return {'matched':True,'company':row,'likelihood':raw['likelihood'],'matched_inputs':matched,'id_precedence_applied':bool(config.pdl_id),'request_status':200}
        scope=continuation_scope(data,config);scroll=None;page,returned=1,0
        if config.page_token:
            try:
                token=json.loads(base64.urlsafe_b64decode(config.page_token.encode('ascii')))
                if not isinstance(token,dict) or set(token)!={'scope','scroll','page','returned','sig'}:raise ValueError()
                signature=token.pop('sig')
                if not isinstance(signature,str) or not hmac.compare_digest(signature,continuation_signature(data,token)) or token['scope']!=scope or type(token['page']) is not int or not 2<=token['page']<=config.max_pages or type(token['returned']) is not int or not 0<token['returned']<=(token['page']-1)*config.size:raise ValueError()
                scroll=text(token['scroll'],8192);page,returned=token['page'],token['returned']
            except Exception:raise PDLError("Continuation belongs to a different query, key, size or projection") from None
        params={'size':config.size}
        if config.query:params['query']=json.dumps(config.query.model_dump(mode='json',by_alias=True,exclude_none=True),separators=(',',':'))
        else:params['sql']=config.sql
        if scroll:params['scroll_token']=scroll
        raw=await request(data,'company/search',params)
        if raw is None:return {'items':[],'total':None,'next_page_token':None,'continuation_known':True,'stop_reason':'documented_not_found','pagination_complete':True if scroll else None,'returned_records':returned,'request_status':404}
        rows=raw.get('data');total=raw.get('total')
        if not isinstance(rows,list) or len(rows)>config.size or type(total) is not int or total<0 or total<len(rows):raise PDLError("Provider returned unreadable bounded company search metadata")
        items=[company(row,config.fields,data) for row in rows]
        if len({row['id'] for row in items})!=len(items):raise PDLError("Provider returned duplicate company identities")
        returned+=len(items);next_scroll=raw.get('scroll_token');known='scroll_token' in raw
        if next_scroll is not None:next_scroll=text(safe(next_scroll,data,8192),8192)
        if next_scroll and (not rows or next_scroll==scroll):raise PDLError("Provider returned a non-progressing company continuation")
        truncated=bool(next_scroll and page>=config.max_pages)
        token=None
        if next_scroll and not truncated:
            cursor={'scope':scope,'scroll':next_scroll,'page':page+1,'returned':returned}
            cursor['sig']=continuation_signature(data,cursor)
            token=base64.urlsafe_b64encode(json.dumps(cursor,separators=(',',':')).encode()).decode()
            if len(token)>16000:raise PDLError("Provider continuation exceeds the native token size bound")
        return {'items':items,'total':total,'next_page_token':token,'continuation_known':known,'truncated':truncated,'stop_reason':'local_page_cap' if truncated else 'provider_complete' if known and next_scroll is None else None,'requested_page':page,'returned_records':returned,'request_status':200}
