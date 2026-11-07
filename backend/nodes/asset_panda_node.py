"""Closed Asset Panda Pioneer metadata reads using the current access-key pair.

Protected parent witnesses bind records to the selected account/module/collection.
Only documented identifiers and explicitly requested collection/column names leave the node.
"""
import hashlib
import hmac
import json
import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_serializer
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

ROOT = "https://api.assetpanda.app"
TYPE = "asset_panda_access_key"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 1000
ID = Annotated[str, Field(min_length=1, max_length=128)]
OPERATIONS = {"list_accounts", "get_account", "list_modules", "get_module", "list_collections", "get_collection", "list_collection_columns", "search_collection_records", "get_collection_record"}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("Supply a bounded opaque Asset Panda identifier")
    return value


def metadata_text(value, *, limit=256):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Asset Panda returned malformed metadata text")
    return value


class AssetPandaAccessKeyCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, title="Asset Panda Access Key", json_schema_extra={"x-credential-url": "https://prohelp.assetpanda.com/settings/api-configuration"})
    credential_type: Literal["asset_panda_access_key"] = Field("asset_panda_access_key", json_schema_extra={"ui:hidden": True})
    access_key_id: str = Field(..., min_length=1, max_length=8192, repr=False, title="Access Key ID", description="Supplied Pioneer/Pro key ID sent only in Access-Key-Id to the fixed api.assetpanda.app host.", json_schema_extra={"ui:widget": "password"})
    access_key_secret: str = Field(..., min_length=1, max_length=8192, repr=False, title="Access Key Secret", description="Supplied Pioneer/Pro key secret sent only in Access-Key-Secret. Legacy V2/V3 OAuth credentials are incompatible.", json_schema_extra={"ui:widget": "password"})
    account_id: ID = Field(..., title="Account ID", description="Exact permitted account ID. Protected GET /accounts membership is checked for every native operation; no ownership, role or expiry is inferred.")
    _account_id = field_validator("account_id", mode="before")(identifier)

    @field_validator("access_key_id", "access_key_secret")
    @classmethod
    def opaque_key(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Supply the opaque access-key value without whitespace")
        return value

    @model_serializer(mode="wrap")
    def canonical(self, handler):
        return {**handler(self), "credential_type": TYPE}


def guard(data):
    if not isinstance(data, dict) or data.get("credential_type") != TYPE:
        raise ValueError("Connect a typed Asset Panda Pioneer access-key credential")
    try:
        return AssetPandaAccessKeyCredential.model_validate(data)
    except ValueError:
        raise ValueError("Asset Panda credential shape is invalid; reconnect it") from None


def authority(value):
    return value.credential_type, value.account_id, value.access_key_id, value.access_key_secret


def op(value, title, category):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})


