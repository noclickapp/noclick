"""Forgejo PAT metadata reads. Development Swagger/released-instance parity is unverified."""
import ipaddress
import json
import re
from typing import Annotated, Any, Dict, Literal, Union
from urllib.parse import quote, urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.forgejo_credentials import ForgejoCredentialStore, CURRENT_ORGANIZATION
from utils.ssrf import SSRFError, guarded_async_client, normalize_https_origin, allow_private_hosts

MAX_BYTES, MAX_ROWS, MAX_INTEGER = 2 * 1024 * 1024, 100, 2**53 - 1


def _text(value, limit=255):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value) or re.search(r"(?:https?|ssh|sftp)://", value, re.I): raise ValueError("Use bounded text without controls or URLs")
    return value


def _segment(value):
    value = _text(value)
    if value in {".", ".."} or any(c in value for c in "/\\?#%") or value != value.strip(): raise ValueError("Use one unambiguous routing name; encoded paths are unsupported")
    return value


def _integer(value, low=0, high=MAX_INTEGER):
    if type(value) is not int or not low <= value <= high: raise ValueError("Expected exact locally bounded metadata integer")
    return value


def _object(value):
    if not isinstance(value, dict): raise ValueError("Expected documented direct JSON object")
    return value


def _array(value, bound):
    if not isinstance(value, list) or len(value) > bound: raise ValueError("Expected bounded documented bare array")
    return value


