"""BC Laws public CiviX reads backed by the Province's published OpenAPI.

Preserve legislative HTML/XML verbatim and expose metadata from browse/search
XML. No account, writes, webhooks or time-ordered polling API is published.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://www.bclaws.ca/civix"
Aspect = Literal["complete", "corpreg", "bcgaz1", "bcgaz2", "oic", "psl", "ecb", "hscr", "arch_oic"]
Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]


def _operation(name, label):
    return Field(name, title=label, json_schema_extra={"ui:hidden": True, "x-display-name": label})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Aspect(_Input):
    aspect_id: Aspect = Field("complete", title="Collection", description="BC Laws aspect identifier. Complete contains current statutes and regulations.")


class ListContent(_Aspect):
    operation: Literal["list_content"] = _operation("list_content", "Browse Collection")


class ListStatutesAndRegulations(_Input):
    operation: Literal["list_statutes_and_regulations"] = _operation("list_statutes_and_regulations", "Browse Current Laws")


class ListOrdersInCouncil(_Input):
    operation: Literal["list_orders_in_council"] = _operation("list_orders_in_council", "Browse Orders in Council")


class ListCorporateRegistry(_Input):
    operation: Literal["list_corporate_registry"] = _operation("list_corporate_registry", "Browse Corporate Registry")


class ListDirectory(_Aspect):
    operation: Literal["list_directory"] = _operation("list_directory", "Browse Index or Directory")
    directory_id: Identifier = Field(..., title="Index or directory ID", description="CIVIX_DOCUMENT_ID from a browse result, for example statreg.")


class _Document(_Aspect):
    index_id: Identifier = Field(..., title="Index ID", description="CIVIX_INDEX_ID from browse/search, for example statreg.")
    document_id: Identifier = Field(..., title="Document ID", description="CIVIX_DOCUMENT_ID from browse/search, for example 01009_01.")


class GetDocumentHtml(_Document):
    operation: Literal["get_document_html"] = _operation("get_document_html", "Get Document HTML")


class GetDocumentXml(_Document):
    operation: Literal["get_document_xml"] = _operation("get_document_xml", "Get Document XML")


class _Highlighted(_Document):
    search_text: str = Field(..., min_length=1, max_length=2000, title="Highlight search", description='Text or quoted phrase to highlight, for example "protection plan".')

    @field_validator("search_text")
    @classmethod
    def search_value(cls, value):
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use nonempty search text without control characters")
        return value


class GetHighlightedDocumentHtml(_Highlighted):
    operation: Literal["get_highlighted_document_html"] = _operation("get_highlighted_document_html", "Get Highlighted Document HTML")


class GetHighlightedDocumentXml(_Highlighted):
    operation: Literal["get_highlighted_document_xml"] = _operation("get_highlighted_document_xml", "Get Highlighted Document XML")


class SearchDocuments(_Aspect):
    operation: Literal["search_documents"] = _operation("search_documents", "Search Legislation")
    query: str = Field(..., min_length=1, max_length=2000, title="Search query", description="CiviX query expression, for example water.")
    start: int = Field(0, ge=0, title="First hit")
    end: int = Field(20, ge=1, title="Last hit", description="At most 100 hits beyond the first hit. Advance both offsets for the next page.")
    fragment_count: int = Field(5, ge=0, lt=10, title="Snippets per hit")
    fragment_length: int = Field(100, ge=1, lt=200, title="Snippet length")

    @field_validator("query")
    @classmethod
    def search_value(cls, value):
        return _Highlighted.search_value(value)

    @model_validator(mode="after")
    def window(self):
        if not self.start < self.end <= self.start + 100:
            raise ValueError("Last hit must be after first hit and at most 100 hits later")
        return self


Operation = Annotated[Union[
    SearchDocuments, ListContent, ListDirectory, GetDocumentHtml, GetDocumentXml,
    GetHighlightedDocumentHtml, GetHighlightedDocumentXml,
    ListStatutesAndRegulations, ListOrdersInCouncil, ListCorporateRegistry,
], Field(discriminator="operation")]


class BCLawsConfig(NodeConfig[Operation, None]):
    @field_validator("credentials", mode="before")
    @classmethod
    def public_api(cls, value):
        return None if value == {} else value


def _metadata(content, expected_root):
    # DTD/entity declarations are unnecessary in documented metadata. Refuse
    # them before parsing; never expand entities or resolve external resources.
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", content, re.I):
        raise ValueError("BC Laws metadata must not contain DTD or entity declarations")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ValueError("BC Laws did not return readable metadata XML") from exc
    if root.tag != expected_root:
        raise ValueError("BC Laws returned an unexpected metadata envelope")
    items = []
    for element in root:
        if element.tag not in {"index", "dir", "document", "doc"}:
            continue
        # Repeated ancestors, index fields and snippets remain lists. Preserve
        # field names and fragment markup as published, with text for display.
        fields = {}
        for child in element:
            value = ElementTree.tostring(child, encoding="unicode") if len(child) else (child.text or "")
            fields.setdefault(child.tag, []).append(value)
        items.append({"kind": element.tag, "attributes": dict(element.attrib),
                      "fields": {key: values if len(values) > 1 else values[0] for key, values in fields.items()}})
    return items


class BCLawsNode(WorkflowNode):
    integration_type = "automation-bclaws"
    connection_evidence = ConnectionEvidence(operation="list_content", noun="public BC legislation collections", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return BCLawsConfig

    async def execute(self, inputs):
        config = self.config.config
        operation = config.operation
        presets = {"list_statutes_and_regulations": "complete", "list_orders_in_council": "oic", "list_corporate_registry": "corpreg"}
        aspect = presets[operation] if operation in presets else config.aspect_id
        params = {}
        metadata_root = None
        if operation == "list_content" or operation in presets:
            path = f"/content/{aspect}"
            metadata_root = "root"
        elif operation == "list_directory":
            path = f"/content/{aspect}/{quote(config.directory_id, safe='')}"
            metadata_root = "root"
        elif operation == "search_documents":
            path = f"/search/{aspect}/fullsearch"
            params = {"q": config.query, "s": str(config.start), "e": config.end,
                      "nFrag": config.fragment_count, "lFrag": config.fragment_length}
            metadata_root = "results"
        else:
            path = f"/document/id/{aspect}/{quote(config.index_id, safe='')}/{quote(config.document_id, safe='')}"
            if operation.endswith("_xml"):
                path += "/xml"
            if isinstance(config, _Highlighted):
                path += "/search/" + quote(config.search_text, safe="")
        # The published .ca server redirects to the Province's .gov.bc.ca
        # host. The shared guarded client checks public destinations on every hop.
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=True, max_redirects=3) as client:
            response = await client.get(BASE + path, params=params, headers={"Accept": "application/xml, text/xml, text/html"})
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("BC Laws did not return a document or listing")
        if not response.content or len(response.content) > 20_000_000:
            raise ValueError("BC Laws returned empty or oversized content")
        content = response.text
        result = {"status": "success", "operation": operation, "content": content,
                  "content_type": response.headers.get("content-type", ""), "url": str(response.url)}
        if metadata_root:
            result["items"] = _metadata(content, metadata_root)
        return result
