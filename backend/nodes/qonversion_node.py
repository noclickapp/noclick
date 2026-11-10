"""Native read-only Qonversion v4 product, entitlement and configuration workflows.

Issued server Secret Keys are sent only in Bearer headers. An optional supplied
product witness proves resource reachability, never a project or human identity.
"""
from __future__ import annotations

import base64
from datetime import datetime
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from repositories.qonversion import QonversionCredentialsRepo
from utils.ssrf import SSRFError, guarded_async_client

API = "https://api.qonversion.io/v4"
FAMILY = "qonversion_secret_key"
UNKNOWN = "No witness product was supplied. Secret-key acceptance and resource access remain unverified."
ProductType = Literal["subscription_with_promo", "subscription", "consumable", "lifetime"]


class QonversionError(ValueError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def bounded_text(value, maximum=4096):
    if not isinstance(value, str) or not value or len(value)>maximum or value!=value.strip() or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError("Enter bounded text without edge whitespace or controls")
    return value


def resource_id(value):
    value=bounded_text(value,255)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*",value) or '..' in value:
        raise ValueError("Enter a native resource ID without a URL, path or query")
    return value


def guard(data, stored=False):
    if not isinstance(data,dict) or ((stored or 'credential_type' in data) and data.get('credential_type')!=FAMILY):
        raise ValueError("Select a native Qonversion Secret Key")


class QonversionSecretKeyCredential(BaseModel):
    model_config=ConfigDict(title="Qonversion Secret Key",extra="ignore",hide_input_in_errors=True,json_schema_extra={
        "x-credential-url":"https://documentation.qonversion.io/reference/v4/authentication",
        "x-credential-instructions":"Paste the issued project sk_ Secret Key unchanged, without Bearer. SDK/public keys and historical test_sk_ prefixes are distinct. Native v4 GET reads only; no key mint, environment-prefix rewriting or refresh. Optionally supply an existing Product ID for a protected connection read; this proves that resource's reachability, not project/account identity. Without it provider acceptance remains unknown."})
    credential_type: Literal["qonversion_secret_key"] = Field(FAMILY,json_schema_extra={"ui:hidden":True})
    secret_key: str = Field(...,title="Project Secret Key",json_schema_extra={"ui:widget":"password"})
    witness_product_id: str|None = Field(None,title="Existing Witness Product ID",description="Optional protected GET used when connecting/checking. No product is created and no project identity is inferred.")

    @field_validator('secret_key',mode='before')
    @classmethod
    def validate_secret_key(cls,value):
        value=bounded_text(value,16384)
        if not value.startswith('sk_') or len(value)<=3 or not value.isascii() or any(c.isspace() for c in value) or '://' in value:
            raise ValueError("Paste the issued sk_ server Secret Key unchanged")
        return value

    @field_validator('witness_product_id',mode='before')
    @classmethod
    def validate_witness(cls,value):return resource_id(value) if value is not None else None


def credential(data):
    guard(data)
    try:return QonversionSecretKeyCredential.model_validate(data).model_dump(mode='json')
    except Exception:raise ValueError("Check the native Secret Key and optional product witness") from None


class Config(BaseModel):
    model_config=ConfigDict(extra="forbid",hide_input_in_errors=True)


class CheckConnection(Config):
    operation: Literal['check_connection'] = Field('check_connection',description="Protected read of the credential's exact product witness; no witness means provider acceptance remains unknown.")


class Page(Config):
    limit: int = Field(20,ge=1,le=100,strict=True)
    max_pages: int = Field(10,ge=1,le=100,strict=True,description="Native continuation cap. Each run requests one page; no automatic fetching.")
    page_token: str|None = Field(None,max_length=8000,description="Native continuation bound to this exact endpoint, filters, limit, key and saved authority. No raw starting_after or URL escape.")


class ListProducts(Page):
    operation: Literal['list_products'] = Field('list_products')
    product_types: list[ProductType] = Field(default_factory=list,max_length=4,description="Repeated filter[type] values use documented OR semantics.")
    @field_validator('product_types')
    @classmethod
    def validate_unique_types(cls,value):
        if len(set(value))!=len(value):raise ValueError("Choose each product type once")
        return value


class GetProduct(Config):
    operation: Literal['get_product'] = Field('get_product')
    product_id: str = Field(...,json_schema_extra={"x-resource-type":"qonversion_product"})
    @field_validator('product_id',mode='before')
    @classmethod
    def validate_product_id(cls,value):return resource_id(value)


class ListEntitlementDefinitions(Page):
    operation: Literal['list_entitlement_definitions'] = Field('list_entitlement_definitions')


class GetEntitlementDefinition(Config):
    operation: Literal['get_entitlement_definition'] = Field('get_entitlement_definition')
    entitlement_id: str = Field(...,json_schema_extra={"x-resource-type":"qonversion_entitlement"})
    @field_validator('entitlement_id',mode='before')
    @classmethod
    def validate_entitlement_id(cls,value):return resource_id(value)


class ListRemoteConfigurations(Page):
    operation: Literal['list_remote_configurations'] = Field('list_remote_configurations')


class GetRemoteConfiguration(Config):
    operation: Literal['get_remote_configuration'] = Field('get_remote_configuration')
    configuration_id: str = Field(...,json_schema_extra={"x-resource-type":"qonversion_remote_configuration"},description="Existing UUID; payload and targeting values are omitted from output.")
    @field_validator('configuration_id',mode='before')
    @classmethod
    def validate_configuration_id(cls,value):
        value=resource_id(value)
        if str(UUID(value))!=value:raise ValueError("Enter the canonical configuration UUID")
        return value


class GetUser(Config):
    operation: Literal['get_user'] = Field('get_user')
    user_id: str
    expected_environment: Literal['prod','sandbox'] = Field(...,description="Explicit response binding; Get User has no documented environment query/header. The key is never rewritten.")
    confirm_user_metadata: Literal[True] = Field(...,description="Read pseudonymous user ID/environment/created_at metadata. External identity, properties, contacts and payment data are excluded.")
    @field_validator('user_id',mode='before')
    @classmethod
    def validate_user_id(cls,value):return resource_id(value)
    @field_validator('confirm_user_metadata',mode='before')
    @classmethod
    def validate_user_confirmation(cls,value):
        if value is not True:raise ValueError("Confirm reading the supplied user's safe metadata")
        return value


QonversionConfig=Annotated[Union[CheckConnection,ListProducts,GetProduct,ListEntitlementDefinitions,GetEntitlementDefinition,ListRemoteConfigurations,GetRemoteConfiguration,GetUser],Field(discriminator='operation')]
class QonversionNodeConfig(NodeConfig[QonversionConfig,QonversionSecretKeyCredential]):pass


class CurrentCredential(dict):
    def __init__(self,data,store=None):
        super().__init__(data);self.store=store;self.anchor=store.current if store else None


CURRENT_ORGANIZATION = object()


@dataclass(frozen=True)
class CredentialAuthority:
    credential_id: str
    caller_id: str
    principal_id: str
    organization_id: str | None
    current_organization: bool
    workflow_id: str | None
    owner_id: str
    credential_type: str
    token_version: int


class QonversionCredentialStore:
    def __init__(self, pool, user_id, credential_id, *, organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        self.pool = pool
        self.user_id = str(UUID(str(user_id)))
        self.credential_id = str(UUID(str(credential_id)))
        self.organization_id = organization_id
        self.workflow_id = str(UUID(str(workflow_id))) if workflow_id else None
        self.current = None

    def _repo(self):
        if self.pool is None:
            from utils.database_pool import get_native_pool
            self.pool = get_native_pool()
        return QonversionCredentialsRepo(self.pool)

    async def _load_principal(self, credential_id, principal_id, pool, org_id):
        from utils.encryption import get_encryption
        current_org = self.organization_id is CURRENT_ORGANIZATION
        row, org = await self._repo().load(
            credential_id, principal_id, org_id, caller_id=self.user_id,
            current_organization=current_org, workflow_id=self.workflow_id,
        )
        if row is None:
            return None
        # Admit raw row identity/live/version BEFORE touching the encrypted blob.
        version = row["token_version"]
        if (row["revoked_at"] is not None or row["credential_type"] != FAMILY
                or type(version) is not int or version < 1):
            raise ValueError("Qonversion credential is unavailable or its saved authority changed.")
        try:
            owner = str(UUID(str(row["owner_id"])))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Qonversion credential saved owner is invalid.") from exc
        try:
            data = get_encryption().decrypt_credential(row["credential"])
        except Exception:
            raise ValueError("Qonversion saved credential could not be decrypted.") from None
        if not isinstance(data, dict):
            raise ValueError("Qonversion saved credential has an invalid shape.")
        data["credential_type"] = row["credential_type"]
        data = credential(data)
        self.current = CredentialAuthority(
            self.credential_id, self.user_id, str(principal_id), org, current_org,
            self.workflow_id, owner, row["credential_type"], version,
        )
        data = deepcopy(data)
        data["token_version"] = version
        if row["updated_at"] is not None:
            data["updated_at"] = row["updated_at"].isoformat()
        return data

    async def load(self):
        from utils.credentials import get_workflow_owner_id, is_credential_authorized_for_workflow

        self.current = None
        self._repo()
        org = None if self.organization_id is CURRENT_ORGANIZATION else self.organization_id
        data = await self._load_principal(self.credential_id, self.user_id, self.pool, org)
        if data is None and self.workflow_id:
            owner = await get_workflow_owner_id(self.pool, self.workflow_id)
            if (owner and owner != self.user_id
                    and await is_credential_authorized_for_workflow(self.pool, self.workflow_id, self.credential_id)):
                data = await self._load_principal(self.credential_id, owner, self.pool, org)
        if data is None or self.current is None:
            raise QonversionError("Secret Key not found or current access denied")
        return data


async def freshen(data,**kwargs):
    if kwargs.get('credential_id'):
        if not kwargs.get('user_id'):raise QonversionError("Current saved-key access requires an authenticated actor")
        context={k:kwargs[k] for k in ('organization_id','workflow_id') if k in kwargs}
        store=QonversionCredentialStore(kwargs.get('pool'),kwargs['user_id'],kwargs['credential_id'],**context)
        return CurrentCredential(await store.load(),store)
    return CurrentCredential(credential(data))


async def current_authority(data):
    if getattr(data,'store',None):
        current=await data.store.load()
        if current.get('secret_key')!=data['secret_key'] or current.get('witness_product_id')!=data.get('witness_product_id') or data.store.current!=data.anchor:
            raise QonversionError("Current Secret Key, witness or saved authority changed")
    guard(data,stored=True)


def safe_text(value,data,maximum=4096):
    value=bounded_text(value,maximum)
    if data['secret_key'] in value:raise QonversionError("Provider returned protected metadata")
    return value


def timestamp(value,data):
    value=safe_text(value,data,64)
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds()!=0:raise QonversionError("Provider returned an unsupported UTC timestamp")
    return value


def project(raw,kind,route,data,expected_id=None):
    if not isinstance(raw,dict) or raw.get('object')!=kind:raise QonversionError("Provider returned the wrong native resource object")
    identity=resource_id(safe_text(raw.get('id'),data,255))
    if expected_id and identity!=expected_id:raise QonversionError("Provider returned a different requested resource")
    if raw.get('url')!='/v4/'+route+'/'+identity:raise QonversionError("Provider returned a different native resource path")
    out={'id':identity,'object':kind,'created_at':timestamp(raw.get('created_at'),data)}
    if kind!='user':out['updated_at']=timestamp(raw.get('updated_at'),data)
    if kind=='product':
        for field in ('type','duration','apple_product_id','google_product_id','google_base_plan_id','stripe_product_id'):
            if field in raw:out[field]=safe_text(raw[field],data,1024) if raw[field] is not None else None
    elif kind=='entitlement':
        out['description']=safe_text(raw['description'],data) if raw.get('description') is not None else None
        values=raw.get('product_ids')
        if values is not None:
            if not isinstance(values,list):raise QonversionError("Provider returned unreadable entitlement products")
            out['product_ids']=[resource_id(safe_text(value,data,255)) for value in values[:100]]
            out['product_ids_truncated']=len(values)>100;out['product_count']=len(values)
        else:out['product_ids']=None
    elif kind=='remote_configuration':
        if str(UUID(identity))!=identity:raise QonversionError("Provider returned an unreadable configuration UUID")
        out['name']=safe_text(raw.get('name'),data,1024);out['status']=safe_text(raw.get('status'),data,64)
        priority=raw.get('priority')
        if priority is not None and type(priority) is not int:raise QonversionError("Provider returned unreadable configuration priority")
        out['priority']=priority
        for field in ('started_at','finished_at'):
            if field in raw:out[field]=timestamp(raw[field],data) if raw[field] is not None else None
        # Payload, audience/segmentation and arbitrary properties never enter output.
    else:
        if raw.get('environment') not in ('prod','sandbox'):raise QonversionError("Provider returned an unreadable user environment")
        out['environment']=raw['environment']
    return out


async def request(data,route,params=None):
    await current_authority(data)
    if data['secret_key'] in route or data['secret_key'] in json.dumps(params):raise QonversionError("Resource input contains protected credential data")
    try:
        async with guarded_async_client(trust_env=False,follow_redirects=False,timeout=30) as client:
            response=await client.get(API+'/'+route,headers={'Authorization':'Bearer '+data['secret_key'],'Accept':'application/json'},params=params)
    except (SSRFError,httpx.RequestError):raise QonversionError("Qonversion could not be reached; resource access remains unverified") from None
    await current_authority(data)
    if response.status_code!=200:raise QonversionError(f"Qonversion HTTP {response.status_code}: resource request was not accepted",response.status_code)
    if len(response.content)>2_000_000 or response.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json':raise QonversionError("Provider returned oversized or non-JSON metadata")
    try:raw=response.json()
    except ValueError:raise QonversionError("Provider returned unreadable JSON") from None
    if not isinstance(raw,dict) or 'error' in raw or 'errors' in raw:raise QonversionError("Provider returned an unsuccessful metadata response")
    return raw


def page_scope(data,config):
    args=config.model_dump(mode='json',exclude_none=True,exclude={'page_token'})
    return hashlib.sha256(json.dumps([args,data['secret_key'],data.get('witness_product_id'),vars(data.anchor) if data.anchor else None],sort_keys=True,default=str).encode()).hexdigest()


def sign(data,cursor):
    return hmac.new(data['secret_key'].encode('ascii'),json.dumps(cursor,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()


async def page(data,config,route,kind):
    scope=page_scope(data,config);starting_after=None;ordinal=1
    if config.page_token:
        try:
            cursor=json.loads(base64.urlsafe_b64decode(config.page_token.encode('ascii')))
            if not isinstance(cursor,dict) or set(cursor)!={'scope','after','page','sig'}:raise ValueError()
            signature=cursor.pop('sig')
            if not isinstance(signature,str) or not hmac.compare_digest(signature,sign(data,cursor)) or cursor['scope']!=scope or type(cursor['page']) is not int or not 2<=cursor['page']<=config.max_pages:raise ValueError()
            starting_after=resource_id(cursor['after']);ordinal=cursor['page']
        except Exception:raise QonversionError("Continuation belongs to a different resource, filter, key, authority or page limit") from None
    params=[('limit',config.limit)]
    if starting_after:params.append(('starting_after',starting_after))
    if isinstance(config,ListProducts):params.extend(('filter[type]',value) for value in config.product_types)
    raw=await request(data,route,params)
    if raw.get('object')!='list' or raw.get('url')!='/v4/'+route or not isinstance(raw.get('data'),list) or len(raw['data'])>config.limit or type(raw.get('has_more')) is not bool:raise QonversionError("Provider returned an unreadable bounded list envelope")
    items=[project(row,kind,route,data) for row in raw['data']]
    if len({row['id'] for row in items})!=len(items):raise QonversionError("Provider returned duplicate native resource IDs")
    more=raw['has_more'];next_cursor=raw.get('next_cursor');last=items[-1]['id'] if items else None
    if next_cursor is not None:next_cursor=safe_text(next_cursor,data,8192)
    if (more and (not items or starting_after==last)) or (not more and next_cursor is not None):raise QonversionError("Provider returned a non-progressing or inconsistent continuation")
    # Docs prescribe last ID but also expose next_cursor without equivalence proof.
    ambiguous=bool(more and next_cursor is not None and next_cursor!=last)
    truncated=bool(more and ordinal>=config.max_pages);token=None
    if more and not truncated and not ambiguous:
        cursor={'scope':scope,'after':last,'page':ordinal+1};cursor['sig']=sign(data,cursor)
        token=base64.urlsafe_b64encode(json.dumps(cursor,separators=(',',':')).encode()).decode()
    return {'items':items,'has_more':more,'next_page_token':token,'continuation_known':not ambiguous,'truncated':truncated,'requested_page':ordinal,'stop_reason':'ambiguous_cursor_contract' if ambiguous else 'local_page_cap' if truncated else 'provider_complete' if not more else None}


class QonversionNode(WorkflowNode):
    integration_type = "automation-qonversion"
    workflow_credential_refresh=True  # Saved current authority; no token renewal.
    connection_evidence=ConnectionEvidence(operation='check_connection',noun='supplied product access',proves='reachability')
    edit_examples=['Inspect product metadata','List entitlement definitions','Read remote configuration status','Read an existing user with explicit environment binding']
    @classmethod
    def get_config_model(cls):return QonversionNodeConfig
    @classmethod
    def parse_config(cls,config_data):
        try:
            if isinstance(config_data,dict) and config_data.get('credentials') is not None:guard(config_data['credentials'])
        except ValueError:raise ConfigValidationError("Select a native Qonversion Secret Key") from None
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls,config_data):
        try:
            if isinstance(config_data,dict) and config_data.get('credentials') is not None:guard(config_data['credentials'])
        except ValueError:return {'valid':False,'errors':['Select a native Qonversion Secret Key'],'satisfied_set':None}
        return super().validate_config(config_data)
    @classmethod
    def _extract_actionable_validation_error(cls,error,config_data):return "Check the native Secret Key, resource ID and required read confirmation"
    @classmethod
    async def freshen_credential(cls,credential_data,*,pool=None,user_id=None,credential_id=None):
        return await freshen(credential_data,pool=pool,user_id=user_id,credential_id=credential_id)
    @classmethod
    async def validate_credential(cls,data):
        credential(data)
        return {'valid':None,'hint':'Only the supplied product read establishes reachability; no project or principal identity is proved.'}
    @classmethod
    async def validate_credential_access(cls,data):return await cls.validate_credential(data)

    async def execute(self,inputs):
        if not self.config or not self.config.credentials:raise ValueError("Connect a native Qonversion Secret Key")
        config=self.config.config
        try:
            nested=self.node_data.get('config') or {};cid=self.node_data.get('credential_id')
            if isinstance(nested,dict) and nested.get('credential_id'):
                if cid and cid!=nested['credential_id']:raise QonversionError("Saved credential selection is ambiguous")
                cid=nested['credential_id']
            data=await freshen(self.config.credentials.model_dump(mode='json'),credential_id=cid,pool=self.node_data.get('_approval_pool'),user_id=self.user_id,organization_id=self.organization_id,workflow_id=self.workflow_id)
            if isinstance(config,CheckConnection):
                witness=data.get('witness_product_id')
                if not witness:return {'status':'not_executed','executed':False,'reason':UNKNOWN,'verification':{'reachable':None,'proves':'reachability','account_label':None}}
                project(await request(data,'products/'+witness),'product','products',data,witness)
                return {'status':'success','data':{'items':[],'resource_access':'supplied_product','identity_verified':False},'verification':{'reachable':True,'proves':'reachability','account_label':None}}
            result=await self._operation(data,config)
            return {'status':'success','action':config.operation,'data':result}
        except QonversionError as exc:return {'status':'error','action':config.operation,'error':str(exc),'status_code':exc.status_code}
        except (ValueError,TypeError,KeyError):return {'status':'error','action':config.operation,'error':'Credential, authority or native metadata could not be validated'}

    async def _operation(self,data,config):
        if isinstance(config,ListProducts):return await page(data,config,'products','product')
        if isinstance(config,ListEntitlementDefinitions):return await page(data,config,'entitlements','entitlement')
        if isinstance(config,ListRemoteConfigurations):return await page(data,config,'remote-configurations','remote_configuration')
        if isinstance(config,GetProduct):route,kind,identity='products','product',config.product_id
        elif isinstance(config,GetEntitlementDefinition):route,kind,identity='entitlements','entitlement',config.entitlement_id
        elif isinstance(config,GetRemoteConfiguration):route,kind,identity='remote-configurations','remote_configuration',config.configuration_id
        else:route,kind,identity='users','user',config.user_id
        result=project(await request(data,route+'/'+identity),kind,route,data,identity)
        if isinstance(config,GetUser) and result['environment']!=config.expected_environment:raise QonversionError("Returned user belongs to a different requested environment")
        return result

    @classmethod
    async def load_field_options(cls,field_name,credential_data,context=None,page_token=None,search=None):
        bindings={'product_id':(ListProducts,'products','product'),'entitlement_id':(ListEntitlementDefinitions,'entitlements','entitlement'),'configuration_id':(ListRemoteConfigurations,'remote-configurations','remote_configuration')}
        if field_name not in bindings:return []
        if page_token:raise QonversionError("This picker requires a complete single page; use the list operation for paging")
        if search is not None:search=bounded_text(search,128).casefold()
        config,route,kind=bindings[field_name];data=credential_data
        if not isinstance(data,CurrentCredential):raise QonversionError("Native picker requires a fresh current credential view")
        result=await page(data,config(limit=100,max_pages=1),route,kind)
        if result['has_more']:raise QonversionError("Resource picker is incomplete; enter the existing ID or use the paginated list operation")
        return [{'label':row.get('name') or row['id'],'value':row['id']} for row in result['items'] if search is None or search in (row.get('name') or row['id']).casefold()]