def _origin(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError("Use a bounded public HTTPS origin")
    raw = value
    try:
        origin = normalize_https_origin(raw, field_name="Forgejo instance")
        host = urlsplit(origin).hostname
        try: ipaddress.ip_address(host)
        except ValueError: pass
        else: raise ValueError("IP literals are unsupported")
        if not host or "." not in host or host.endswith((".localhost", ".local", ".internal")): raise ValueError("Use one public DNS HTTPS instance")
        return origin
    except (ValueError, SSRFError): raise ValueError("Use one public HTTPS Forgejo origin without path, userinfo, query or fragment") from None


class ForgejoPATCredential(BaseModel):
    model_config = ConfigDict(title="Forgejo Personal Access Token", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://forgejo.org/docs/latest/user/api/usage/", "x-credential-instructions": "Supply an existing PAT for one public HTTPS Forgejo instance. Authorization token header only, fixed /api/v1; no OAuth, refresh, issue, Basic/Bearer/query auth or Gitea fallback. Current-user ID proves authenticated actor, repository access does not prove ownership. Development Swagger/released-instance compatibility and permissions remain unverified."})
    credential_type: Literal["forgejo_pat"] = Field("forgejo_pat", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., repr=False, title="Existing Forgejo Personal Access Token", json_schema_extra={"ui:widget": "password"})
    instance_url: str = Field(..., title="Public HTTPS Forgejo Instance Origin")
    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = _text(value, 4096)
        if any(c.isspace() for c in value): raise ValueError("Supply raw PAT without authentication prefix or whitespace")
        return clean_secret(value, field_name="Forgejo PAT")
    @field_validator("instance_url", mode="before")
    @classmethod
    def instance(cls, value): return _origin(value)


def _credential(raw):
    if isinstance(raw, ForgejoPATCredential): raw = raw.model_dump(mode="json")
    if not isinstance(raw, dict) or raw.get("credential_type") != "forgejo_pat": raise ValueError("Select the authoritative Forgejo PAT family")
    raw = dict(raw)
    if "token_version" in raw and (type(raw["token_version"]) is not int or raw["token_version"] < 1): raise ValueError("Unsupported saved credential version")
    raw.pop("token_version", None); raw.pop("updated_at", None)
    if set(raw) - {"credential_type", "access_token", "instance_url"}: raise ValueError("Unsupported raw PAT/instance grant")
    try: return ForgejoPATCredential.model_validate(raw)
    except Exception: raise ValueError("Forgejo supplied PAT/public instance binding unsupported") from None


def _stored(raw): return _credential(raw).model_dump(mode="json")


class _CurrentCredential(dict):
    def __init__(self, data, store): super().__init__(data); self.store, self.anchor = store, self.identity(store.current)
    @staticmethod
    def identity(row): return tuple(getattr(row, name) for name in ("credential_id", "caller_id", "principal_id", "organization_id", "current_organization", "workflow_id", "owner_id", "credential_type", "token_version"))
    async def reload(self):
        try:
            raw = await self.store.load()
            if self.identity(self.store.current) != self.anchor or _stored(raw) != _stored(self): raise ValueError()
        except Exception: raise ValueError("Forgejo current saved PAT/instance or authority changed") from None
    def __repr__(self): return "<Forgejo current credential>"


def _op(value, title): return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Forgejo Metadata", "x-is-trigger": False})
def _page(title="Page"): return Field(1, strict=True, ge=1, le=2**31 - 1, title=title)


class _Names(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    include_names: bool = Field(False, strict=True, title="Include Routing Names and Titles", description="Opt in to actor login, repository owner/name and issue title. Internal routing witnesses remain private; no profile, body or capability output.")


class ForgejoUserConfig(_Names):
    operation: Literal["get_user"] = _op("get_user", "Get Authenticated Actor ID")


class ForgejoRepositoriesConfig(_Names):
    operation: Literal["list_repositories"] = _op("list_repositories", "List Accessible Repository Metadata")
    page: int = _page()
    limit: int = Field(20, strict=True, ge=1, le=MAX_ROWS, title="Local Page Limit", description="Documented numeric limit; instance cap/default unknown. No automatic completion inference.")


class _Repository(_Names):
    owner: str = Field(..., title="Selected Repository Owner Routing Name", json_schema_extra={"x-resource-type": "owner", "x-dynamic-options": {"field_name": "owner", "depends_on": ["repo_catalog_page", "limit", "include_names"], "allow_custom": True, "auto_select_sole_option": False}})
    repo_name: str = Field(..., title="Selected Repository Routing Name", json_schema_extra={"x-resource-type": "repo_name", "x-dynamic-options": {"field_name": "repo_name", "depends_on": ["owner", "repo_catalog_page", "limit", "include_names"], "allow_custom": True, "auto_select_sole_option": False}})
    repo_catalog_page: int = _page("Current Repository Catalog Page for Ancestry")
    limit: int = Field(20, strict=True, ge=1, le=MAX_ROWS, title="Local Page Limit")
    @field_validator("owner", "repo_name", mode="before")
    @classmethod
    def routing_names(cls, value): return _segment(value)


class ForgejoRepositoryConfig(_Repository):
    operation: Literal["get_repository"] = _op("get_repository", "Get Selected Repository Metadata")


class ForgejoIssuesConfig(_Repository):
    operation: Literal["list_issues"] = _op("list_issues", "List Selected Repository Issues")
    state: Literal["open", "closed", "all"] = Field("open", title="Issue State Filter")
    page: int = _page("Issue Catalog Page")


class ForgejoIssueConfig(ForgejoIssuesConfig):
    operation: Literal["get_issue"] = _op("get_issue", "Get Selected Issue Metadata")
    issue_index: int = Field(..., strict=True, ge=1, le=MAX_INTEGER, title="Issue Number in Selected Repository", json_schema_extra={"x-resource-type": "issue_index", "x-dynamic-options": {"field_name": "issue_index", "depends_on": ["owner", "repo_name", "repo_catalog_page", "limit", "include_names", "state", "page"], "allow_custom": True, "auto_select_sole_option": False}})
    @field_validator("issue_index", mode="before")
    @classmethod
    def selected_index(cls, value):
        if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,15}", value): value = int(value)
        return _integer(value, 1)


ForgejoOperation = Annotated[Union[ForgejoUserConfig, ForgejoRepositoriesConfig, ForgejoRepositoryConfig, ForgejoIssuesConfig, ForgejoIssueConfig], Field(discriminator="operation")]
class ForgejoNodeConfig(NodeConfig[ForgejoOperation, ForgejoPATCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _actor(raw):
    row = _object(raw)
    return _integer(row.get("id"), 1), _segment(row.get("login"))


def _repository(raw, names=False):
    row = _object(raw); anchor = (_integer(row.get("id"), 1), _segment(_object(row.get("owner")).get("login")), _segment(row.get("name")))
    if "full_name" in row and _text(row["full_name"], 511) != anchor[1] + "/" + anchor[2]: raise ValueError("Returned repository routing fields disagree")
    out = {"id": anchor[0]}
    for field in ("private", "archived", "fork", "mirror", "empty"):
        if field in row:
            if type(row[field]) is not bool: raise ValueError("Expected documented repository boolean")
            out[field] = row[field]
    for field in ("open_issues_count", "stars_count", "forks_count", "watchers_count", "size"):
        if field in row: out[field] = _integer(row[field])
    for field in ("created_at", "updated_at"):
        if field in row: out[field] = _text(row[field], 128)
    if names: out.update(owner=anchor[1], name=anchor[2])
    return out, anchor


def _issue(raw, parent, names=False):
    row = _object(raw)
    if row.get("pull_request") is not None: raise ValueError("Pull-request records are excluded")
    out = {"id": _integer(row.get("id"), 1), "number": _integer(row.get("number"), 1)}
    if "repository" in row:
        meta = _object(row["repository"])
        expected = {"id": parent[0], "owner": parent[1], "name": parent[2], "full_name": parent[1] + "/" + parent[2]}
        for field, value in expected.items():
            if field in meta and (type(meta[field]) is not type(value) or meta[field] != value): raise ValueError("Returned issue repository metadata crosses protected ancestry")
    if "state" in row: out["state"] = _text(row["state"], 32)
    if "is_locked" in row:
        if type(row["is_locked"]) is not bool: raise ValueError("Expected documented issue boolean")
        out["is_locked"] = row["is_locked"]
    for field in ("created_at", "updated_at", "closed_at"):
        if field in row: out[field] = _text(row[field], 128)
    if names and "title" in row: out["title"] = _text(row["title"], 512)
    return out


def _pagination(headers, page, limit, count, repository=False):
    total = headers.get("x-total-count")
    if total is not None:
        if not isinstance(total, str) or not re.fullmatch(r"[0-9]{1,16}", total): raise ValueError("Unsupported total-count header")
        total = _integer(int(total))
        if total < count: raise ValueError("Inconsistent current-page total")
    return {"returned_count": count, "requested_page": page, "requested_limit": limit, "reported_total": total, "count_scope": "repository_header" if repository and total is not None else "issue_header_when_present" if total is not None else "unknown", "link_header_present": "link" in headers, "has_more": None, "next_page_token": None, "pagination_complete": None}


class _ProviderError(Exception):
    def __init__(self, result): self.result = result


class _Session:
    def __init__(self, raw, config): self.raw, self.key, self.config, self.attempted, self.status = raw, _credential(raw), config, False, None
    def error(self, message): return {"status": "error", "action": self.config.operation, "error": message, "executed": self.attempted, "mutation_attempted": False, "_halt_downstream": True, **({"http_status": self.status} if self.status is not None else {})}
    async def request(self, kind, page=None):
        params = {}
        if kind == "user": path = "/api/v1/user"
        elif kind == "repositories": path = "/api/v1/user/repos"; params = {"page": str(_integer(page, 1, 2**31 - 1)), "limit": str(self.config.limit)}
        elif kind in {"repository", "issues", "issue"}:
            path = "/api/v1/repos/" + quote(_segment(self.config.owner), safe="") + "/" + quote(_segment(self.config.repo_name), safe="")
            if kind in {"issues", "issue"}: path += "/issues"
            if kind == "issues": params = {"type": "issues", "state": self.config.state, "page": str(_integer(page, 1, 2**31 - 1)), "limit": str(self.config.limit)}
            if kind == "issue": path += "/" + str(self.config.issue_index)
        else: raise ValueError("Closed Forgejo metadata route required")
        try:
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            key = _credential(self.raw); self.status = None
            if allow_private_hosts(): raise ValueError("Forgejo requires the public-only outbound policy")
            async with guarded_async_client(timeout=20, follow_redirects=False, trust_env=False) as client:
                self.attempted = True
                async with client.stream("GET", key.instance_url + path, params=params, headers={"Authorization": "token " + key.access_token, "Accept": "application/json"}) as response:
                    self.status = response.status_code; headers = response.headers; body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES: raise ValueError("Forgejo response exceeds local bound")
                        body.extend(chunk)
            if isinstance(self.raw, _CurrentCredential): await self.raw.reload()
            if self.status != 200:
                reason = "Forgejo authentication failed (HTTP401)" if self.status == 401 else "Forgejo metadata is missing-or-invisible (HTTP404)" if self.status == 404 else "Forgejo protected metadata read could not be verified"
                raise _ProviderError(self.error(reason + "; permissions and instance compatibility remain unknown. Private provider bodies omitted; no retry"))
            if "application/json" not in headers.get("content-type", "").lower(): raise ValueError("Expected documented JSON representation")
            return json.loads(body), headers
        except (httpx.HTTPError, SSRFError): raise _ProviderError(self.error("Forgejo transport outcome unknown; no retry")) from None
    async def actor(self): return _actor((await self.request("user"))[0])
    async def repositories(self, page):
        raw, headers = await self.request("repositories", page); rows = _array(raw, self.config.limit)
        parsed = [_repository(row, self.config.include_names) for row in rows]
        anchors = [anchor for _, anchor in parsed]
        if len({a[0] for a in anchors}) != len(anchors) or len({a[1:] for a in anchors}) != len(anchors): raise ValueError("Ambiguous current repository catalog")
        return {"data": [row for row, _ in parsed], **_pagination(headers, page, self.config.limit, len(rows), repository=True)}, anchors
    async def repository(self):
        _, anchors = await self.repositories(self.config.repo_catalog_page)
        selected = [a for a in anchors if a[1:] == (self.config.owner, self.config.repo_name)]
        if len(selected) != 1: raise ValueError("Selected repository not established on current protected catalog page; global absence unknown")
        data, anchor = _repository((await self.request("repository"))[0], self.config.include_names)
        if anchor != selected[0]: raise ValueError("Repository detail differs from current catalog ancestry")
        return data, anchor
    async def issues(self, parent):
        raw, headers = await self.request("issues", self.config.page)
        rows = [_issue(row, parent, self.config.include_names) for row in _array(raw, self.config.limit)]
        if len({r["id"] for r in rows}) != len(rows) or len({r["number"] for r in rows}) != len(rows): raise ValueError("Ambiguous current issue catalog")
        return {"data": rows, **_pagination(headers, self.config.page, self.config.limit, len(rows))}


class ForgejoNode(WorkflowNode):
    integration_type = "automation-forgejo"
    credential_provider_labels = {"forgejo": "Forgejo Account"}
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="get_user", identity_operation="get_user", noun="Forgejo authenticated actor ID", label_keys=("id",), identity_keys=("id",), proves="account")
    edit_examples = ["Read my Forgejo actor ID and accessible repository status without profile data", "Read a selected repository's ordinary issue IDs and state without bodies or pull requests"]
    @classmethod
    def get_config_model(cls): return ForgejoNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: _stored(config_data["credentials"])
            except ValueError as error: raise ConfigValidationError(str(error)) from None
        return super().parse_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._load_current_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
    @classmethod
    async def _load_current_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        _credential(credential_data)
        if not credential_id: return credential_data
        organization = organization_id
        if organization is None and not workflow_id: organization = CURRENT_ORGANIZATION
        store = ForgejoCredentialStore(pool, user_id, credential_id, credential_type="forgejo_pat", validate=_stored, organization_id=organization, workflow_id=workflow_id)
        try: return _CurrentCredential(await store.load(), store)
        except Exception: raise ValueError("Forgejo saved PAT unavailable under current authority") from None
    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        try: _stored(credential_data)
        except ValueError: return {"valid": False, "error": "Forgejo literal PAT/public-instance family unsupported"}
        if validation_context is None: return {"valid": True, "provider_verified": False}
        await validation_context.revalidate(); result = await validation_context.run_operation("get_user"); await validation_context.revalidate()
        if result.get("status") == "success" and result.get("protected_authentication_verified") is True: return {"valid": True, "provider_verified": True}
        return {"valid": False if result.get("http_status") == 401 else None, "error": result.get("error", "Current actor authentication could not be verified")}
    @classmethod
    async def _dispatch(cls, credential, config):
        session = _Session(credential, config)
        try:
            actor = await session.actor()
            if config.operation == "get_user": out = {"data": {"id": actor[0], **({"login": actor[1]} if config.include_names else {})}}
            elif config.operation == "list_repositories": out, _ = await session.repositories(config.page)
            elif config.operation in {"get_repository", "list_issues", "get_issue"}:
                parent_data, parent = await session.repository()
                if config.operation == "get_repository": out = {"data": parent_data}
                else:
                    catalog = await session.issues(parent)
                    if config.operation == "list_issues": out = catalog
                    else:
                        matches = [row for row in catalog["data"] if row["number"] == config.issue_index]
                        if len(matches) != 1: raise ValueError("Issue not established on current repository page; no global absence claim")
                        data = _issue((await session.request("issue"))[0], parent, config.include_names)
                        if (data["id"], data["number"]) != (matches[0]["id"], matches[0]["number"]): raise ValueError("Issue detail differs from current route/catalog witness")
                        current = await session.issues(parent)
                        if not any((r["id"], r["number"]) == (data["id"], data["number"]) for r in current["data"]): raise ValueError("Issue left current selected repository page")
                        out = {"data": data}
                status = session.status
                if (await session.repository())[1] != parent: raise ValueError("Repository ancestry changed during metadata read")
                session.status = status
            else: raise ValueError("Closed native operation required")
            status = session.status
            if await session.actor() != actor: raise ValueError("Authenticated actor changed during read")
            session.status = status
            if session.key.access_token in json.dumps(out, ensure_ascii=False, allow_nan=False): raise ValueError("Output contains credential material")
            return {"status": "success", "action": config.operation, "executed": True, "http_status": session.status, "mutation_attempted": False, "snapshot_stable": False, "protected_authentication_verified": True, "principal_identity_proven": True, "repository_ownership_proven": False, **out}
        except _ProviderError as error: return error.result
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError): return session.error("Current credentials/actor/catalog ancestry or bounded published metadata could not be established; no raw fallback/retry")
    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        _credential(credential_data); context = context or {}
        if field_name not in {"owner", "repo_name", "issue_index"}: raise ValueError("Select a native repository or issue field")
        if field_name in {"owner", "repo_name"} and context.get("include_names") is not True: return {"options": [], "has_more": None, "next_page_token": None, "message": "Enable Include Routing Names and Titles to reveal repository routing names, or enter a known name"}
        if field_name == "repo_name" and not context.get("owner"): raise ValueError("Select protected current repository owner routing name first")
        page = context.get("page", 1) if field_name == "issue_index" else context.get("repo_catalog_page", 1)
        if page_token is not None:
            if not isinstance(page_token, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", page_token): raise ValueError("Use a bounded numeric manual page; returned URLs are never followed")
            page = _integer(int(page_token), 1, 2**31 - 1)
        if search is not None: _text(search, 100)
        args = {"include_names": context.get("include_names", False), "limit": context.get("limit", 20), "page": page}
        if field_name == "issue_index":
            if not context.get("owner") or not context.get("repo_name"): raise ValueError("Select a protected current repository first")
            config = ForgejoIssuesConfig(**args, owner=context["owner"], repo_name=context["repo_name"], repo_catalog_page=context.get("repo_catalog_page", 1), state=context.get("state", "open"))
        else: config = ForgejoRepositoriesConfig(**args)
        result = await cls._dispatch(credential_data, config)
        if result.get("status") != "success": raise ValueError(result["error"])
        rows = result["data"]
        if field_name == "repo_name": rows = [r for r in rows if r["owner"] == _segment(context["owner"])]
        if field_name == "owner": options = [{"value": owner, "label": owner, "metadata": {"protected_catalog": True, "ownership_proven": False}} for owner in sorted({r["owner"] for r in rows})]
        else: options = [{"value": str(r["number"]) if field_name == "issue_index" else r["name"], "label": r.get("title", str(r["number"])) if field_name == "issue_index" else r["name"], "metadata": {"id": r["id"], "protected_catalog": True, "ownership_proven": False}} for r in rows]
        return {"options": [r for r in options if not search or search.casefold() in r["label"].casefold() or search.casefold() in r["value"].casefold()], "has_more": None, "next_page_token": None}
    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        raw = self.node_data.get("credentials") if self.node_data.get("credentials") is not None else self.config.credentials
        initial = _credential(raw)
        credential = await self._load_current_credential(initial.model_dump(mode="json"), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data["credential_id"], workflow_id=self.workflow_id, organization_id=self.organization_id) if self.node_data.get("credential_id") else initial
        return await self._dispatch(credential, self.config.config)
