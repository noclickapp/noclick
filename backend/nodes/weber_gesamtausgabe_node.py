"""WeGA's public REST API, pinned to the provider's OpenAPI 1.1.0.

All fifteen published operations are available without an account or API key.
Dates describe historical documents, not ingestion time; no change trigger is
claimed. Preferences are returned by this request's session, not persisted as
an account connection or carried into later workflow executions.
"""
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://weber-gesamtausgabe.de/api/v1"
DocType = Literal["biblio", "diaries", "documents", "letters", "news", "orgs", "persons", "places", "thematicCommentaries", "var", "works", "writings"]
Text = Annotated[str, Field(min_length=1, max_length=4096)]


def _operation(name, label):
    return Field(name, title=label, json_schema_extra={"ui:hidden": True, "x-display-name": label})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class _Page(_Input):
    offset: int = Field(1, ge=1, description="One-based first result. Add the number of returned items for the next page.")
    limit: int = Field(10, ge=1, le=200, description="Maximum results in this request; no automatic pagination.")


class _DocumentPage(_Page):
    doc_types: list[DocType] | None = Field(None, min_length=1, alias="docType", title="Document types")


class SearchEntities(_DocumentPage):
    operation: Literal["search_entities"] = _operation("search_entities", "Search Entities")
    q: Text | None = Field(None, title="Search query")


class ListDocuments(_DocumentPage):
    operation: Literal["list_documents"] = _operation("list_documents", "List Documents")


class GetDocuments(_Input):
    operation: Literal["get_documents"] = _operation("get_documents", "Get Documents by ID")
    doc_id: Text = Field(..., alias="docID", title="Document ID", description="WeGA ID such as A002068, or the documented WeGA, VIAF, Wikidata or GND URI. Sent as a path value, never fetched as a URL.")


class FindDocumentsByAuthor(_DocumentPage):
    operation: Literal["find_documents_by_author"] = _operation("find_documents_by_author", "Find Documents by Author")
    author_id: Text = Field(..., alias="authorID", title="Author ID")


class FindDocumentsByMention(_DocumentPage):
    operation: Literal["find_documents_by_mention"] = _operation("find_documents_by_mention", "Find Documents by Mention")
    doc_id: Text = Field(..., alias="docID", title="Mentioned document ID")


class FindDocumentsByDate(_DocumentPage):
    operation: Literal["find_documents_by_date"] = _operation("find_documents_by_date", "Find Documents by Date")
    from_date: date = Field(..., alias="fromDate", description="Earliest historical document date (YYYY-MM-DD), not creation time in the API.")
    to_date: date | None = Field(None, alias="toDate", description="Latest historical document date (YYYY-MM-DD).")

    @model_validator(mode="after")
    def date_range(self):
        if self.to_date is not None and self.to_date < self.from_date:
            raise ValueError("End date must be on or after start date")
        return self


class OnThisDay(_DocumentPage):
    operation: Literal["find_on_this_day"] = _operation("find_on_this_day", "Find On This Day Events")
    on_date: date | None = Field(None, alias="date", description="Month/day and latest year for historical events. Omit for the provider's current date.")


class ListRepositories(_Page):
    operation: Literal["list_repositories"] = _operation("list_repositories", "List Repositories")
    city: Text | None = Field(None, description="WeGA city ID, e.g. A130002 (Berlin).")


class ListRepositoryItems(_Page):
    operation: Literal["list_repository_items"] = _operation("list_repository_items", "List Repository Items")
    siglum: Text | None = Field(None, description="RISM siglum, e.g. D-B.")
    term: Text | None = None
    orderby: Literal["idno", "docID", "sortdate", "docType", "title"] | None = Field(None, description="sortdate is the historical item's date, not when WeGA added or updated it.")
    orderdir: Literal["asc", "desc"] | None = None


class FindCodeByElement(_DocumentPage):
    operation: Literal["find_code_by_element"] = _operation("find_code_by_element", "Find XML Code Samples")
    element: Text
    namespace: str = Field("http://www.tei-c.org/ns/1.0", description="XML namespace URI, sent as a filter only.")


class GetFacets(_DocumentPage):
    operation: Literal["get_facets"] = _operation("get_facets", "Get Search Facets")
    facet: Literal["addressee", "authors", "biblioType", "composers", "dedicatees", "docLang", "docSource", "docStatus", "docTypeSubClass", "editors", "facsimile", "forenames", "geonamesFeatureClass", "journals", "keywords", "keywords_biblio", "librettists", "lyricists", "occupations", "persons", "placeOfAddressee", "placeOfSender", "placenames", "places", "pubPlace", "publisher", "repository", "residences", "sender", "series", "sex", "sources-details-cat", "sources-meta-cat", "surnames", "textType", "works", "workTitle"]
    scope: str = Field(..., pattern=r"^(?:indices|A[A-F0-9]{6})$", description="indices or a WeGA document ID.")
    doc_types: list[DocType] = Field(..., min_length=1, alias="docType", title="Document types")
    term: Text | None = None


class GetApplicationStatus(_Input):
    operation: Literal["get_application_status"] = _operation("get_application_status", "Get Application Status")


