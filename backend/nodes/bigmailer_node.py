"""BigMailer account, audience and campaign operations from its published v1 API.

Each operation makes one API request and returns the provider JSON unchanged,
including pagination cursors. API keys are sent only to api.bigmailer.io.
"""
from __future__ import annotations

import re
from datetime import date as Date
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.bigmailer.io"
CREDENTIAL_TYPE = "bigmailer_api_key"


class BigmailerApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Bigmailer API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.bigmailer.io/docs/getting-started-api",
            "x-credential-instructions": "Open the API key management page in the BigMailer console, click Create Key, enter a name and copy the key. Paste the key here. NoClick checks it by reading your brands.",
        })
    credential_type: Literal["bigmailer_api_key"] = Field("bigmailer_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API Key", key=True)


class BigmailerFieldValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., title="Field Tag Name", min_length=1)
    string: str | None = None
    integer: int | None = Field(None, strict=True)
    date: Date | None = None

    @model_validator(mode="after")
    def one_value(self):
        if sum(getattr(self, key) is not None for key in ("string", "integer", "date")) != 1:
            raise ValueError("Each field value requires exactly one of string, integer or date")
        return self


class BigmailerVariable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=500)
    value: str = Field(..., max_length=100000)


class _OperationConfig(BaseModel):
    @field_validator("contact_id", "email", mode="before", check_fields=False)
    @classmethod
    def bounded_path_and_email(cls, value, info):
        if info.field_name == "contact_id":
            if not isinstance(value, str) or not value or len(value) > 254 or value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 33 for c in value):
                raise ValueError("Use a contact ID or email address")
        if info.field_name == "email" and value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                raise ValueError("Use a valid email address")
        return value


# method, path, query fields, body fields, required body fields, label.
# No generic URL or body escape hatch: each entry is one published operation.
OPERATIONS = {'list_brands': ('GET', '/v1/brands', ('limit', 'cursor'), (), (), 'List brands'),
 'get_brand': ('GET', '/v1/brands/{brand_id}', (), (), (), 'Get brand'),
 'list_contacts': ('GET',
                   '/v1/brands/{brand_id}/contacts',
                   ('limit', 'cursor', 'list_id'),
                   (),
                   (),
                   'List contacts'),
 'create_contact': ('POST',
                    '/v1/brands/{brand_id}/contacts',
                    ('validate',),
                    ('email', 'field_values', 'list_ids', 'unsubscribe_all', 'unsubscribe_ids'),
                    ('email',),
                    'Create contact'),
 'upsert_contact': ('POST',
                    '/v1/brands/{brand_id}/contacts/upsert',
                    ('validate',),
                    ('email', 'field_values', 'list_ids', 'unsubscribe_all', 'unsubscribe_ids'),
                    ('email',),
                    'Create or update contact'),
 'get_contact': ('GET', '/v1/brands/{brand_id}/contacts/{contact_id}', (), (), (), 'Get contact'),
 'update_contact': ('POST',
                    '/v1/brands/{brand_id}/contacts/{contact_id}',
                    ('field_values_op', 'list_ids_op', 'unsubscribe_ids_op'),
                    ('email', 'field_values', 'list_ids', 'unsubscribe_all', 'unsubscribe_ids'),
                    (),
                    'Update contact'),
 'delete_contact': ('DELETE', '/v1/brands/{brand_id}/contacts/{contact_id}', (), (), (), 'Delete contact'),
 'list_lists': ('GET', '/v1/brands/{brand_id}/lists', ('limit', 'cursor'), (), (), 'List lists'),
 'create_list': ('POST', '/v1/brands/{brand_id}/lists', (), ('name',), ('name',), 'Create list'),
 'get_list': ('GET', '/v1/brands/{brand_id}/lists/{list_id}', (), (), (), 'Get list'),
 'update_list': ('POST', '/v1/brands/{brand_id}/lists/{list_id}', (), ('name',), (), 'Update list'),
 'delete_list': ('DELETE', '/v1/brands/{brand_id}/lists/{list_id}', (), (), (), 'Delete list'),
 'list_fields': ('GET', '/v1/brands/{brand_id}/fields', ('limit', 'cursor'), (), (), 'List fields'),
 'get_field': ('GET', '/v1/brands/{brand_id}/fields/{field_id}', (), (), (), 'Get field'),
 'list_templates': ('GET', '/v1/brands/{brand_id}/templates', ('limit', 'cursor'), (), (), 'List templates'),
 'get_template': ('GET', '/v1/brands/{brand_id}/templates/{template_id}', (), (), (), 'Get template'),
 'list_segments': ('GET', '/v1/brands/{brand_id}/segments', ('limit', 'cursor'), (), (), 'List segments'),
 'get_segment': ('GET', '/v1/brands/{brand_id}/segments/{segment_id}', (), (), (), 'Get segment'),
 'list_bulk_campaigns': ('GET',
                         '/v1/brands/{brand_id}/bulk-campaigns',
                         ('limit', 'cursor'),
                         (),
                         (),
                         'List bulk campaigns'),
 'get_bulk_campaign': ('GET',
                       '/v1/brands/{brand_id}/bulk-campaigns/{campaign_id}',
                       (),
                       (),
                       (),
                       'Get bulk campaign'),
 'list_transactional_campaigns': ('GET',
                                  '/v1/brands/{brand_id}/transactional-campaigns',
                                  ('limit', 'cursor'),
                                  (),
                                  (),
                                  'List transactional campaigns'),
 'get_transactional_campaign': ('GET',
                                '/v1/brands/{brand_id}/transactional-campaigns/{campaign_id}',
                                (),
                                (),
                                (),
                                'Get transactional campaign'),
 'send_transactional_campaign': ('POST',
                                 '/v1/brands/{brand_id}/transactional-campaigns/{campaign_id}/send',
                                 (),
                                 ('email', 'field_values', 'variables'),
                                 ('email',),
                                 'Send a transactional email')}


