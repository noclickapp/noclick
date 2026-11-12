"""SearchApi Google search actions, pinned to the provider's Google OpenAPI 1.0.0.

Each action is one GET /api/v1/search (searchGoogle). SearchApi offers no
write operation in this contract. Connection checks consume one search credit
and prove key reachability, not ownership of the public search results.
Contract: https://www.searchapi.io/openapi/google.yaml
Docs: https://www.searchapi.io/docs/google
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://www.searchapi.io/api/v1/search"


class SearchApiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="SearchApi Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.searchapi.io/api_key",
            "x-credential-instructions": "Paste the API key from your SearchApi dashboard. Connecting runs one Google search and consumes one search credit. This checks that SearchApi accepts the key; public search results do not identify your account.",
        },
    )
    credential_type: Literal["search_api_api_key"] = Field(
        "search_api_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        title="API Key",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without spaces or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class SearchApiCheckConfig(_Input):
    """Check key reachability using one paid Google search for Google."""

    operation: Literal["check_connection"] = Field(
        "check_connection", json_schema_extra={"ui:hidden": True}
    )


class _Search(_Input):
    q: str = Field(
        ...,
        min_length=1,
        title="Search Query",
        description="Google query, including site:, inurl:, intitle:, AND or OR.",
    )
    page: int = Field(
        1,
        ge=1,
        description="Result page to return. Run again with the next page number to paginate.",
    )
    safe: Literal["active", "blur", "off"] = "blur"
    link: Literal["raw", "resolved"] = Field(
        "raw",
        description="Resolve remaining encrypted Google redirect links (adds latency).",
    )
    optimization_strategy: Literal["performance", "ads"] = "performance"
    nfpr: Literal["0", "1"] = Field(
        "0",
        title="Exclude Spelling Corrections",
        description="1 excludes automatically corrected queries.",
    )
    filter: Literal["0", "1"] = Field("1", title="Duplicate Content Filter")


class SearchApiGoogleConfig(_Search):
    """Search Google's web results with SafeSearch and duplicate filtering."""

    operation: Literal["search_google"] = Field(
        "search_google", json_schema_extra={"ui:hidden": True}
    )
    device: Literal["desktop", "mobile", "tablet"] = "desktop"


class SearchApiRecentConfig(_Search):
    """Find recently published pages within a relative time window."""

    operation: Literal["search_recent"] = Field(
        "search_recent", json_schema_extra={"ui:hidden": True}
    )
    time_period: Literal[
        "last_hour", "last_day", "last_week", "last_month", "last_year"
    ] = "last_week"


class SearchApiDateRangeConfig(_Search):
    """Search pages published within an explicit date range."""

    operation: Literal["search_date_range"] = Field(
        "search_date_range", json_schema_extra={"ui:hidden": True}
    )
    time_period_min: str = Field(
        ...,
        pattern=r"^(0?[1-9]|1[0-2])\/(0?[1-9]|[12][0-9]|3[01])\/(19|20)\d\d$",
        title="Start Date",
        description="MM/DD/YYYY, inclusive start of the search period.",
    )
    time_period_max: str = Field(
        ...,
        pattern=r"^(0?[1-9]|1[0-2])\/(0?[1-9]|[12][0-9]|3[01])\/(19|20)\d\d$",
        title="End Date",
        description="MM/DD/YYYY, end of the search period.",
    )

    @field_validator("time_period_min", "time_period_max")
    @classmethod
    def date(cls, value):
        datetime.strptime(value, "%m/%d/%Y")
        return value

    @model_validator(mode="after")
    def date_order(self):
        if datetime.strptime(self.time_period_min, "%m/%d/%Y") > datetime.strptime(
            self.time_period_max, "%m/%d/%Y"
        ):
            raise ValueError("Start date must not follow end date")
        return self


class SearchApiLocationConfig(_Search):
    """Search from a named geographic location."""

    operation: Literal["search_location"] = Field(
        "search_location", json_schema_extra={"ui:hidden": True}
    )
    location: str = Field(
        ...,
        min_length=1,
        description="Canonical location, such as New York,United States.",
    )


class SearchApiCoordinatesConfig(_Search):
    """Search from a precise latitude and longitude."""

    operation: Literal["search_coordinates"] = Field(
        "search_coordinates", json_schema_extra={"ui:hidden": True}
    )
    latitude: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(..., ge=-180, le=180, allow_inf_nan=False)