class CreateDocumentID(_Input):
    operation: Literal["create_document_id"] = _operation("create_document_id", "Create Document ID")
    doc_types: list[DocType] = Field(..., min_length=1, alias="docType", description="Request a fresh ID; this does not create or upload a document.")


class GetPreferences(_Input):
    operation: Literal["get_preferences"] = _operation("get_preferences", "Get Session Preferences")


class SetPreferences(_Input):
    operation: Literal["set_preferences"] = _operation("set_preferences", "Set Session Preferences")
    limit: Literal[10, 25, 50] | None = None
    line_wrap: bool | None = Field(None, alias="line-wrap")
    thematic_commentaries_marker: bool | None = Field(None, alias="thematicCommentaries-marker")
    rdg_marker: bool | None = Field(None, alias="rdg-marker")
    text_const_marker: bool | None = Field(None, alias="textConst-marker")
    supplied_marker: bool | None = Field(None, alias="supplied-marker")
    note_marker: bool | None = Field(None, alias="note-marker")
    model_config = ConfigDict(extra="forbid", populate_by_name=True, json_schema_extra={
        "description": "Set preferences for this HTTP session and return the response. No saved account or browser session is attached; these preferences do not carry into another workflow request.",
    })


WegaConfig = Annotated[Union[SearchEntities, ListDocuments, GetDocuments,
    FindDocumentsByAuthor, FindDocumentsByMention, FindDocumentsByDate, OnThisDay,
    ListRepositories, ListRepositoryItems, FindCodeByElement, GetFacets,
    GetApplicationStatus, CreateDocumentID, GetPreferences, SetPreferences], Field(discriminator="operation")]


class WegaFullConfig(NodeConfig[WegaConfig, None]):
    @field_validator("credentials", mode="before")
    @classmethod
    def public_api(cls, value):
        return None if value == {} else value


# Fixed operations; no caller-controlled method, host or route.
ROUTES = {
    "search_entities": ("GET", "/search/entity"),
    "list_documents": ("GET", "/documents"),
    "get_documents": ("GET", "/documents/{docID}"),
    "find_documents_by_author": ("GET", "/documents/findByAuthor/{authorID}"),
    "find_documents_by_mention": ("GET", "/documents/findByMention/{docID}"),
    "find_documents_by_date": ("GET", "/documents/findByDate"),
    "find_on_this_day": ("GET", "/documents/otd"),
    "list_repositories": ("GET", "/repositories"),
    "list_repository_items": ("GET", "/repositories/items"),
    "find_code_by_element": ("GET", "/code/findByElement/{element}"),
    "get_facets": ("GET", "/facets/{facet}"),
    "get_application_status": ("GET", "/application/status"),
    "create_document_id": ("GET", "/application/newID"),
    "get_preferences": ("GET", "/application/preferences"),
    "set_preferences": ("POST", "/application/preferences"),
}


class WeberGesamtausgabeNode(WorkflowNode):
    integration_type = "automation-weber-gesamtausgabe"
    connection_evidence = ConnectionEvidence(operation="get_application_status", noun="public WeGA API status", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return WegaFullConfig

    async def execute(self, inputs):
        config = self.config.config
        method, path = ROUTES[config.operation]
        params = config.model_dump(mode="json", by_alias=True, exclude={"operation"}, exclude_none=True)
        for key in ("docID", "authorID", "element", "facet"):
            if "{" + key + "}" in path:
                value = params.pop(key)
                # Dot segments are special to HTTP clients even after encoding.
                if value in {".", ".."}:
                    raise ValueError("Use a document ID, URI, element or facet name")
                path = path.replace("{" + key + "}", quote(value, safe=""))
        # Search/list parameters declare form + explode:false. The newID
        # parameter omits explode, so its default is repeated query values.
        if "docType" in params and config.operation != "create_document_id":
            params["docType"] = ",".join(params["docType"])
        kwargs = {"json": params} if method == "POST" else {"params": params}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, headers={"Accept": "application/json"}, **kwargs)
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("WeGA returned a redirect instead of API data")
        body = response.json()
        object_result = config.operation in {"get_application_status", "create_document_id", "get_preferences", "set_preferences"}
        if object_result:
            if not isinstance(body, dict) or "code" in body or "error" in body or "errors" in body:
                raise ValueError("WeGA returned an invalid result or error envelope")
        elif not isinstance(body, list) or any(not isinstance(row, dict) for row in body):
            raise ValueError("WeGA returned an invalid result list")
        result = {"status": "success", "operation": config.operation, "data": body}
        total = response.headers.get("totalrecordcount")
        if total is not None:
            try:
                result["total_record_count"] = int(total)
            except ValueError:
                raise ValueError("WeGA returned an invalid totalrecordcount") from None
        if isinstance(config, _Page):
            result["offset"] = config.offset
            result["limit"] = config.limit
            # With no count header, a full page may have another page; do not
            # claim completion merely because the provider omitted the header.
            next_offset = config.offset + len(body)
            has_more = bool(body) and (next_offset <= result["total_record_count"] if total is not None else len(body) >= config.limit)
            result["next_offset"] = next_offset if has_more else None
        return result