def _field(name, required=False):
    default = ... if required else None
    title = name.replace("_", " ").title().replace(" Id", " ID")
    if name.endswith("_id") and name != "contact_id":
        kind, options = UUID, {}
    elif name in {"list_ids", "unsubscribe_ids"}:
        kind, options = list[UUID], {}
    elif name == "field_values":
        kind, options = list[BigmailerFieldValue], {}
    elif name == "variables":
        kind, options = list[BigmailerVariable], {}
    elif name == "unsubscribe_all":
        kind, options = bool, {"strict": True}
    elif name == "limit":
        return int, Field(10, ge=1, le=100, title="Page Size")
    elif name == "validate_email":
        kind, options = Literal["true", "false"], {}
    elif name.endswith("_op"):
        kind, options = Literal["add", "remove", "replace"], {}
    elif name == "name":
        kind, options = str, {"min_length": 1, "max_length": 50}
    elif name == "email":
        kind, options = str, {"min_length": 1, "max_length": 100, "json_schema_extra": {"format": "email"}}
    else:
        kind, options = str, {"min_length": 1}
    return (kind if required else kind | None), Field(default, title=title, **options)


def _config(name, spec):
    method, path, query, body, required, label = spec
    path_fields = re.findall(r"\{(\w+)\}", path)
    fields = {("validate_email" if key == "validate" else key):
              _field("validate_email" if key == "validate" else key, key in path_fields or key in required)
              for key in dict.fromkeys((*path_fields, *query, *body))}
    return create_model("Bigmailer" + "".join(word.title() for word in name.split("_")) + "Config",
        __base__=_OperationConfig, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "ui:hidden": True, "x-display-name": label, "x-is-trigger": False,
            "x-category": "Campaigns" if "campaign" in name else "Templates" if "template" in name else "Audience",
        })), **fields)


CONFIG_MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
BigmailerConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Field(discriminator="operation")]


class BigmailerNodeConfig(NodeConfig[BigmailerConfig, BigmailerApiKeyCredential]):
    pass


class BigmailerNode(WorkflowNode):
    integration_type = "automation-bigmailer"
    connection_evidence = ConnectionEvidence(operation="list_brands", noun="brands")
    edit_examples = ["Create or update a BigMailer contact", "Send a BigMailer transactional email",
                     "List BigMailer audiences and campaigns"]

    @classmethod
    def get_config_model(cls):
        return BigmailerNodeConfig

    async def execute(self, inputs):
        if not isinstance(self.config, BigmailerNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a BigMailer API key")
        config = self.config.config
        method, path, query, body_fields, _, _ = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for name in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        params = {}
        for name in query:
            config_key = "validate_email" if name == "validate" else name
            if config_key in values:
                params[name] = values[config_key]
        body = {name: values[name] for name in body_fields if name in values}
        # Never follow redirects with an API key or replay a mutation automatically.
        async with guarded_async_client(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"X-API-Key": self.config.credentials.api_key, "Accept": "application/json"},
                params=params, **({"json": body} if method == "POST" else {}))
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("BigMailer returned an unexpected JSON response")
        if method == "GET" and config.operation.startswith("list_") and not isinstance(result.get("data"), list):
            raise ValueError("BigMailer returned an invalid list response")
        return result