class SearchApiCountryConfig(_Search):
    """Localize Google results to a country and optionally restrict their origin."""

    operation: Literal["search_country"] = Field(
        "search_country", json_schema_extra={"ui:hidden": True}
    )
    gl: Literal[
        "af",
        "al",
        "dz",
        "as",
        "ad",
        "ao",
        "ai",
        "aq",
        "ag",
        "ar",
        "am",
        "aw",
        "au",
        "at",
        "az",
        "bs",
        "bh",
        "bd",
        "bb",
        "by",
        "be",
        "bz",
        "bj",
        "bm",
        "bt",
        "bo",
        "ba",
        "bw",
        "bv",
        "br",
        "io",
        "bn",
        "bg",
        "bf",
        "bi",
        "kh",
        "cm",
        "ca",
        "cv",
        "ky",
        "cf",
        "td",
        "cl",
        "cn",
        "cx",
        "cc",
        "co",
        "km",
        "cg",
        "cd",
        "ck",
        "cr",
        "ci",
        "hr",
        "cu",
        "cy",
        "cz",
        "dk",
        "dj",
        "dm",
        "do",
        "ec",
        "eg",
        "sv",
        "gq",
        "er",
        "ee",
        "et",
        "fk",
        "fo",
        "fj",
        "fi",
        "fr",
        "gf",
        "pf",
        "tf",
        "ga",
        "gm",
        "ge",
        "de",
        "gh",
        "gi",
        "gr",
        "gl",
        "gd",
        "gp",
        "gu",
        "gt",
        "gn",
        "gw",
        "gy",
        "ht",
        "hm",
        "va",
        "hn",
        "hk",
        "hu",
        "is",
        "in",
        "id",
        "ir",
        "iq",
        "ie",
        "il",
        "it",
        "jm",
        "jp",
        "jo",
        "kz",
        "ke",
        "ki",
        "kp",
        "kr",
        "kw",
        "kg",
        "la",
        "lv",
        "lb",
        "ls",
        "lr",
        "ly",
        "li",
        "lt",
        "lu",
        "mo",
        "mk",
        "mg",
        "mw",
        "my",
        "mv",
        "ml",
        "mt",
        "mh",
        "mq",
        "mr",
        "mu",
        "yt",
        "mx",
        "fm",
        "md",
        "mc",
        "mn",
        "ms",
        "ma",
        "mz",
        "mm",
        "na",
        "nr",
        "np",
        "nl",
        "nc",
        "nz",
        "ni",
        "ne",
        "ng",
        "nu",
        "nf",
        "mp",
        "no",
        "om",
        "pk",
        "pw",
        "ps",
        "pa",
        "pg",
        "py",
        "pe",
        "ph",
        "pn",
        "pl",
        "pt",
        "pr",
        "qa",
        "re",
        "ro",
        "ru",
        "rw",
        "sh",
        "kn",
        "lc",
        "pm",
        "vc",
        "ws",
        "sm",
        "st",
        "sa",
        "sn",
        "rs",
        "sc",
        "sl",
        "sg",
        "sk",
        "si",
        "sb",
        "so",
        "za",
        "gs",
        "es",
        "lk",
        "sd",
        "sr",
        "sj",
        "sz",
        "se",
        "ch",
        "sy",
        "tw",
        "tj",
        "tz",
        "th",
        "tl",
        "tg",
        "tk",
        "to",
        "tt",
        "tn",
        "tr",
        "tm",
        "tc",
        "tv",
        "ug",
        "ua",
        "ae",
        "uk",
        "gb",
        "us",
        "um",
        "uy",
        "uz",
        "vu",
        "ve",
        "vn",
        "vg",
        "vi",
        "wf",
        "eh",
        "ye",
        "zm",
        "zw",
        "gg",
        "je",
        "im",
        "me",
    ] = Field(..., title="Country", json_schema_extra={"x-enum-searchable": True})
    cr: str | None = Field(
        None,
        title="Document Country Restriction",
        description="Google country restriction, such as countryUS.",
    )


class SearchApiLanguageConfig(_Search):
    """Search with an interface language and optional document-language restriction."""

    operation: Literal["search_language"] = Field(
        "search_language", json_schema_extra={"ui:hidden": True}
    )
    hl: Literal[
        "af",
        "ak",
        "sq",
        "am",
        "ar",
        "hy",
        "az",
        "eu",
        "be",
        "bem",
        "bn",
        "bh",
        "xx-bork",
        "bs",
        "br",
        "bg",
        "km",
        "ca",
        "chr",
        "ny",
        "zh-cn",
        "zh-tw",
        "co",
        "hr",
        "cs",
        "da",
        "nl",
        "xx-elmer",
        "en",
        "eo",
        "et",
        "ee",
        "fo",
        "tl",
        "fi",
        "fr",
        "fy",
        "gaa",
        "gl",
        "ka",
        "de",
        "el",
        "kl",
        "gn",
        "gu",
        "xx-hacker",
        "ht",
        "ha",
        "haw",
        "iw",
        "hi",
        "hu",
        "is",
        "ig",
        "id",
        "ia",
        "ga",
        "it",
        "ja",
        "jw",
        "kn",
        "kk",
        "rw",
        "rn",
        "xx-klingon",
        "kg",
        "ko",
        "kri",
        "ku",
        "ckb",
        "ky",
        "lo",
        "la",
        "lv",
        "ln",
        "lt",
        "loz",
        "lg",
        "ach",
        "mk",
        "mg",
        "my",
        "ms",
        "ml",
        "mt",
        "mv",
        "mi",
        "mr",
        "mfe",
        "mo",
        "mn",
        "sr-me",
        "ne",
        "pcm",
        "nso",
        "no",
        "nn",
        "oc",
        "or",
        "om",
        "ps",
        "fa",
        "xx-pirate",
        "pl",
        "pt",
        "pt-br",
        "pt-pt",
        "pa",
        "qu",
        "ro",
        "rm",
        "nyn",
        "ru",
        "gd",
        "sr",
        "sh",
        "st",
        "tn",
        "crs",
        "sn",
        "sd",
        "si",
        "sk",
        "sl",
        "so",
        "es",
        "es-419",
        "su",
        "sw",
        "sv",
        "tg",
        "ta",
        "tt",
        "te",
        "th",
        "ti",
        "to",
        "lua",
        "tum",
        "tr",
        "tk",
        "tw",
        "ug",
        "uk",
        "ur",
        "uz",
        "vu",
        "vi",
        "cy",
        "wo",
        "xh",
        "yi",
        "yo",
        "zu",
    ] = Field(
        ..., title="Interface Language", json_schema_extra={"x-enum-searchable": True}
    )
    lr: str | None = Field(
        None,
        title="Document Languages",
        pattern=r"^lang_[a-z]{2}(-[A-Z]{2})?(\|lang_[a-z]{2}(-[A-Z]{2})?)*$",
        description="For example lang_en|lang_de.",
    )