def resource(name, parents=()):
    return {"x-resource-type": "asset_panda_" + name.removesuffix("_id"), "x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True, **({"depends_on": list(parents)} if parents else {})}}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    _ids = field_validator("module_id", "collection_id", "column_id", "record_id", mode="before", check_fields=False)(identifier)


class Module(Input):
    module_id: ID = Field(..., title="Module", json_schema_extra=resource("module_id"))


class Collection(Module):
    collection_id: ID = Field(..., title="Collection", json_schema_extra=resource("collection_id", ("module_id",)))


class Names(Input):
    include_names: StrictBool = Field(False, title="Include Names", description="Opt in to documented collection/column names. Names can contain business or personal data; IDs are returned by default.")


class ListAccounts(Input):
    operation: Literal["list_accounts"] = op("list_accounts", "Verify Selected Account Membership", "Accounts")


class GetAccount(Input):
    operation: Literal["get_account"] = op("get_account", "Get Selected Account ID", "Accounts")


class ListModules(Input):
    operation: Literal["list_modules"] = op("list_modules", "List Account Module IDs", "Modules")


class GetModule(Module):
    operation: Literal["get_module"] = op("get_module", "Get Account Module ID", "Modules")


class ListCollections(Module, Names):
    operation: Literal["list_collections"] = op("list_collections", "List Module Collections", "Collections")


class GetCollection(Collection, Names):
    operation: Literal["get_collection"] = op("get_collection", "Get Collection Metadata", "Collections")


class ListColumns(Collection, Names):
    operation: Literal["list_collection_columns"] = op("list_collection_columns", "List Collection Column Metadata", "Columns")


class SearchRecords(Collection):
    operation: Literal["search_collection_records"] = op("search_collection_records", "Search Collection Record IDs", "Records")
    column_id: ID = Field(..., title="Filter Column", description="Exact current column ID; the documented field-name filter uses its current nonempty name.", json_schema_extra=resource("column_id", ("module_id", "collection_id")))
    operator: Literal["eq", "contains"] = Field("eq", title="Comparison")
    value: str = Field(..., min_length=1, max_length=256, repr=False, title="Search Value", description="Bounded supplied string used only with the selected current column. No raw filters or returned record values.")
    offset: Annotated[StrictInt, Field(ge=0, le=10000)] = Field(0, title="Starting Index", description="Documented zero-based pagination.from, locally capped at 10000. Results may change between calls; no snapshot or cursor guarantee.")
    page_size: Annotated[StrictInt, Field(ge=1, le=100)] = Field(50, title="Page Size", description="Documented pagination.size 1..100. Total and has_more are not supplied by the published envelope.")
    _value = field_validator("value")(metadata_text)


class GetRecord(Collection):
    operation: Literal["get_collection_record"] = op("get_collection_record", "Get Collection Record ID", "Records")
    record_id: ID = Field(..., title="Record ID", description="Paste an exact record ID; only its documented ID is projected. Unfiltered record discovery is not implemented.", json_schema_extra={"x-resource-type": "asset_panda_record"})


Config = Annotated[Union[ListAccounts, GetAccount, ListModules, GetModule, ListCollections, GetCollection, ListColumns, SearchRecords, GetRecord], Field(discriminator="operation")]


class AssetPandaNodeConfig(NodeConfig[Config, AssetPandaAccessKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate Asset Panda metadata field")
        result[key] = value
    return result


def invalid_number(_value):
    raise ValueError("Nonfinite Asset Panda metadata number")


class PrivateHeaders(dict):
    def __repr__(self):
        return "<private Asset Panda access-key headers>"

    __str__ = __repr__


async def request(value, path, *, params=None, body=None):
    query = params or {}
    fixed = {"/accounts": set(), "/modules": {"accountId"}, "/collections": {"accountId", "moduleId"}, "/collection-columns": {"accountId", "moduleId", "collectionId"}, "/collection-records/search": set()}
    points = {"account": set(), "module": {"accountId"}, "collection": {"accountId", "moduleId"}, "collection-record": {"accountId", "moduleId", "collectionId"}}
    if path in fixed:
        allowed = fixed[path]
    else:
        match = re.fullmatch(r"/(account|module|collection|collection-record)/([A-Za-z0-9][A-Za-z0-9_-]{0,127})", path)
        if match is None:
            raise ValueError("Unsupported Asset Panda metadata route")
        allowed = points[match[1]]
        if match[1] == "account" and match[2] != value.account_id:
            raise ValueError("Account is outside this credential's saved scope")
    if set(query) != allowed or any(identifier(v) != v for v in query.values()) or query.get("accountId", value.account_id) != value.account_id:
        raise ValueError("Asset Panda metadata query does not match its scoped route")
    if path == "/collection-records/search":
        if not isinstance(body, dict) or set(body) != {"tenant", "collectionId", "searchInput", "pagination"}:
            raise ValueError("Unsupported Asset Panda search shape")
        search_input = body["searchInput"]
        if not isinstance(search_input, dict):
            raise ValueError("Unsupported Asset Panda selection shape")
        tenant, selection, page = body["tenant"], search_input.get("selection"), body["pagination"]
        if not isinstance(tenant, dict) or set(tenant) != {"accountId", "moduleId"} or tenant["accountId"] != value.account_id:
            raise ValueError("Asset Panda search does not match its saved account")
        identifier(tenant["moduleId"]); identifier(body["collectionId"])
        if not isinstance(selection, dict) or set(selection) != {"matchType", "filters"} or selection["matchType"] != "All" or set(search_input) != {"selection"} or not isinstance(selection["filters"], list) or len(selection["filters"]) != 1:
            raise ValueError("Supply one closed Asset Panda metadata filter")
        condition = selection["filters"][0]
        if not isinstance(condition, dict) or set(condition) != {"field", "operator", "value"} or condition["operator"] not in {"eq", "contains"}:
            raise ValueError("Unsupported Asset Panda metadata comparison")
        metadata_text(condition["field"]); metadata_text(condition["value"])
        if not isinstance(page, dict) or set(page) != {"from", "size"} or type(page["from"]) is not int or not 0 <= page["from"] <= 10000 or type(page["size"]) is not int or not 1 <= page["size"] <= 100:
            raise ValueError("Supply bounded documented Asset Panda pagination")
    elif body is not None:
        raise ValueError("Asset Panda metadata GET does not accept a body")
    try:
        async with guarded_async_client(timeout=12, follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST" if body is not None else "GET", ROOT + path, params=query, **({"json": body} if body is not None else {}), headers=PrivateHeaders({"Access-Key-Id": value.access_key_id, "Access-Key-Secret": value.access_key_secret, "Accept": "application/json", "Cache-Control": "no-store"})) as response:
                if response.status_code != 200:
                    raise ValueError("Asset Panda read refused or service unavailable; permissions and entitlement remain unverified")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("Asset Panda returned an unsupported format")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise ValueError("Asset Panda metadata exceeds the local 2 MiB bound")
        payload = json.loads(raw, object_pairs_hook=unique_json, parse_constant=invalid_number)
        if not isinstance(payload, dict) or "data" not in payload:
            raise ValueError("Asset Panda returned a malformed documented data envelope")
        return payload
    except Exception:
        raise ValueError("Asset Panda metadata read could not be established; inspect access, entitlement or service availability") from None


def rows(payload, *, maximum=MAX_ROWS):
    items = payload.get("data")
    if not isinstance(items, list) or len(items) > maximum or any(not isinstance(v, dict) for v in items):
        raise ValueError("Malformed or oversized Asset Panda data-array envelope")
    ids = [identifier(v.get("id")) for v in items]
    if len(set(ids)) != len(ids):
        raise ValueError("Asset Panda repeated a resource identifier")
    return items


def projection(row, *, include_names=False, column=False):
    if not isinstance(row, dict):
        raise ValueError("Malformed Asset Panda metadata record")
    out = {"id": identifier(row.get("id"))}
    if include_names and "name" in row:
        out["name"] = metadata_text(row["name"])
    if column and "type" in row:
        out["type"] = metadata_text(row["type"], limit=128)
    return out


def inventory(items):
    return {"items": items, "count": len(items), "total": None, "complete": None, "has_more": None, "pagination": "not_documented"}


class AssetPandaNode(WorkflowNode):
    integration_type = "automation-asset-panda"
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="selected accessible account IDs", proves="account", label_keys=("id",))

    @classmethod
    def get_config_model(cls):
        return AssetPandaNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials"):
            config_data = {**config_data, "credentials": guard(config_data["credentials"]).model_dump()}
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials"):
            try:
                config_data = {**config_data, "credentials": guard(config_data["credentials"]).model_dump()}
            except ValueError as error:
                return {"valid": False, "errors": [str(error)], "satisfied_set": None}
        return super().validate_config(config_data)

    @staticmethod
    async def _account(value):
        items = rows(await request(value, "/accounts"))
        if value.account_id not in {identifier(v["id"]) for v in items}:
            raise ValueError("Selected Asset Panda account is absent from the protected membership response")
        return {"id": value.account_id}

    @staticmethod
    async def _module(value, module):
        module = identifier(module)
        items = rows(await request(value, "/modules", params={"accountId": value.account_id}))
        if module not in {identifier(v["id"]) for v in items}:
            raise ValueError("Module is absent from this account's protected module list")
        result = projection((await request(value, "/module/" + module, params={"accountId": value.account_id}))["data"])
        if result["id"] != module:
            raise ValueError("Asset Panda returned a different scoped module")
        return result

    @staticmethod
    async def _collection(value, module, collection, *, include_names=False):
        collection = identifier(collection)
        query = {"accountId": value.account_id, "moduleId": module}
        items = rows(await request(value, "/collections", params=query))
        if collection not in {identifier(v["id"]) for v in items}:
            raise ValueError("Collection is absent from this account/module's protected list")
        result = projection((await request(value, "/collection/" + collection, params=query))["data"], include_names=include_names)
        if result["id"] != collection:
            raise ValueError("Asset Panda returned a different scoped collection")
        return result

    @staticmethod
    async def _columns(value, module, collection):
        return rows(await request(value, "/collection-columns", params={"accountId": value.account_id, "moduleId": module, "collectionId": collection}))

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"module_id", "collection_id", "column_id", "record_id"}:
            return {"options": [], "next_page_token": None}
        if field_name == "record_id":
            raise ValueError("Paste an exact record ID; unfiltered record discovery is not implemented")
        value = guard(credential_data)
        context = context or {}; search = search or ""
        if not isinstance(context, dict) or not isinstance(search, str) or len(search) > 256 or any(ord(c) < 32 for c in search):
            raise ValueError("Supply bounded Asset Panda picker context/search")
        module = identifier(context.get("module_id")) if field_name != "module_id" else None
        collection = identifier(context.get("collection_id")) if field_name == "column_id" else None
        await cls._account(value)
        if module:
            await cls._module(value, module)
        if collection:
            await cls._collection(value, module, collection)
            raw = await cls._columns(value, module, collection)
        elif module:
            raw = rows(await request(value, "/collections", params={"accountId": value.account_id, "moduleId": module}))
        else:
            raw = rows(await request(value, "/modules", params={"accountId": value.account_id}))
        items = [projection(v) for v in raw if search.casefold() in identifier(v.get("id")).casefold()]
        binding = hashlib.sha256(json.dumps({"field": field_name, "module": module, "collection": collection, "search": search, "records": items}, sort_keys=True).encode()).hexdigest()
        key, offset = json.dumps(authority(value)).encode(), 0
        if page_token is not None:
            try:
                if not isinstance(page_token, str) or len(page_token) > 4096:
                    raise ValueError()
                encoded, signature = page_token.rsplit(".", 1); saved = json.loads(encoded)
                if set(saved) != {"binding", "offset"} or saved["binding"] != binding or type(saved["offset"]) is not int or not 0 < saved["offset"] < len(items) or saved["offset"] % 50 or not hmac.compare_digest(signature, hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()):
                    raise ValueError()
                offset = saved["offset"]
            except (ValueError, KeyError, TypeError, AttributeError):
                raise ValueError("Asset Panda local picker continuation no longer matches its current credential, parents, search or ID inventory") from None
        end = offset + 50
        encoded = json.dumps({"binding": binding, "offset": end}, sort_keys=True, separators=(",", ":"))
        token = encoded + "." + hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest() if end < len(items) else None
        return {"options": [{"value": v["id"], "label": v["id"]} for v in items[offset:end]], "next_page_token": token}

    async def execute(self, inputs):
        if not isinstance(self.config, AssetPandaNodeConfig):
            raise ValueError("Asset Panda configuration is required")
        cfg = self.config.config
        if self.config.credentials is None:
            raise ValueError("Connect an Asset Panda access key in the credentials tab")
        value = guard(self.config.credentials.model_dump())
        account = await self._account(value)
        if cfg.operation == "list_accounts":
            return {**inventory([account]), "selected_account_id": value.account_id, "identity": "protected_account_membership", "principal_identity_verified": False, "provider_permissions_verified": False}
        if cfg.operation == "get_account":
            item = projection((await request(value, "/account/" + value.account_id))["data"])
            if item["id"] != value.account_id:
                raise ValueError("Asset Panda returned a different scoped account")
            return item
        if cfg.operation == "list_modules":
            return inventory([projection(v) for v in rows(await request(value, "/modules", params={"accountId": value.account_id}))])
        module = await self._module(value, cfg.module_id)
        if cfg.operation == "get_module":
            return module
        query = {"accountId": value.account_id, "moduleId": cfg.module_id}
        if cfg.operation == "list_collections":
            return inventory([projection(v, include_names=cfg.include_names) for v in rows(await request(value, "/collections", params=query))])
        collection = await self._collection(value, cfg.module_id, cfg.collection_id, include_names=getattr(cfg, "include_names", False))
        if cfg.operation == "get_collection":
            return collection
        query["collectionId"] = cfg.collection_id
        if cfg.operation == "list_collection_columns":
            return inventory([projection(v, include_names=cfg.include_names, column=True) for v in await self._columns(value, cfg.module_id, cfg.collection_id)])
        if cfg.operation == "get_collection_record":
            item = projection((await request(value, "/collection-record/" + cfg.record_id, params=query))["data"])
            if item["id"] != cfg.record_id:
                raise ValueError("Asset Panda returned a different scoped record")
            return item
        if cfg.operation == "search_collection_records":
            columns = await self._columns(value, cfg.module_id, cfg.collection_id)
            column = next((v for v in columns if v["id"] == cfg.column_id), None)
            if column is None:
                raise ValueError("Filter column is absent from the selected current collection")
            body = {"tenant": {"accountId": value.account_id, "moduleId": cfg.module_id}, "collectionId": cfg.collection_id, "searchInput": {"selection": {"matchType": "All", "filters": [{"field": metadata_text(column.get("name")), "operator": cfg.operator, "value": cfg.value}]}}, "pagination": {"from": cfg.offset, "size": cfg.page_size}}
            items = [projection(v) for v in rows(await request(value, "/collection-records/search", body=body), maximum=cfg.page_size)]
            return {"items": items, "count": len(items), "offset": cfg.offset, "page_size": cfg.page_size, "total": None, "has_more": None, "complete": None, "next_cursor": None}
        raise ValueError("Unsupported Asset Panda operation")
