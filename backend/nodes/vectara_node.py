"""Native Vectara v2 corpus, document indexing and retrieval workflows.

Every request is bound to one explicitly selected corpus. Retrieval disables
generation and query history; arbitrary queries and account/key APIs are absent.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from contextvars import ContextVar
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, WrapValidator, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client
from utils.oauth_token_cache import OAuthTokenCache, oauth_authority_digest

API = "https://api.vectara.io/v2"
FAMILY = "vectara_api_key"
OAUTH_FAMILY = "vectara_client_credentials"
FAMILIES = (FAMILY, OAUTH_FAMILY)
_TOKEN_CACHE = OAuthTokenCache()
_PRIVATE = ContextVar("vectara_private_request", default=False)
_REFERENCE = re.compile(r"\{\{.*\}\}|\$\(", re.S)


class VectaraError(ValueError):
    def __init__(self, message, *, http_status=None, uncertain=False):
        super().__init__(message)
        self.http_status, self.uncertain = http_status, uncertain


class _Privacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            record.msg, record.args = "Vectara transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_PRIVACY = _Privacy()


def _ref(value):
    return isinstance(value, str) and bool(_REFERENCE.search(value))


def _literal_secret(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be literal text.")
    value = clean_secret(value, field_name=label)
    if not value or len(value) > 8192 or _ref(value) or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError(f"Supply {label} without spaces or control characters.")
    return value


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_=-]{1,50}", value):
        raise ValueError("Supply a literal Vectara corpus key, at most 50 characters.")
    return value


def _id(value):
    if not isinstance(value, str) or not value or len(value) > 256 or value != value.strip() or "://" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Supply a native document ID without a URL or control characters.")
    return value


def _cursor(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 4096 or "://" in value or _ref(value) or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise VectaraError("Vectara returned or received an invalid opaque page key.")
    return value


def _job_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"job_[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Supply a native Vectara job ID.")
    return value


def _metadata(value):
    if not isinstance(value, dict) or len(value) > 100:
        raise ValueError("Metadata must be an object with at most 100 scalar fields.")
    for key, item in value.items():
        if not isinstance(key, str) or not 1 <= len(key) <= 128 or any(ord(c) < 32 for c in key):
            raise ValueError("Metadata keys must be bounded text.")
        if not (item is None or isinstance(item, (str, int, float, bool))) or isinstance(item, str) and len(item) > 10000 or isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Metadata values must be bounded finite JSON scalars.")
    if len(json.dumps(value, allow_nan=False).encode()) > 65536:
        raise ValueError("Native metadata exceeds 64 KiB.")
    return value


CorpusKey = Annotated[str, WrapValidator(lambda v, h: v if _ref(v) else _key(h(v)))]
DocumentID = Annotated[str, WrapValidator(lambda v, h: v if _ref(v) else _id(h(v)))]
JobID = Annotated[str, WrapValidator(lambda v, h: v if _ref(v) else _job_id(h(v)))]
Cursor = Annotated[str, WrapValidator(lambda v, h: v if _ref(v) else _cursor(h(v)))]
Number = Annotated[int, WrapValidator(lambda v, h: v if _ref(v) else h(v))]
Metadata = Annotated[dict, WrapValidator(lambda v, h: v if _ref(v) else _metadata(h(v)))]


class VectaraAPIKeyCredential(BaseModel):
    credential_type: Literal["vectara_api_key"] = Field("vectara_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})
    corpus_key: str = Field(..., title="Bound Corpus Key", description="Every operation is restricted to this existing or deliberately new corpus key.")
    @field_validator("api_key", mode="before")
    @classmethod
    def secret(cls, value):
        return _literal_secret(value, "Vectara API key")
    @model_validator(mode="before")
    @classmethod
    def method(cls, value):
        if isinstance(value, dict) and any(value.get(k) is not None for k in ("client_id", "client_secret", "token_endpoint")):
            raise ValueError("Select one Vectara authentication method.")
        return value
    @field_validator("corpus_key", mode="before")
    @classmethod
    def corpus(cls, value):
        return _key(value)
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True, title="Vectara API Key", json_schema_extra={
        "x-credential-url": "https://console.vectara.com",
        "x-credential-instructions": "Supply an existing API key and its explicitly allowed corpus. Viewer/editor/API roles determine availability. No key creation, OAuth bootstrap or account identity is claimed."
    })


class VectaraClientCredentials(BaseModel):
    credential_type: Literal["vectara_client_credentials"] = Field(OAUTH_FAMILY, json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., title="Client ID")
    client_secret: str = Field(..., title="Client Secret", json_schema_extra={"ui:widget": "password"})
    token_endpoint: Literal["https://auth.vectara.io/oauth2/token", "https://auth.vectara.com/oauth2/token"] = Field(..., title="Token Endpoint", description="Select the exact official authentication URL shown for your existing app client. No automatic host fallback.")
    corpus_key: str = Field(..., title="Bound Corpus Key", description="Every operation is restricted to this existing or deliberately new corpus key.")

    @field_validator("client_id", "client_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        return _literal_secret(value, "Vectara " + info.field_name.replace("_", " "))

    @model_validator(mode="before")
    @classmethod
    def method(cls, value):
        if isinstance(value, dict) and value.get("api_key") is not None:
            raise ValueError("Select one Vectara authentication method.")
        return value

    @field_validator("corpus_key", mode="before")
    @classmethod
    def corpus(cls, value):
        return _key(value)

    model_config = ConfigDict(extra="allow", hide_input_in_errors=True, title="Vectara OAuth Client", json_schema_extra={
        "x-credential-url": "https://console.vectara.com/console/apiAccess/appClients",
        "x-credential-instructions": "Supply an existing app client's ID, secret, exact official token endpoint and allowed corpus. The server obtains short-lived machine tokens; no browser consent or refresh token. The bound corpus read proves reachability, not account identity."
    })


Credential = Union[VectaraAPIKeyCredential, VectaraClientCredentials]
_CREDENTIAL = TypeAdapter(Credential)


def _material(cred):
    if isinstance(cred, VectaraClientCredentials):
        return (cred.credential_type, cred.corpus_key, cred.client_id, cred.client_secret, cred.token_endpoint)
    return (cred.credential_type, cred.corpus_key, cred.api_key)


def _secrets(cred):
    return (cred.client_id, cred.client_secret) if isinstance(cred, VectaraClientCredentials) else (cred.api_key,)


def _contains_secret(value, secrets):
    if isinstance(value, str): return any(secret in value for secret in secrets)
    if isinstance(value, dict): return any(_contains_secret(key, secrets) or _contains_secret(item, secrets) for key, item in value.items())
    return any(_contains_secret(item, secrets) for item in value) if isinstance(value, (list, tuple)) else False


class _Base(BaseModel):
    corpus_key: CorpusKey | None = Field(None, description="Defaults to the credential's bound corpus; another key is refused.", json_schema_extra={"x-resource-type": "vectara_corpus_key"})
    model_config = ConfigDict(extra="ignore")


class _MetadataProjection(_Base):
    metadata_keys: list[str] = Field(default_factory=list, max_length=20, description="Explicit scalar metadata fields to return. Default omits document metadata.", json_schema_extra={"ui:widget": "list"})
    @field_validator("metadata_keys")
    @classmethod
    def keys(cls, value):
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", k) for k in value):
            raise ValueError("Metadata projection keys must be bounded literal field names.")
        return value


class _Page(_MetadataProjection):
    limit: Number = Field(10, ge=1, le=100, description="This node caps each page at 100 items.")
    page_key: Cursor | None = None


class _Document(_MetadataProjection):
    document_id: DocumentID = Field(..., json_schema_extra={"x-resource-type": "vectara_document_id"})


class _CorpusName(_Base):
    name: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=5000, json_schema_extra={"ui:widget": "textarea"})


class _UpdateCorpus(_CorpusName):
    @model_validator(mode="after")
    def nonempty(self):
        if self.name is None and self.description is None:
            raise ValueError("Supply a corpus name or description.")
        return self


class _Index(_Document):
    text: str = Field(..., min_length=1, max_length=200000, json_schema_extra={"ui:widget": "textarea"})
    metadata: Metadata = Field(default_factory=dict, json_schema_extra={"ui:widget": "json"})
    wait_for: Literal["searchable", "indexed"] = Field("searchable", description="Indexed is durably stored but may briefly lag in search; searchable waits for retrieval readiness.")


class _UpdateMetadata(_Document):
    metadata: Metadata = Field(..., json_schema_extra={"ui:widget": "json"})


class _Search(_Base):
    query: str = Field(..., min_length=1, max_length=5000)
    limit: Number = Field(10, ge=1, le=100)
    offset: Number = Field(0, ge=0, le=100000)
    lexical_interpolation: float = Field(0.005, ge=0, le=1, allow_inf_nan=False)
    metadata_filter: str | None = Field(None, max_length=8000)


class _Job(_Base):
    job_id: JobID = Field(..., json_schema_extra={"x-resource-type": "vectara_job_id"})
    page_key: Cursor | None = Field(None, description="Optional bound-corpus job page from List Corpus Jobs. The selected job must appear on this page before detail readback.")

class VectaraGetCorpusConfig(_Base):
    operation: Literal["get_corpus"] = Field("get_corpus", description='Read the explicitly bound corpus metadata and usage; proves scoped reachability only.', json_schema_extra={"const": "get_corpus", "ui:hidden": True, "x-display-name": "Get Bound Corpus", "x-category": "Corpora", "x-is-trigger": False})

class VectaraCreateCorpusConfig(_CorpusName):
    operation: Literal["create_corpus"] = Field("create_corpus", description='Create the credential-bound corpus key. Requires account creation permission and may consume account resources.', json_schema_extra={"const": "create_corpus", "ui:hidden": True, "x-display-name": "Create Bound Corpus", "x-category": "Corpora", "x-is-trigger": False})

class VectaraUpdateCorpusConfig(_UpdateCorpus):
    operation: Literal["update_corpus"] = Field("update_corpus", description='Change only the bound corpus name and description.', json_schema_extra={"const": "update_corpus", "ui:hidden": True, "x-display-name": "Update Corpus Metadata", "x-category": "Corpora", "x-is-trigger": False})

class VectaraListDocumentsConfig(_Page):
    operation: Literal["list_documents"] = Field("list_documents", description='Read one bounded document ID and selected scalar metadata page; omit document contents.', json_schema_extra={"const": "list_documents", "ui:hidden": True, "x-display-name": "List Documents", "x-category": "Documents", "x-is-trigger": False})

class VectaraGetDocumentConfig(_Document):
    operation: Literal["get_document"] = Field("get_document", description='Read one selected document ID, usage and explicitly selected scalar metadata.', json_schema_extra={"const": "get_document", "ui:hidden": True, "x-display-name": "Get Document Metadata", "x-category": "Documents", "x-is-trigger": False})

class VectaraIndexDocumentConfig(_Index):
    operation: Literal["index_document"] = Field("index_document", description='Index one owned core text document. May consume resources; read back its explicit ID before repeating an uncertain write.', json_schema_extra={"const": "index_document", "ui:hidden": True, "x-display-name": "Index Text Document", "x-category": "Documents", "x-is-trigger": False})

class VectaraMergeDocumentMetadataConfig(_UpdateMetadata):
    operation: Literal["merge_document_metadata"] = Field("merge_document_metadata", description='Merge scalar metadata fields into the selected document using PATCH.', json_schema_extra={"const": "merge_document_metadata", "ui:hidden": True, "x-display-name": "Merge Document Metadata", "x-category": "Documents", "x-is-trigger": False})

class VectaraReplaceDocumentMetadataConfig(_UpdateMetadata):
    operation: Literal["replace_document_metadata"] = Field("replace_document_metadata", description='Replace all metadata on the selected document using PUT. An empty object clears metadata.', json_schema_extra={"const": "replace_document_metadata", "ui:hidden": True, "x-display-name": "Replace Document Metadata", "x-category": "Documents", "x-is-trigger": False})

class VectaraDeleteDocumentConfig(_Document):
    operation: Literal["delete_document"] = Field("delete_document", description='Delete one deliberately selected document. The acknowledgement does not verify absence; get it again for readback.', json_schema_extra={"const": "delete_document", "ui:hidden": True, "x-display-name": "Delete Document", "x-category": "Documents", "x-is-trigger": False})

class VectaraSearchCorpusConfig(_Search):
    operation: Literal["search_corpus"] = Field("search_corpus", description='Retrieve bounded matching text with generation, saved history and query rewriting disabled. Search may consume resources.', json_schema_extra={"const": "search_corpus", "ui:hidden": True, "x-display-name": "Search Corpus without Generation", "x-category": "Search", "x-is-trigger": False})

class VectaraListCorpusJobsConfig(_Page):
    operation: Literal["list_corpus_jobs"] = Field("list_corpus_jobs", description='Read an existing job page filtered to the bound corpus; refuse jobs that also belong to another corpus.', json_schema_extra={"const": "list_corpus_jobs", "ui:hidden": True, "x-display-name": "List Corpus Jobs", "x-category": "Jobs", "x-is-trigger": False})

class VectaraGetCorpusJobConfig(_Job):
    operation: Literal["get_corpus_job"] = Field("get_corpus_job", description='Read one existing exclusively bound job; pending and failed provider states remain explicit.', json_schema_extra={"const": "get_corpus_job", "ui:hidden": True, "x-display-name": "Get Corpus Job State", "x-category": "Jobs", "x-is-trigger": False})

Config = Annotated[Union[VectaraGetCorpusConfig, VectaraCreateCorpusConfig, VectaraUpdateCorpusConfig, VectaraListDocumentsConfig, VectaraGetDocumentConfig, VectaraIndexDocumentConfig, VectaraMergeDocumentMetadataConfig, VectaraReplaceDocumentMetadataConfig, VectaraDeleteDocumentConfig, VectaraSearchCorpusConfig, VectaraListCorpusJobsConfig, VectaraGetCorpusJobConfig], Field(discriminator="operation")]


class VectaraNodeConfig(NodeConfig[Config, Credential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _raw_guard(data):
    if not isinstance(data, dict):
        raise ValueError("Vectara configuration must be an object.")
    mapping, cid = data.get("credentialIds", {}), data.get("credential_id")
    if mapping is None: mapping = {}
    if cid is not None and (not isinstance(cid, str) or not cid or _ref(cid)):
        raise ValueError("Select a literal credential row ID.")
    if not isinstance(mapping, dict) or len(mapping)>1 or any(k not in FAMILIES or not isinstance(v,str) or not v or _ref(v) for k,v in mapping.items()):
        raise ValueError("Select one native Vectara credential.")
    if cid and mapping and cid not in mapping.values():
        raise ValueError("Selected Vectara row IDs differ.")
    creds=data.get("credentials")
    if isinstance(creds,dict):
        stored=bool(cid or mapping) or any(creds.get(k) is not None for k in ("id","token_version","updated_at"))
        family = creds.get("credential_type")
        if (stored or family is not None) and family not in FAMILIES:
            raise ValueError("Stored Vectara credentials require an explicit native family.")
        if mapping and family != next(iter(mapping)):
            raise ValueError("The Vectara attachment family differs from the credential.")
        if creds.get("api_key") is not None and any(creds.get(k) is not None for k in ("client_id", "client_secret", "token_endpoint")):
            raise ValueError("Select one Vectara authentication method.")
        if any(creds.get(k) is not None for k in ("id","token_version","updated_at")) and not (cid or mapping):
            raise ValueError("Stored Vectara attachments require a selected row.")
        if any(creds.get(k) is not None and not isinstance(creds[k],str) for k in ("api_key","corpus_key","client_id","client_secret","token_endpoint")):
            raise ValueError("Vectara key and corpus must be text before shaping.")
    cfg=data.get("config",data)
    if isinstance(cfg,dict):
        for k in ("corpus_key","document_id","job_id","query","text","name","description","metadata_filter","page_key"):
            if cfg.get(k) is not None and not isinstance(cfg[k],str):
                raise ValueError("Vectara IDs and text must be text before shaping.")
        if any(isinstance(cfg.get(k),bool) for k in ("limit","offset","lexical_interpolation")):
            raise ValueError("Numeric parameters cannot be boolean.")
        if cfg.get("operation") in ("index_document","merge_document_metadata","replace_document_metadata") and "metadata" in cfg and not _ref(cfg["metadata"]): _metadata(cfg["metadata"])
        if "metadata_keys" in cfg and (not isinstance(cfg["metadata_keys"],list) or any(not isinstance(k,str) for k in cfg["metadata_keys"])):
            raise ValueError("Metadata projection keys must be a list of text fields.")


def _selected(data):
    _raw_guard(data)
    return data.get("credential_id") or next(iter((data.get("credentialIds") or {}).values()),None)


def _unresolved(value):
    if isinstance(value,str): return _ref(value)
    if isinstance(value,(dict,list)): return any(_unresolved(v) for v in (value.values() if isinstance(value,dict) else value))
    return False


def _project_metadata(body, keys):
    if not isinstance(body,dict): return {}
    out={}
    for key in keys:
        if key not in body: continue
        if re.search(r"secret|password|token|api.?key|authorization|url",key,re.I): continue
        v=body.get(key)
        if v is None or isinstance(v,(bool,int,float)) and (not isinstance(v,float) or math.isfinite(v)) or isinstance(v,str) and len(v)<=10000 and "://" not in v:
            out[key]=v
    return out


def _document(body, corpus, keys, expected=None):
    if not isinstance(body,dict): raise VectaraError("Vectara returned invalid document metadata.")
    try: rid=_id(body.get("id"))
    except ValueError: raise VectaraError("Vectara returned an invalid document ID.") from None
    if expected is not None and rid!=expected: raise VectaraError("Vectara returned a different selected document.")
    out={"id":rid,"corpus_key":corpus,"metadata":_project_metadata(body.get("metadata"),keys)}
    usage=body.get("storage_usage")
    if isinstance(usage,dict): out["storage_usage"]={k:v for k,v in usage.items() if k in ("bytes_used","metadata_bytes_used") and isinstance(v,int) and not isinstance(v,bool) and v>=0}
    return out


def _corpus(body, expected):
    if not isinstance(body,dict) or body.get("key")!=expected: raise VectaraError("Vectara returned a different bound corpus.")
    out={k:body[k] for k in ("id","key","name","description","created_at","encoder_name") if isinstance(body.get(k),str)}
    if isinstance(body.get("enabled"),bool): out["enabled"]=body["enabled"]
    limits=body.get("limits")
    if isinstance(limits,dict): out["usage"]={k:v for k,v in limits.items() if k in ("used_docs","used_parts","used_characters") and isinstance(v,int) and not isinstance(v,bool) and v>=0}
    return out


def _write_ack(project, *args):
    try:
        return project(*args)
    except (ValueError,TypeError):
        raise VectaraError("Vectara returned an invalid write acknowledgement. Outcome is unknown; read back before repeating.",uncertain=True) from None


def _job(body, corpus, expected=None):
    if not isinstance(body,dict) or not isinstance(body.get("id"),str) or not re.fullmatch(r"job_[A-Za-z0-9_-]{1,128}",body["id"]): raise VectaraError("Vectara returned invalid job metadata.")
    if body.get("corpus_keys")!=[corpus] or expected is not None and body["id"]!=expected: raise VectaraError("The job is not exclusively bound to this corpus.")
    state=body.get("state")
    if state not in ("unknown","queued","started","completed","failed","failed_will_retry","aborted"): raise VectaraError("Vectara returned an unknown job state.")
    out={"id":body["id"],"corpus_key":corpus,"state":state}
    for k in ("type","created_at","started_at","completed_at"):
        if isinstance(body.get(k),str): out[k]=body[k]
    progress=body.get("progress")
    if isinstance(progress,dict): out["progress"]={k:v for k,v in progress.items() if k in ("documents_indexed","documents_expected","scan_shards","scan_shards_finished") and isinstance(v,int) and not isinstance(v,bool) and v>=0}
    return out


from repositories.credentials import credential_access_predicate


class VectaraAuthorityRepo:
    def __init__(self,pool): self.pool=pool
    _ACCESS=f"""SELECT c.id,c.owner_id,c.credential_type,c.credential,c.metadata,
        c.revoked_at,c.token_version,c.updated_at FROM credentials c
        WHERE c.id=$1 AND {credential_access_predicate()}"""
    async def accessible(self,cid,user,org):
        async with self.pool.acquire() as conn:
            row=await conn.fetchrow(self._ACCESS,cid,user,org)
        return dict(row) if row else None
    async def workflow_owner(self,workflow_id):
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT owner_id FROM workflows WHERE id=$1",workflow_id)


class VectaraNode(WorkflowNode):
    integration_type = "automation-vectara"
    credential_provider_labels = {"vectara": "Vectara Account"}
    connection_evidence=ConnectionEvidence(operation="get_corpus",noun="corpus",label_keys=("name","key"),proves="reachability")
    scope_registry=ScopeRegistry("Vectara",{op:ScopeRequirement(credential_types=FAMILIES,note="API key or machine client; viewer/editor and account API roles are enforced by Vectara. Native calls remain bound to one corpus.") for op in ("get_corpus","create_corpus","update_corpus","list_documents","get_document","index_document","merge_document_metadata","replace_document_metadata","delete_document","search_corpus","list_corpus_jobs","get_corpus_job")})
    @classmethod
    def get_config_model(cls): return VectaraNodeConfig
    @classmethod
    def parse_config(cls,config_data):
        _raw_guard(config_data); return super().parse_config(config_data)
    @classmethod
    def validate_config(cls,config_data):
        try: _raw_guard(config_data)
        except ValueError as e: return {"valid":False,"errors":[str(e)],"satisfied_set":None}
        return super().validate_config(config_data)
    def _context(self):
        return (self.user_id,self.organization_id,self.workflow_id,_selected(self.node_data),json.dumps(self.node_data.get("config",{}),sort_keys=True,default=str),json.dumps(self.node_data.get("credentials",{}),sort_keys=True,default=str),self.config.config.model_dump(mode="json"))
    async def run(self,inputs):
        self.__dict__.pop("_executing",None)
        cid=_selected(self.node_data)
        if cid: self.node_data["credential_id"]=cid
        self._admitted=self._context()
        return await super().run(inputs)
    def _check(self):
        ctx=self._context()
        if ctx!=getattr(self,"_admitted",ctx) or ctx!=getattr(self,"_executing",ctx): raise VectaraError("Vectara caller, selection or arguments changed; run the configured operation again.")
    async def _current(self):
        from repositories.organization import OrgRepo
        from utils.database_pool import get_native_pool
        from utils.encryption import get_encryption
        from utils.credentials import is_credential_authorized_for_workflow
        self._check(); cid=_selected(self.node_data); expected=self.config.credentials
        if not cid:
            if expected is None: raise VectaraError("Connect Vectara credentials and a bound corpus.")
            return expected,("unsaved",*_material(expected))
        if not self.user_id: raise VectaraError("Saved credentials require an authenticated caller.")
        pool=get_native_pool(); repo=VectaraAuthorityRepo(pool); actor=self.user_id
        async with pool.acquire() as conn: primary=await OrgRepo(pool).get_primary_org_id(conn,self.user_id)
        row=await repo.accessible(cid,actor,self.organization_id)
        if row is None and self.workflow_id and await is_credential_authorized_for_workflow(pool,self.workflow_id,cid):
            owner=await repo.workflow_owner(self.workflow_id)
            if owner: row,actor=await repo.accessible(cid,owner,None),owner
        self._check()
        if not row or str(row["id"])!=cid or row["credential_type"] not in FAMILIES or expected is None or row["credential_type"]!=expected.credential_type: raise VectaraError("The current Vectara row is missing, inaccessible or belongs to another credential family.")
        meta=row.get("metadata") or {}
        try: meta=json.loads(meta) if isinstance(meta,str) else meta
        except ValueError: raise VectaraError("Current credential metadata is invalid.") from None
        if not isinstance(meta,dict) or row.get("revoked_at") or meta.get("revoked_at") or meta.get("connection_healthy") is False: raise VectaraError("The current Vectara credential is revoked or disconnected.")
        try:
            blob = {**get_encryption().decrypt_credential(row["credential"]), "credential_type": row["credential_type"]}
            _raw_guard({"credential_id": cid, "credentials": blob})
            cred = _CREDENTIAL.validate_python(blob)
        except (ValueError,TypeError): raise VectaraError("The current Vectara credential is invalid.") from None
        if expected is None or cred.corpus_key!=expected.corpus_key: raise VectaraError("The selected credential's bound corpus changed.")
        return cred,(str(row["id"]),str(row["owner_id"]),row["credential_type"],row.get("token_version"),str(row.get("updated_at")),primary,actor,self.organization_id,*_material(cred))
    async def _guard(self):
        cred,binding=await self._current()
        if binding!=self._binding: raise VectaraError("Current credential version, corpus or authority changed during the call.")
        return cred
    async def _authorization(self, cred):
        if not isinstance(cred, VectaraClientCredentials):
            return {"x-api-key": cred.api_key}, _secrets(cred)
        cache_key = oauth_authority_digest(provider="vectara", binding=self._binding)
        token = _TOKEN_CACHE.get(cache_key, now=time.monotonic())
        if token is None:
            started = time.monotonic()
            try:
                async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                    await self._guard()
                    async with client.stream("POST", cred.token_endpoint, data={"grant_type": "client_credentials", "client_id": cred.client_id, "client_secret": cred.client_secret}, headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}) as response:
                        status, buffer = response.status_code, bytearray()
                        async for part in response.aiter_bytes():
                            buffer.extend(part)
                            if len(buffer) > 65536: raise VectaraError("Vectara token response exceeded 64 KiB.")
            except httpx.HTTPError:
                raise VectaraError("Vectara machine-token transport failed.") from None
            await self._guard()
            if status != 200:
                raise VectaraError("Vectara rejected the machine-token request." if status in (400,401,403) else "Vectara machine-token request failed.", http_status=status)
            try:
                payload = json.loads(buffer)
                token, ttl = payload.get("access_token"), payload.get("expires_in")
                valid = (
                    isinstance(token, str)
                    and re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token)
                    and len(token) <= 16384
                    and payload.get("token_type", "").lower() == "bearer"
                    and not isinstance(ttl, bool)
                    and isinstance(ttl, (int, float))
                    and math.isfinite(ttl)
                    and 0 < ttl <= 86400
                    and not any(secret in token for secret in _secrets(cred))
                )
            except (ValueError, TypeError, AttributeError):
                valid = False
            if not valid: raise VectaraError("Vectara returned an invalid machine token or expiry.")
            _TOKEN_CACHE.put(cache_key, token, expires_in=ttl, now=started)
            if _TOKEN_CACHE.get(cache_key, now=time.monotonic()) is None:
                raise VectaraError("Vectara machine token expired before use.")
        return {"Authorization": "Bearer " + token}, (*_secrets(cred), token)
    async def _request(self,method,path,*,params=None,body=None,expected_status=200,mutation=False):
        cred=await self._guard()
        base="/corpora/"+quote(cred.corpus_key,safe="")
        document_path=base+"/documents/"+quote(getattr(self.config.config,"document_id",""),safe="")
        routes={("GET",base),("PATCH",base),("POST","/corpora"),("GET",base+"/documents"),("POST",base+"/documents"),("GET",document_path),("PATCH",document_path),("DELETE",document_path),("PUT",document_path+"/metadata"),("POST",base+"/query"),("GET","/jobs"),("GET","/jobs/"+getattr(self.config.config,"job_id",""))}
        if (method,path) not in routes:
            raise VectaraError("Unsupported native Vectara route.")
        for name in {"httpx","httpcore",*logging.Logger.manager.loggerDict}:
            if name in ("httpx","httpcore") or name.startswith(("httpx.","httpcore.")): logging.getLogger(name).addFilter(_PRIVACY)
        private=_PRIVATE.set(True)
        try:
            auth, secrets = await self._authorization(cred)
            if _contains_secret({"path":path,"params":params,"body":body}, secrets):
                raise VectaraError("Authentication material cannot be submitted as indexed or query data.")
            async with guarded_async_client(timeout=30,follow_redirects=False,trust_env=False) as client:
                await self._guard()
                async with client.stream(method,API+path,params=params,json=body,headers={**auth,"Accept":"application/json","Request-Timeout-Millis":"25000"}) as response:
                    status=response.status_code; buffer=bytearray()
                    async for part in response.aiter_bytes():
                        buffer.extend(part)
                        if len(buffer)>4*1024*1024: raise VectaraError("Vectara response exceeded 4 MiB."+(" Outcome is unknown; read back before repeating." if mutation else ""),uncertain=mutation)
        except httpx.HTTPError: raise VectaraError("Vectara transport failed."+(" Outcome is unknown; read back before repeating." if mutation else ""),uncertain=mutation) from None
        finally: _PRIVATE.reset(private)
        try: await self._guard()
        except VectaraError: raise VectaraError("Credential authority changed before accepting the response."+(" Outcome is unknown; read back before repeating." if mutation else ""),uncertain=mutation) from None
        if status!=expected_status:
            uncertain=mutation and (status>=500 or 300<=status<400 or 200<=status<300)
            message={401:"Vectara rejected the credentials (HTTP 401); reconnect them.",403:"Vectara permission denied (HTTP 403) for this operation.",404:"Vectara corpus, document or job was not found.",409:"Vectara reported a conflict; read back before repeating.",429:"Vectara request limit reached; retry later."}.get(status,"Vectara returned an unexpected status.")
            raise VectaraError(message+(" Outcome is unknown; read back before repeating." if uncertain else ""),http_status=status,uncertain=uncertain)
        if status==204:
            if buffer: raise VectaraError("Unexpected delete acknowledgement; read back before repeating.",uncertain=True)
            return None
        try: result=json.loads(buffer)
        except (ValueError,UnicodeError): raise VectaraError("Unexpected Vectara response."+(" Outcome is unknown; read back before repeating." if mutation else ""),uncertain=mutation) from None
        if _contains_secret(result, secrets): raise VectaraError("Authentication material was withheld from the Vectara response.",uncertain=mutation)
        return result
    async def execute(self,inputs):
        self._check(); cfg=self.config.config
        if _unresolved(cfg.model_dump()): raise VectaraError("Resolve Vectara references before execution.")
        self._executing=self._context(); cred,self._binding=await self._current()
        self.scope_registry.enforce_credential_type(cfg.operation,cred.credential_type)
        corpus=cred.corpus_key
        if cfg.corpus_key is not None and cfg.corpus_key!=corpus: raise VectaraError("The requested corpus is outside the credential's explicit parent binding.")
        base="/corpora/"+quote(corpus,safe=""); op=cfg.operation
        mutation=op in ("create_corpus","update_corpus","index_document","merge_document_metadata","replace_document_metadata","delete_document")
        if _contains_secret(cfg.model_dump(), _secrets(cred)): raise VectaraError("Authentication material cannot be submitted as indexed or query data.")
        if op=="create_corpus":
            body={"key":corpus,"save_history":False,**{k:getattr(cfg,k) for k in ("name","description") if getattr(cfg,k) is not None}}
            data=_write_ack(_corpus,await self._request("POST","/corpora",body=body,expected_status=201,mutation=True),corpus)
        else:
            parent=_corpus(await self._request("GET",base),corpus)
            if op=="get_corpus": data=parent
            elif op=="update_corpus": data=_write_ack(_corpus,await self._request("PATCH",base,body={k:getattr(cfg,k) for k in ("name","description") if getattr(cfg,k) is not None},mutation=True),corpus)
            elif op in ("list_documents","list_corpus_jobs"):
                kind="documents" if op=="list_documents" else "jobs"
                params={"limit":cfg.limit}
                if cfg.page_key is not None: params["page_key"]=_cursor(cfg.page_key)
                if kind=="jobs": params["corpus_key"]=[corpus]
                raw=await self._request("GET",base+"/documents" if kind=="documents" else "/jobs",params=params)
                rows=raw.get(kind) if isinstance(raw,dict) else None
                if not isinstance(rows,list) or len(rows)>cfg.limit: raise VectaraError("Vectara returned an invalid bounded collection.")
                metadata=raw.get("metadata") or {}
                if not isinstance(metadata,dict): raise VectaraError("Invalid Vectara pagination metadata.")
                cursor=_cursor(metadata.get("page_key"))
                if cursor is not None and cursor==cfg.page_key: raise VectaraError("Vectara repeated the page key.")
                data={"corpus_key":corpus,"items":[_document(r,corpus,cfg.metadata_keys) if kind=="documents" else _job(r,corpus) for r in rows],"next_page_key":cursor,"has_more":cursor is not None}
            elif op=="search_corpus":
                search={"limit":cfg.limit,"offset":cfg.offset,"lexical_interpolation":cfg.lexical_interpolation}
                if cfg.metadata_filter is not None: search["metadata_filter"]=cfg.metadata_filter
                raw=await self._request("POST",base+"/query",body={"query":cfg.query,"search":search,"generation":{"enabled":False},"stream_response":False,"save_history":False,"intelligent_query_rewriting":False})
                rows=raw.get("search_results") if isinstance(raw,dict) else None
                if not isinstance(rows,list) or len(rows)>cfg.limit: raise VectaraError("Vectara returned invalid bounded search results.")
                hits=[]
                for r in rows:
                    if not isinstance(r,dict) or r.get("corpus_key",corpus)!=corpus or r.get("request_corpora_index",0)!=0: raise VectaraError("A search result escaped the bound corpus.")
                    score=r.get("score"); text=r.get("text")
                    if not isinstance(score,(int,float)) or isinstance(score,bool) or not math.isfinite(score) or not isinstance(text,str) or len(text)>20000: raise VectaraError("Vectara returned invalid search text or score.")
                    hits.append({"document_id":_id(r.get("document_id")),"score":score,"text":text})
                data={"corpus_key":corpus,"items":hits,"offset":cfg.offset,"generation_enabled":False,"more_results_unknown":len(hits)==cfg.limit}
            elif op=="get_corpus_job":
                params={"corpus_key":[corpus],"limit":100}
                if cfg.page_key is not None: params["page_key"]=_cursor(cfg.page_key)
                listed=await self._request("GET","/jobs",params=params)
                rows=listed.get("jobs") if isinstance(listed,dict) else None
                if not isinstance(rows,list) or len(rows)>100: raise VectaraError("Vectara returned an invalid bound job page.")
                selected=[_job(row,corpus) for row in rows]
                if not any(row["id"]==cfg.job_id for row in selected): raise VectaraError("The selected job is not present on this bound corpus page. List Corpus Jobs and supply its page key before reading the job.")
                data=_job(await self._request("GET","/jobs/"+cfg.job_id),corpus,cfg.job_id)
            else:
                path=base+"/documents/"+quote(cfg.document_id,safe="")
                if op=="index_document":
                    ack=await self._request("POST",base+"/documents",params={"wait_for":cfg.wait_for},body={"id":cfg.document_id,"type":"core","metadata":cfg.metadata,"document_parts":[{"text":cfg.text}]},expected_status=201,mutation=True)
                    data=_write_ack(_document,ack,corpus,cfg.metadata_keys,cfg.document_id); data["searchable_acknowledged"]=cfg.wait_for=="searchable"
                else:
                    found=_document(await self._request("GET",path),corpus,cfg.metadata_keys,cfg.document_id)
                    if op=="get_document": data=found
                    elif op=="delete_document":
                        await self._request("DELETE",path,expected_status=204,mutation=True)
                        data={"id":cfg.document_id,"corpus_key":corpus,"delete_acknowledged":True,"deletion_verified":False}
                    else:
                        method="PATCH" if op=="merge_document_metadata" else "PUT"
                        ack=await self._request(method,path if method=="PATCH" else path+"/metadata",body={"metadata":cfg.metadata},mutation=True)
                        data=_write_ack(_document,ack,corpus,cfg.metadata_keys,cfg.document_id)
        if mutation: data.update(accepted=True,readback_required=True)
        try: await self._guard()
        except VectaraError: raise VectaraError("Current authority changed before accepting the outcome."+(" Outcome is unknown; read back before repeating." if mutation else ""),uncertain=mutation) from None
        result={"status":"success","data":data}
        if op=="get_corpus_job":
            if data["state"] in ("queued","started","failed_will_retry"): result.update(status="pending",executed=True)
            if data["state"] in ("failed","aborted"): result.update(status="error",executed=True,error="Vectara job did not complete successfully.")
        return result