class SearchApiMobileConfig(_Search):
    """Inspect Google's mobile search results."""

    operation: Literal["search_mobile"] = Field(
        "search_mobile", json_schema_extra={"ui:hidden": True}
    )


class SearchApiVerbatimConfig(_Search):
    """Search exact keywords without Google's query rewriting."""

    operation: Literal["search_verbatim"] = Field(
        "search_verbatim", json_schema_extra={"ui:hidden": True}
    )


class SearchApiKnowledgeGraphConfig(_Input):
    """Look up a Google Knowledge Graph entity by its identifier."""

    operation: Literal["search_knowledge_graph"] = Field(
        "search_knowledge_graph", json_schema_extra={"ui:hidden": True}
    )
    kgmid: str = Field(
        ...,
        min_length=1,
        description="Google Knowledge Graph ID, for example /m/02_286 (New York).",
    )
    page: int = Field(1, ge=1)


# SearchApi's own MCP server: agents get its tools through a person's SearchApi sign-in.
SearchApiMcpCredential = mcp_credential("search_api", "https://www.searchapi.io/mcp", app="SearchApi")
SearchApiCredential = Union[SearchApiAPIKeyCredential, SearchApiMcpCredential]


SearchApiConfig = Annotated[
    Union[
        SearchApiCheckConfig,
        SearchApiGoogleConfig,
        SearchApiRecentConfig,
        SearchApiDateRangeConfig,
        SearchApiLocationConfig,
        SearchApiCoordinatesConfig,
        SearchApiCountryConfig,
        SearchApiLanguageConfig,
        SearchApiMobileConfig,
        SearchApiVerbatimConfig,
        SearchApiKnowledgeGraphConfig,
    ],
    Field(discriminator="operation"),
]


class SearchApiFullConfig(NodeConfig[SearchApiConfig, SearchApiCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class SearchApiNode(WorkflowNode):
    integration_type = "automation-search-api"
    credential_provider_labels = {"search_api": "SearchApi Account"}
    connection_evidence = ConnectionEvidence(
        noun="SearchApi Google search",
        operation="check_connection",
        proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return SearchApiFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a SearchApi API key")
        config = self.config.config
        params = config.model_dump(exclude={"operation"}, exclude_none=True)
        if config.operation == "check_connection":
            params["q"] = "Google"
        elif config.operation == "search_mobile":
            params["device"] = "mobile"
        elif config.operation == "search_verbatim":
            params["verbatim"] = "true"
        params.update(engine="google", api_key=credential.api_key)
        try:
            async with httpx.AsyncClient(
                timeout=90, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    "GET",
                    BASE_URL,
                    params=params,
                    headers={"Accept": "application/json"},
                )
        except httpx.RequestError:
            # httpx exception text can contain the URL and its secret query key.
            raise ValueError(
                "SearchApi request could not complete; try again"
            ) from None
        try:
            body = response.json()
        except ValueError:
            raise ValueError(
                f"SearchApi returned non-JSON (HTTP {response.status_code})"
            ) from None
        if not isinstance(body, dict):
            raise ValueError("SearchApi returned an unexpected response shape")
        # SearchResponse documents this 200 error string as an empty search,
        # rather than an authentication or request failure.
        empty_search = body.get("error") == "Google didn't return any results."
        if response.status_code != 200 or ("error" in body and not empty_search):
            message = body.get("error")
            if not isinstance(message, str):
                message = f"SearchApi request failed (HTTP {response.status_code})"
            raise ValueError(message.replace(credential.api_key, "[redacted]"))

        # Retain every response section, including empty result sets and pagination.
        # Redact only the submitted key if the provider unexpectedly echoes it.
        def redact(value):
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items() if k != "api_key"}
            if isinstance(value, list):
                return [redact(v) for v in value]
            if isinstance(value, str):
                return value.replace(credential.api_key, "[redacted]")
            return value

        return {"status": "success", "data": redact(body)}
