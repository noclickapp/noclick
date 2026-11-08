"""API.Bible v1: all 19 published text and audio read endpoints.

Contract: https://rest.api.bible/v1/swagger.json (1.6.3).
Authentication: https://docs.api.bible/quick-start/authentication/.
Returns provider JSON intact, including copyright and FUMS metadata. Audio
reads return the provider's metadata/URLs, without downloading audio files.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://rest.api.bible/v1"
ID = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


class ApiBibleApiKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="API.Bible API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.bible/dashboard",
            "x-credential-instructions": "Copy your API key from the top right of your API.Bible dashboard. Access to translations depends on your account's licenses.",
        },
    )
    credential_type: Literal["api_bible_api_key"] = Field("api_bible_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        description="Paste your API.Bible API key. NoClick sends it in the api-key header.",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def header_value(cls, value):
        value = value.strip()
        if not value or re.search(r"\s", value):
            raise ValueError("Paste the API key without whitespace or a header prefix")
        return value


class BibleFilters(BaseModel):
    language: str | None = Field(None, min_length=3, max_length=3, description="ISO 639-3 code, for example eng.")
    abbreviation: str | None = Field(None, title="Abbreviation")
    name: str | None = Field(None, title="Bible Name")
    ids: str | None = Field(None, title="Bible IDs", description="Comma-separated Bible IDs.")
    include_full_details: bool = Field(False, title="Include Full Details")


class ListBibles(BibleFilters):
    operation: Literal["list_bibles"] = Field("list_bibles", title="List Available Bibles", json_schema_extra={"ui:hidden": True})


class BibleResource(BaseModel):
    bible_id: ID = Field(..., title="Bible ID", description="Use an ID returned by List Available Bibles (or List Audio Bibles for audio operations).")


class GetBible(BibleResource):
    operation: Literal["get_bible"] = Field("get_bible", title="Get Bible", json_schema_extra={"ui:hidden": True})


class BookOptions(BaseModel):
    include_chapters: bool = Field(False, title="Include Chapters")


class ListBooks(BibleResource, BookOptions):
    operation: Literal["list_books"] = Field("list_books", title="List Books", json_schema_extra={"ui:hidden": True})
    include_chapters_and_sections: bool = Field(False, title="Include Chapters and Sections")


class BookResource(BibleResource):
    book_id: ID = Field(..., title="Book ID", description="For example GEN. Use an ID returned by List Books.")


class GetBook(BookResource, BookOptions):
    operation: Literal["get_book"] = Field("get_book", title="Get Book", json_schema_extra={"ui:hidden": True})


class ListChapters(BookResource):
    operation: Literal["list_chapters"] = Field("list_chapters", title="List Chapters", json_schema_extra={"ui:hidden": True})


class ContentOptions(BaseModel):
    content_type: Literal["html", "json", "text"] = Field("html", title="Content Format")
    include_notes: bool = Field(False, title="Include Footnotes")
    include_titles: bool = Field(True, title="Include Section Titles")
    include_chapter_numbers: bool = Field(False, title="Include Chapter Numbers")
    include_verse_numbers: bool = Field(True, title="Include Verse Numbers")
    include_verse_spans: bool = Field(False, title="Include Verse Spans")
    parallels: str | None = Field(None, title="Parallel Bible IDs", description="Comma-separated Bible IDs for parallel verses.")


class ChapterResource(BibleResource):
    chapter_id: ID = Field(..., title="Chapter ID", description="For example GEN.1. Use an ID returned by List Chapters.")


class GetChapter(ChapterResource, ContentOptions):
    operation: Literal["get_chapter"] = Field("get_chapter", title="Get Chapter", json_schema_extra={"ui:hidden": True})


class GetPassage(BibleResource, ContentOptions):
    operation: Literal["get_passage"] = Field("get_passage", title="Get Passage", json_schema_extra={"ui:hidden": True})
    passage_id: ID = Field(..., title="Passage ID", description="A verse range, for example GEN.1.1-GEN.2.1.")
    use_org_id: bool = Field(False, title="Use Original Verse IDs")


class ListBookSections(BookResource):
    operation: Literal["list_book_sections"] = Field("list_book_sections", title="List Book Sections", json_schema_extra={"ui:hidden": True})


class ListChapterSections(ChapterResource):
    operation: Literal["list_chapter_sections"] = Field("list_chapter_sections", title="List Chapter Sections", json_schema_extra={"ui:hidden": True})


class GetSection(BibleResource, ContentOptions):
    operation: Literal["get_section"] = Field("get_section", title="Get Section", json_schema_extra={"ui:hidden": True})
    section_id: ID = Field(..., title="Section ID", description="Use an ID returned by List Book Sections or List Chapter Sections.")


class ListVerses(ChapterResource):
    operation: Literal["list_verses"] = Field("list_verses", title="List Verses", json_schema_extra={"ui:hidden": True})


class GetVerse(BibleResource, ContentOptions):
    operation: Literal["get_verse"] = Field("get_verse", title="Get Verse", json_schema_extra={"ui:hidden": True})
    verse_id: ID = Field(..., title="Verse ID", description="For example GEN.1.1. Use an ID returned by List Verses.")
    use_org_id: bool = Field(False, title="Use Original Verse IDs")


class SearchBible(BibleResource):
    operation: Literal["search_bible"] = Field("search_bible", title="Search Bible", description="Return one page of keyword or reference results. Use limit, offset and the returned total for pagination.", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1, title="Search Query", description="Keywords, wildcards (* and ?), or a passage reference.")
    limit: int = Field(10, ge=1, title="Results Per Page")
    offset: int = Field(0, ge=0, title="Result Offset")
    sort: Literal["relevance", "canonical", "reverse-canonical"] = Field("relevance", title="Sort")
    range: str | None = Field(None, title="Passage Ranges", description="Comma-separated passage IDs to limit the search.")
    fuzziness: Literal["AUTO", "0", "1", "2"] = Field("AUTO", title="Fuzziness")


class ListAudioBibles(BibleFilters):
    operation: Literal["list_audio_bibles"] = Field("list_audio_bibles", title="List Audio Bibles", json_schema_extra={"ui:hidden": True})
    related_bible_id: str | None = Field(None, title="Related Text Bible ID", description="Filter by the related text Bible ID.")


class GetAudioBible(BibleResource):
    operation: Literal["get_audio_bible"] = Field("get_audio_bible", title="Get Audio Bible", json_schema_extra={"ui:hidden": True})


class ListAudioBooks(BibleResource, BookOptions):
    operation: Literal["list_audio_books"] = Field("list_audio_books", title="List Audio Books", json_schema_extra={"ui:hidden": True})
    include_chapters_and_sections: bool = Field(False, title="Include Chapters and Sections")


class GetAudioBook(BookResource, BookOptions):
    operation: Literal["get_audio_book"] = Field("get_audio_book", title="Get Audio Book", json_schema_extra={"ui:hidden": True})


class ListAudioChapters(BookResource):
    operation: Literal["list_audio_chapters"] = Field("list_audio_chapters", title="List Audio Chapters", json_schema_extra={"ui:hidden": True})


class GetAudioChapter(ChapterResource):
    operation: Literal["get_audio_chapter"] = Field("get_audio_chapter", title="Get Audio Chapter", json_schema_extra={"ui:hidden": True})


ApiBibleOperation = Annotated[Union[
    ListBibles, GetBible, ListBooks, GetBook, ListChapters, GetChapter, GetPassage,
    ListBookSections, ListChapterSections, GetSection, ListVerses, GetVerse,
    SearchBible, ListAudioBibles, GetAudioBible, ListAudioBooks, GetAudioBook,
    ListAudioChapters, GetAudioChapter,
], Field(discriminator="operation")]


class ApiBibleConfig(NodeConfig[ApiBibleOperation, ApiBibleApiKeyCredential]):
    pass


# Each operation issues exactly one GET, with only its typed query fields.
ROUTES = {
    "list_bibles": "/bibles",
    "get_bible": "/bibles/{bible_id}",
    "list_books": "/bibles/{bible_id}/books",
    "get_book": "/bibles/{bible_id}/books/{book_id}",
    "list_chapters": "/bibles/{bible_id}/books/{book_id}/chapters",
    "get_chapter": "/bibles/{bible_id}/chapters/{chapter_id}",
    "get_passage": "/bibles/{bible_id}/passages/{passage_id}",
    "list_book_sections": "/bibles/{bible_id}/books/{book_id}/sections",
    "list_chapter_sections": "/bibles/{bible_id}/chapters/{chapter_id}/sections",
    "get_section": "/bibles/{bible_id}/sections/{section_id}",
    "list_verses": "/bibles/{bible_id}/chapters/{chapter_id}/verses",
    "get_verse": "/bibles/{bible_id}/verses/{verse_id}",
    "search_bible": "/bibles/{bible_id}/search",
    "list_audio_bibles": "/audio-bibles",
    "get_audio_bible": "/audio-bibles/{bible_id}",
    "list_audio_books": "/audio-bibles/{bible_id}/books",
    "get_audio_book": "/audio-bibles/{bible_id}/books/{book_id}",
    "list_audio_chapters": "/audio-bibles/{bible_id}/books/{book_id}/chapters",
    "get_audio_chapter": "/audio-bibles/{bible_id}/chapters/{chapter_id}",
}


class ApiBibleNode(WorkflowNode):
    integration_type = "automation-api-bible"
    connection_evidence = ConnectionEvidence(noun="available Bibles", operation="list_bibles")

    @classmethod
    def get_config_model(cls):
        return ApiBibleConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an API.Bible API key")
        config = self.config.config
        values = config.model_dump(exclude_none=True)
        route = ROUTES[config.operation]
        path_fields = re.findall(r"\{(\w+)\}", route)
        path = route.format(**{name: quote(values[name], safe="") for name in path_fields})
        params = {}
        for name, value in values.items():
            if name == "operation" or name in path_fields:
                continue
            wire = "bibleId" if name == "related_bible_id" else name.replace("_", "-")
            params[wire] = str(value).lower() if isinstance(value, bool) else value
        # Fixed HTTPS origin; never follow a redirect with the credential.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request("GET", BASE_URL + path, params=params,
                headers={"api-key": self.config.credentials.api_key, "Accept": "application/json"})
        if response.status_code != 200:
            message = "API.Bible did not complete the read"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000].replace(self.config.credentials.api_key, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "status_code": response.status_code, "error": message}
        if "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("API.Bible returned an unexpected content type")
        body = response.json()
        if not isinstance(body, dict) or body.get("error") or "data" not in body:
            raise ValueError("API.Bible returned an invalid JSON envelope")
        expected = list if config.operation.startswith("list_") else dict
        if not isinstance(body["data"], expected):
            raise ValueError("API.Bible returned an invalid data shape")
        return {**body, "status": "success", "operation": config.operation}
