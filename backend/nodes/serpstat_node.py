"""Serpstat v4: closed SEO reads, account credit metadata and existing results.

Query-token authentication is documented by the current official OpenAPI.
Real analytical calls consume credits; no sandbox, launches or generic methods.
"""
from __future__ import annotations
import base64
import hashlib
import json
import logging
import math
import re
from contextvars import ContextVar
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote, quote_plus
from uuid import uuid4
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, ValidationResult, WorkflowNode, runtime_config_view
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence

NODE_TYPE = "automation-serpstat"
FAMILIES = ("serpstat_api_token",)
API_URL = "https://api.serpstat.com/v4"
SEARCH_ENGINES = ["g_af","g_al","g_dz","g_as","g_ad","g_ao","g_ai","g_ag","g_ar","g_am","g_aw","g_au","g_at","g_az","g_bh","g_bd","g_bb","g_by","g_be","g_bz","g_bj","g_bm","g_bt","g_bo","g_ba","g_bw","g_br","g_io","g_vg","g_bn","g_bg","g_bf","g_bi","g_kh","g_cm","g_ca","g_cv","g_ky","g_cf","g_td","g_cl","g_cn","g_cx","g_сс","g_co","g_km","g_ck","g_cr","g_ci","g_hr","g_cw","g_cy","g_cz","g_cd","g_dk","g_dj","g_dm","g_do","g_ec","g_eg","g_sv","g_gq","g_er","g_ee","g_et","g_fk","g_fo","g_fm","g_fj","g_fi","g_fr","g_gf","g_pf","g_ga","g_ge","g_de","g_gh","g_gi","g_gr","g_gl","g_gd","g_gp","g_gu","g_gt","g_gg","g_gn","g_gw","g_gy","g_ht","g_hn","g_hk","g_hu","g_is","g_in","g_id","g_iq","g_ie","g_im","g_il","g_it","g_jm","g_jp","g_je","g_jo","g_kz","g_ke","g_ki","g_kw","g_kg","g_la","g_lv","g_lb","g_ls","g_lr","g_ly","g_li","g_lt","g_lu","g_mo","g_mk","g_mg","g_mw","g_my","g_mv","g_ml","g_mt","g_mh","g_mq","g_mr","g_mu","g_yt","g_mx","g_md","g_mc","g_mn","g_me","g_ms","g_ma","g_mz","g_mm","g_na","g_nr","g_np","g_nl","g_nc","g_nz","g_ni","g_ne","g_ng","g_nu","g_nf","g_mp","g_no","g_om","g_pk","g_pw","g_ps","g_pa","g_pg","g_py","g_pe","g_ph","g_pn","g_pl","g_pt","g_pr","g_qa","g_cg","g_re","g_ro","g_ru","g_rw","g_sh","g_kn","g_lc","g_pm","g_vc","g_ws","g_sm","g_st","g_sa","g_sn","g_rs","g_sc","g_sl","g_sg","g_sx","g_sk","g_si","g_sb","g_so","g_za","g_kr","g_es","g_lk","g_sr","g_sz","g_se","g_ch","g_tw","g_tj","g_tz","g_th","g_bs","g_gm","g_tl","g_tg","g_tk","g_to","g_tt","g_tn","g_tr","g_tm","g_tc","g_tv","g_vi","g_ug","g_ua","g_ae","g_uk","g_us","g_uy","g_uz","g_vu","g_va","g_ve","g_vn","g_wf","g_ye","g_zm","g_zw","bing_us"]
CONTRACTS = json.loads(r'''{"SerpstatLimitsProcedure.getStats":{"type":"object","properties":{"data":{"type":"object","properties":{"max_lines":{"type":"integer"},"used_lines":{"type":"integer"},"left_lines":{"type":"integer"},"user_info":{"type":"object","properties":{"user_id":{"type":"string"}},"required":["user_id"]},"plugin_limits":{"type":"object","properties":{"hasApiPlugin":{"type":"boolean"},"delayBetweenRequests":{"type":"integer"},"total":{"type":"integer"},"used":{"type":"integer"},"left":{"type":"integer"}},"required":["hasApiPlugin","delayBetweenRequests","total","used","left"]}},"required":["max_lines","used_lines","left_lines","user_info","plugin_limits"]},"summary_info":{"type":"object","properties":{"left_lines":{"type":"integer"}},"required":["left_lines"]}},"required":["data","summary_info"]},"ProjectProcedure.getProjects":{"type":"object","properties":{"data":{"type":"array","items":{"type":"object","properties":{"project_id":{"type":"string"},"project_name":{"type":"string"},"domain":{"type":"string"},"created_at":{"type":"string"},"type":{"type":"string"}},"required":["project_id","project_name","domain","created_at","type"]}},"summary_info":{"type":"object","properties":{"page":{"type":"integer"},"page_total":{"type":"integer"},"count":{"type":"integer"},"total":{"type":"integer"}},"required":["page","page_total","count","total"]}},"required":["data","summary_info"]},"RtApiProjectProcedure.getProjects":{"type":"object","properties":{"data":{"type":"array","items":{"type":"object","properties":{"id":{"type":"string"},"projectName":{"type":"string"},"domain":{"type":"string"},"createdAt":{"type":"string"},"type":{"type":"string"},"status":{"type":"integer"},"enableTracking":{"type":"boolean"}},"required":["id","projectName","domain","createdAt","type","status","enableTracking"]}},"summary_info":{"type":"object","properties":{"page":{"type":"integer"},"page_total":{"type":"integer"},"count":{"type":"integer"},"total":{"type":"integer"}},"required":["page","page_total","count","total"]}},"required":["data","summary_info"]},"RtApiSearchEngineProcedure.getProjectRegions":{"type":"object","properties":{"projectId":{"type":"integer"},"regions":{"type":"array","items":{"type":"object","properties":{"id":{"type":"integer"},"active":{"type":"boolean"},"serpType":{"type":"string"},"deviceType":{"type":"string"},"searchEngine":{"type":"string"},"region":{"type":"string"},"country":{"type":"string"},"city":{"type":"string"},"langCode":{"type":"string"}},"required":[]}},"spent_limits":{"type":"integer"}},"required":[]},"RtApiProjectProcedure.getProjectStatus":{"type":"object","properties":{"projectId":{"type":"integer"},"automaticParsing":{"type":"boolean"},"lastParsingDate":{"type":"string"},"regionId":{"type":"integer"},"parsing":{"type":"boolean"}},"required":["projectId","regionId","parsing"]},"RtApiProcedure.getProjectKeywords":{"type":"object","properties":{"data":{"type":"array","items":{"type":"object","properties":{"id":{"type":"integer"},"keyword_id":{"type":"integer"},"value":{"type":"string"},"added":{"type":"string"},"region":{"type":"array","items":{"type":"object","properties":{"status":{"type":"integer","enum":[0,1,2]},"region_id":{"type":"integer"}},"required":[]}}},"required":[]}},"summary_info":{"type":"object","properties":{"current_page":{"type":"integer","minimum":1},"size":{"type":"integer","minimum":1},"pages_count":{"type":"integer","minimum":1,"maximum":1000},"total_data":{"type":"integer"},"sort":{"type":"string","enum":["added","alpha"]},"order":{"type":"string","enum":["asc","desc"]}},"required":[]},"spent_limits":{"type":"integer"},"left_limits":{"type":"integer"}},"required":[]},"SerpstatDomainProcedure.getDomainsInfo":{"type":"object","properties":{"data":{"type":"array","items":{"type":"object","properties":{"domain":{"type":"string"},"keywords":{"type":"integer"},"traff":{"type":"integer"},"new_keywords":{"type":"integer"},"out_keywords":{"type":"integer"},"rised_keywords":{"type":"integer"},"down_keywords":{"type":"integer"},"ad_keywords":{"type":"integer"},"ads":{"type":"integer"},"prev_date":{"type":"string"},"traffic_ai":{"type":"integer"},"aio_keywords":{"type":"integer"},"aio_citations":{"type":"integer"}},"required":[]}},"summary_info":{"type":"object","properties":{"page":{"type":"integer"},"left_lines":{"type":"integer"}},"required":[]}},"required":[]},"SerpstatDomainProcedure.getDomainsHistory":{"type":"object","properties":{"data":{"type":"array","items":{"type":"object","properties":{"domain":{"type":"string"},"keywords":{"type":"integer"},"traff":{"type":"integer"},"visible_static":{"type":"number"},"new_keywords":{"type":"integer"},"out_keywords":{"type":"integer"},"rised_keywords":{"type":"integer"},"down_keywords":{"type":"integer"},"ad_keywords":{"type":"integer"},"ads":{"type":"integer"},"date":{"type":"string"},"aio_keywords":{"type":"integer"},"aio_citations":{"type":"integer"}},"required":["domain","keywords","traff","visible_static","new_keywords","out_keywords","rised_keywords","down_keywords","ad_keywords","ads","date","aio_keywords","aio_citations"]}},"summary_info":{"type":"object","properties":{"page":{"type":"integer"},"total":{"type":"integer"},"left_lines":{"type":"integer"}},"required":["page","total","left_lines"]}},"required":["data","summary_info"]},"SerpstatDomainProcedure.getDomainKeywords":{"type":"object","properties":{"data":{"type":"array","items":{"type":"object","properties":{"subdomain":{"type":"string"},"domain":{"type":"string"},"keyword":{"type":"string"},"position":{"type":"integer"},"cost":{"type":"number"},"concurrency":{"type":"integer"},"region_queries_count":{"type":"integer"},"traff":{"type":"integer"},"difficulty":{"type":"integer"},"dynamic":{"type":"integer"}},"required":["subdomain","domain","keyword","position","cost","concurrency","region_queries_count","traff","difficulty","dynamic"]}},"summary_info":{"type":"object","properties":{"page":{"type":"integer"},"total":{"type":"integer"},"left_lines":{"type":"integer"}},"required":["page","total","left_lines"]}},"required":[]},"SerpstatDomainProcedure.getOrganicCompetitorsPage":{"type":"object","properties":{"data":{"type":"array","items":{"type":"object","properties":{"domain":{"type":"string"},"all":{"type":"object","properties":{"currentValue":{"type":["integer"]},"dynamicValue":{"type":["integer"]}},"required":["currentValue","dynamicValue"]},"common":{"type":"object","properties":{"currentValue":{"type":["integer"]},"dynamicValue":{"type":["integer","number"]}},"required":["currentValue","dynamicValue"]},"visibility":{"type":"object","properties":{"currentValue":{"type":"number"},"dynamicValue":{"type":"number"}},"required":["currentValue","dynamicValue"]},"missing":{"type":"integer"},"relevance":{"type":"number"},"our_relevance":{"type":"number"},"traff":{"type":"integer"}},"required":["domain","all","common","visibility","missing","relevance"]}},"summary_info":{"type":"object","properties":{"page":{"type":"integer"},"left_lines":{"type":"integer"}},"required":["page","left_lines"]}},"required":[]},"SerpstatKeywordProcedure.getKeywordsInfo":{"type":"object","properties":{"data":{"type":"array","items":{"type":"object","properties":{"keyword":{"type":"string"},"cost":{"type":["number"]},"concurrency":{"type":"integer"},"found_results":{"type":"integer"},"region_queries_count":{"type":"integer"},"region_queries_count_wide":{"type":"integer"},"right_spelling":{"type":"string","nullable":true},"lang":{"type":"string"},"difficulty":{"type":"integer"},"suggestions_count":{"type":"integer"},"keywords_count":{"type":"integer"}},"required":["keyword","cost","concurrency","found_results","region_queries_count","region_queries_count_wide","right_spelling","lang","difficulty","suggestions_count","keywords_count"]}},"summary_info":{"type":"object","properties":{"page":{"type":"integer"},"left_lines":{"type":"integer"}},"required":["page","left_lines"]},"not_found":{"type":"array","items":{"type":"string"}}},"required":["data","summary_info"]},"SerpstatKeywordProcedure.getRelatedKeywords":{"type":"object","properties":{"data":{"type":"array","items":{"type":"object","properties":{"keyword":{"type":"string"},"region_queries_count":{"type":"integer"},"cost":{"type":"number"},"concurrency":{"type":"integer"},"right_spelling":{"type":"string","nullable":true},"weight":{"type":"integer"},"difficulty":{"type":"integer"}},"required":["keyword","region_queries_count","cost","concurrency","right_spelling","weight","difficulty"]}},"summary_info":{"type":"object","properties":{"page":{"type":"integer"},"total":{"type":"integer"},"left_lines":{"type":"integer"}},"required":["page","total","left_lines"]}},"required":[]},"SerpstatKeywordProcedure.getKeywordTrends":{"type":"object","properties":{"data":{"type":"array","items":{"type":"object","properties":{"keyword":{"type":"string"},"current_volume":{"type":"integer","nullable":true},"yoy_change_pct":{"type":"number","nullable":true},"trend":{"type":"string","enum":["growing","declining","stable"],"nullable":true},"peak_month":{"type":"string","nullable":true},"trough_month":{"type":"string","nullable":true},"monthly":{"type":"array","items":{"type":"object","properties":{"month":{"type":"string"},"volume":{"type":"integer"}},"required":[]}}},"required":[]}},"spent_limits":{"type":"integer"},"left_limits":{"type":"integer"}},"required":[]},"SerpstatKeywordProcedure.getKeywordTop":{"type":"object","properties":{"data":{"type":"object","properties":{"top":{"type":"array","items":{"type":"object","properties":{"position":{"type":"integer"},"domain":{"type":"string"},"subdomain":{"type":"string"},"types":{"type":"array","items":{"type":"string"}}},"required":["position","domain","subdomain","types"]}},"types":{"type":"array","items":{"type":"string"}},"results":{"type":"integer"}},"required":["types","results"]},"summary_info":{"type":"object","properties":{"page":{"type":"integer"},"left_lines":{"type":"integer"}},"required":["page","left_lines"]}},"required":[]},"SerpstatBacklinksProcedure.getSummaryV2":{"type":"object","properties":{"data":{"type":"object","properties":{"sersptat_domain_rank":{"type":"integer"},"referring_domains":{"type":"integer"},"referring_domains_change":{"type":"integer"},"backlinks":{"type":"integer"},"backlinks_change":{"type":"integer"},"nofollow_backlinks":{"type":"integer"},"dofollow_backlinks":{"type":"integer"},"external_domains":{"type":"integer"},"external_links":{"type":"integer"}},"required":["sersptat_domain_rank","referring_domains","referring_domains_change","backlinks","backlinks_change","nofollow_backlinks","dofollow_backlinks","external_domains","external_links"]},"summary_info":{"type":"object","properties":{"left_lines":{"type":"integer"}},"required":["left_lines"]}},"required":["summary_info"]},"SerpstatBacklinksProcedure.getRefDomains":{"type":"object","properties":{"data":{"type":"array","items":{"type":"object","properties":{"domain_from":{"type":"string"},"ref_pages":{"type":["string","integer"]},"domainRank":{"type":["string","integer"]}},"required":["domain_from","ref_pages","domainRank"]}},"summary_info":{"type":"object","properties":{"left_lines":{"type":"integer"},"page":{"type":"integer"},"count":{"type":"integer"},"total":{"type":"integer"},"sort":{"type":"string"},"order":{"type":"string","enum":["asc","desc","ASC","DESC"]}},"required":["left_lines","page","count","total","sort","order"]}},"required":[]},"AuditSite.getList":{"type":"array","items":{"type":"object","properties":{"reportId":{"type":"integer"},"date":{"type":"string"},"sdo":{"type":"integer"},"pagesLimit":{"type":"integer"},"pagesScanned":{"type":"integer"},"criticalCount":{"type":"integer"},"nonCriticalCount":{"type":"integer"},"virusesCount":{"type":"integer"},"progress":{"type":"integer"},"stoped":{"type":"boolean"},"hasDetailData":{"type":"boolean"}},"required":["reportId","date","sdo","pagesLimit","pagesScanned","criticalCount","nonCriticalCount","virusesCount","progress","stoped","hasDetailData"]}},"AuditSite.getBasicInfo":{"type":"object","properties":{"reportId":{"type":"integer"},"date":{"type":"string"},"sdo":{"type":"integer"},"highCount":{"type":"integer"},"mediumCount":{"type":"integer"},"lowCount":{"type":"integer"},"informationCount":{"type":"integer"},"virusesCount":{"type":"integer"},"progress":{"type":"integer"},"stoped":{"enum":[0,1]},"specialStopReason":{"type":"integer"},"checkedPageCount":{"type":"integer"},"totalCheckedPageCount":{"type":"integer"},"redirectCount":{"type":"integer"},"captchaDetected":{"type":"boolean"},"hasDetailData":{"type":"boolean"}},"required":["reportId","date","sdo","highCount","mediumCount","lowCount","informationCount","virusesCount","progress","stoped","specialStopReason","checkedPageCount","totalCheckedPageCount","redirectCount","captchaDetected","hasDetailData"]},"AuditSite.getCategoriesStatistic":{"type":"array","items":{"type":"object","properties":{"category":{"enum":["pages_status","meta_tags","headings","content","multimedia","indexation","redirects","links","https","hreflang","amp","markup","pagespeed_desktop","pagespeed_mobile","server_params"]},"highCount":{"type":"integer"},"mediumCount":{"type":"integer"},"lowCount":{"type":"integer"},"informationCount":{"type":"integer"}},"required":["highCount","mediumCount","lowCount","informationCount"]}}}''')
MAX_BYTES = 4 * 1024 * 1024
MAX_ROWS = 1000


def _secret_value(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        raise ValueError("Supply the existing private Serpstat API token without whitespace")
    return value


class SerpstatApiTokenCredential(BaseModel):
    credential_type: Literal["serpstat_api_token"] = Field("serpstat_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="Existing Private API Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Serpstat API Token", extra="ignore", json_schema_extra={
        "x-credential-url": "https://help.serpstat.com/en/articles/15956919-serpstat-api",
        "x-credential-instructions": "Supply an existing personal Serpstat API token. Current v4 requires query parameter token; native transport logs are protected. No environment fallback, token generation, OAuth or sandbox. Current API access starts at Team; actual credits, delays and API plugin access come from the protected account limits read. SEO/result calls can consume live credits even for empty responses; connection uses documented non-credit getStats. Account proof does not prove rank/audit access or a free entitlement.",
    })
    _token = field_validator("api_token")(_secret_value)


# Serpstat's own MCP server: agents get its tools through a person's Serpstat sign-in.
SerpstatMcpCredential = mcp_credential("serpstat", "https://mcp.serpstat.com/mcp", app="Serpstat")
SerpstatCredential = Union[SerpstatApiTokenCredential, SerpstatMcpCredential]


def _op(name, label, category):
    return Field(name, title=label, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


def _whole(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,9}", value):
        value = int(value)
    if type(value) is not int:
        raise ValueError("Use a whole page, batch or limit")
    return value


def _id(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,17}", value):
        raise ValueError("Supply the exact positive resource identifier")
    return value


def _domain(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 253 or value != value.strip() or any(c in value for c in "/:@?#\\"):
        raise ValueError("Supply a domain name without URL, port, path or query")
    try:
        normalized = value.rstrip('.').encode('idna').decode().lower()
    except UnicodeError:
        raise ValueError("Domain is invalid") from None
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", normalized):
        raise ValueError("Supply a valid domain name")
    return normalized


def _keyword(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Supply a nonempty bounded keyword")
    return value.strip()


def _dynamic(field, parent=None):
    result = {"x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True}, "x-resource-type": "serpstat_" + field.removesuffix("_id"), "x-resource-id-path": field}
    if parent:
        result["x-dynamic-options"]["depends_on"] = parent
    return result


class SerpstatOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SerpstatPage(SerpstatOperation):
    page: int = Field(1, ge=1, le=10000, description="One actual 1-based provider page. No automatic complete export.")
    size: int = Field(20, ge=10, le=100, description="Native page cap 100, below the provider's larger endpoint limits. Project sizes use documented 20/50/100.")
    _pages = field_validator("page", "size", mode="before")(_whole)


class SerpstatSearchEngine(SerpstatOperation):
    search_engine: str = Field("g_us", title="Search Database", description="Official search-engine database code; a static catalog is not account proof.", json_schema_extra={"ui:widget": "select", "enum": SEARCH_ENGINES})
    @field_validator("search_engine")
    @classmethod
    def valid_engine(cls, value):
        if value not in SEARCH_ENGINES:
            raise ValueError("Select an official search database code")
        return value


class SerpstatDomain(SerpstatSearchEngine):
    domain: str = Field(..., description="Domain subject only; the node never fetches this host.")
    _domain_value = field_validator("domain")(_domain)


class SerpstatKeyword(SerpstatSearchEngine):
    keyword: str = Field(..., max_length=256)
    _keyword_value = field_validator("keyword")(_keyword)


class SerpstatKeywords(SerpstatSearchEngine):
    keywords: list[str] = Field(..., min_length=1, max_length=20, json_schema_extra={"ui:widget": "list"}, description="Explicit small keyword batch; live analytics consume credits.")
    @field_validator("keywords")
    @classmethod
    def valid_keywords(cls, value):
        result = [_keyword(v) for v in value]
        if len(set(result)) != len(result):
            raise ValueError("Supply unique keywords")
        return result


class SerpstatProjectScope(SerpstatOperation):
    project_id: str = Field(..., title="Audit Project", json_schema_extra=_dynamic("project_id"))
    _project = field_validator("project_id", mode="before")(_id)


class SerpstatRankScope(SerpstatOperation):
    rank_project_id: str = Field(..., title="Rank Tracker Project", json_schema_extra=_dynamic("rank_project_id"), description="Rank project identifiers are separate from general/audit project identifiers.")
    _project = field_validator("rank_project_id", mode="before")(_id)


class SerpstatAuditScope(SerpstatProjectScope):
    audit_report_id: str = Field(..., title="Existing Audit Report", json_schema_extra=_dynamic("audit_report_id", "project_id"), description="Read an existing report; current project membership is checked before report-only methods.")
    _report = field_validator("audit_report_id", mode="before")(_id)


class SerpstatCheckConfig(SerpstatOperation):
    operation: Literal["test_connection"] = _op("test_connection", "Check Account Credit Access", "Connection")



class SerpstatCreditsConfig(SerpstatOperation):
    operation: Literal["get_credit_limits"] = _op("get_credit_limits", "Get Account Credit Limits", "Connection")



class SerpstatProjectsConfig(SerpstatPage):
    size: Literal[20, 50, 100] = Field(20, title="Projects Per Page")
    operation: Literal["list_projects"] = _op("list_projects", "List Audit Projects", "Projects")



class SerpstatDomainOverviewConfig(SerpstatDomain):
    operation: Literal["get_domain_overview"] = _op("get_domain_overview", "Get Domain Overview", "Domain Analysis")



class SerpstatDomainHistoryConfig(SerpstatDomain):
    operation: Literal["get_domain_history"] = _op("get_domain_history", "Get Domain History", "Domain Analysis")
    size: int = Field(20, ge=1, le=100)
    _size = field_validator("size", mode="before")(_whole)


class SerpstatDomainKeywordsConfig(SerpstatDomain, SerpstatPage):
    operation: Literal["list_domain_keywords"] = _op("list_domain_keywords", "List Domain Keywords", "Domain Analysis")



class SerpstatCompetitorsConfig(SerpstatDomain, SerpstatPage):
    operation: Literal["list_domain_competitors"] = _op("list_domain_competitors", "List Organic Domain Competitors", "Domain Analysis")



class SerpstatKeywordMetricsConfig(SerpstatKeywords):
    operation: Literal["get_keyword_metrics"] = _op("get_keyword_metrics", "Get Keyword Metrics", "Keyword Analysis")



class SerpstatRelatedConfig(SerpstatKeyword, SerpstatPage):
    operation: Literal["list_related_keywords"] = _op("list_related_keywords", "List Related Keywords", "Keyword Analysis")



class SerpstatTrendsConfig(SerpstatKeywords):
    operation: Literal["get_keyword_trends"] = _op("get_keyword_trends", "Get Keyword Trends", "Keyword Analysis")
    months: int = Field(12, ge=1, le=48)
    _months = field_validator("months", mode="before")(_whole)


class SerpstatTopConfig(SerpstatKeyword):
    operation: Literal["get_keyword_top"] = _op("get_keyword_top", "Get Keyword Top Domains", "Keyword Analysis")
    size: int = Field(20, ge=1, le=100)
    _size = field_validator("size", mode="before")(_whole)


class SerpstatBacklinkSummaryConfig(SerpstatOperation):
    operation: Literal["get_backlink_summary"] = _op("get_backlink_summary", "Get Backlink Summary", "Backlinks")
    domain: str = Field(...)
    _domain_value = field_validator("domain")(_domain)
    search_type: Literal["domain", "domain_with_subdomains"] = Field("domain")


class SerpstatRefDomainsConfig(SerpstatPage):
    operation: Literal["list_referring_domains"] = _op("list_referring_domains", "List Referring Domains", "Backlinks")
    domain: str = Field(...)
    _domain_value = field_validator("domain")(_domain)
    search_type: Literal["domain", "domain_with_subdomains"] = Field("domain")


class SerpstatRankProjectsConfig(SerpstatPage):
    size: Literal[20, 50, 100] = Field(20, title="Projects Per Page")
    operation: Literal["list_rank_projects"] = _op("list_rank_projects", "List Rank Tracker Projects", "Rank Tracker")



class SerpstatRankRegionsConfig(SerpstatRankScope):
    operation: Literal["list_rank_regions"] = _op("list_rank_regions", "List Rank Project Regions", "Rank Tracker")



class SerpstatRankStatusConfig(SerpstatRankScope):
    operation: Literal["get_rank_status"] = _op("get_rank_status", "Get Existing Rank Parsing Status", "Rank Tracker")
    rank_region_id: str = Field(..., title="Rank Region", json_schema_extra=_dynamic("rank_region_id", "rank_project_id"))
    _region = field_validator("rank_region_id", mode="before")(_id)


class SerpstatRankKeywordsConfig(SerpstatRankScope, SerpstatPage):
    operation: Literal["list_rank_keywords"] = _op("list_rank_keywords", "List Tracked Keyword Metadata", "Rank Tracker")



class SerpstatAuditReportsConfig(SerpstatProjectScope):
    operation: Literal["list_audit_reports"] = _op("list_audit_reports", "List Existing Audit Reports", "Site Audit")
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0, le=10000, description="Documented audit batch number, not an assumed row offset. One batch only; absence of a total does not prove full collection exhaustion.")
    _bounds = field_validator("limit", "offset", mode="before")(_whole)


class SerpstatAuditStatusConfig(SerpstatAuditScope):
    operation: Literal["get_audit_status"] = _op("get_audit_status", "Get Existing Audit Status", "Site Audit")



class SerpstatAuditCategoriesConfig(SerpstatAuditScope):
    operation: Literal["get_audit_categories"] = _op("get_audit_categories", "Get Audit Category Counts", "Site Audit")


SerpstatConfig = Annotated[Union[SerpstatCheckConfig, SerpstatCreditsConfig, SerpstatProjectsConfig, SerpstatDomainOverviewConfig, SerpstatDomainHistoryConfig, SerpstatDomainKeywordsConfig, SerpstatCompetitorsConfig, SerpstatKeywordMetricsConfig, SerpstatRelatedConfig, SerpstatTrendsConfig, SerpstatTopConfig, SerpstatBacklinkSummaryConfig, SerpstatRefDomainsConfig, SerpstatRankProjectsConfig, SerpstatRankRegionsConfig, SerpstatRankStatusConfig, SerpstatRankKeywordsConfig, SerpstatAuditReportsConfig, SerpstatAuditStatusConfig, SerpstatAuditCategoriesConfig], Field(discriminator="operation")]

class SerpstatNodeConfig(NodeConfig[SerpstatConfig, SerpstatCredential]):
    pass

class SerpstatAPIError(ValueError):
    def __init__(self, message, *, authority_rejected=False):
        super().__init__(message)
        self.authority_rejected = authority_rejected


def _shape(data):
    if not isinstance(data, dict) or data.get("credential_type", FAMILIES[0]) not in FAMILIES:
        raise ValueError("Serpstat credential family is unsupported")
    try:
        shaped = SerpstatApiTokenCredential.model_validate({**data, "credential_type": FAMILIES[0]}).model_dump()
    except Exception:
        raise ValueError("Serpstat native private API token is invalid") from None
    return {**data, **shaped}


def _binding(data):
    return (data["credential_type"], data["api_token"], data.get("owner_id"), data.get("token_version"), data.get("updated_at"), data.get("approval_revision"))

def _original_family(data):
    if not isinstance(data, dict):
        raise ValueError("Serpstat configuration is invalid")
    creds = data.get("credentials")
    saved = data.get("credential_id") or data.get("credentialIds")
    if saved and not isinstance(creds, dict) or isinstance(creds, dict) and (creds.get("credential_type") is not None or saved) and creds.get("credential_type") not in FAMILIES:
        raise ValueError("Serpstat saved credential family is missing or unsupported")


def _context(data, context):
    # Staging resolves and authorizes saved credentials before this picker.
    return {**{k: v for k, v in context.items() if not k.startswith("_")},
            "_user_id": context.get("_user_id"), "_workflow_id": context.get("_workflow_id")}


def _bounded(value, depth=0):
    if type(value) is int and value.bit_length() > 256:
        raise ValueError("Unverified JSON integer bound")
    if depth > 32 or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Unverified JSON depth or non-finite number")
    if isinstance(value, dict):
        for key, child in value.items():
            if len(key) > 512:
                raise ValueError("Unverified JSON key")
            _bounded(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ROWS:
            raise ValueError("Unverified JSON row bound")
        for child in value:
            _bounded(child, depth + 1)


def _redact(value, secret):
    if isinstance(value, str):
        variants = (secret, quote(secret, safe=""), quote_plus(secret, safe=""), base64.b64encode(secret.encode()).decode(), base64.b64encode((secret + ":").encode()).decode())
        for variant in variants:
            pattern = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: '%' + ''.join('[' + c.lower() + c.upper() + ']' for c in m[1]), re.escape(variant))
            value = re.sub(pattern, "[redacted]", value)
        return re.sub(r"(?i)([?&](?:access_token|api_key|token|signature|auth|key)=)[^&#\s]+", r"\1[redacted]", value)
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


# Narrow reuse of utils.meta_subscriptions._TransportPrivacy: context-local
# masking leaves concurrent unrelated requests untouched and resets on failure.
_PRIVATE_REQUEST = ContextVar("serpstat_private_request", default=False)


class _TransportPrivacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE_REQUEST.get():
            record.msg, record.args = "Serpstat private transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_TRANSPORT_PRIVACY = _TransportPrivacy()


def _protect_transport_logs():
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"}
    names.update(name for name in tuple(logging.Logger.manager.loggerDict) if name.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_TRANSPORT_PRIVACY)


def _projected(value, schema):
    """Validate and project only explicitly selected current documented fields."""
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    if value is None and ("null" in kinds or schema.get("nullable") is True):
        return None
    if "object" in kinds or "properties" in schema:
        if not isinstance(value, dict) or any(key not in value for key in schema.get("required", [])):
            raise SerpstatAPIError("Serpstat documented object response is unverified")
        return {key: _projected(value[key], child) for key, child in schema.get("properties", {}).items() if key in value}
    if "array" in kinds:
        if not isinstance(value, list) or len(value) > MAX_ROWS:
            raise SerpstatAPIError("Serpstat documented list response is unverified")
        return [_projected(item, schema["items"]) for item in value]
    valid = ("integer" in kinds and type(value) is int or "number" in kinds and type(value) in (int, float)
             or "string" in kinds and isinstance(value, str) and len(value) <= 2048
             or "boolean" in kinds and type(value) is bool)
    if kind is None and "enum" in schema:
        valid = any(type(value) is type(item) and value == item for item in schema["enum"])
    if not valid or "enum" in schema and not any(type(value) is type(item) and value == item for item in schema["enum"]):
        raise SerpstatAPIError("Serpstat documented field response is unverified")
    return value


async def _rpc(data, context, method, params=None):
    if method not in CONTRACTS or params is not None and not isinstance(params, dict):
        raise ValueError("Unsupported Serpstat native method")
    current = _shape(data)
    identifier = uuid4().hex
    body = {"jsonrpc": "2.0", "id": identifier, "method": method}
    if params is not None:
        body["params"] = params
    _bounded(body)
    if len(json.dumps(body, allow_nan=False).encode()) > 8192:
        raise ValueError("Serpstat request exceeds the local input bound")
    _protect_transport_logs()
    private = _PRIVATE_REQUEST.set(True)
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST", API_URL, params={"token": current["api_token"]}, headers={"Accept": "application/json", "Content-Type": "application/json"}, json=body) as response:
                payload = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(payload) + len(chunk) > MAX_BYTES:
                        raise SerpstatAPIError("Serpstat response exceeds the local byte bound; credits may have been consumed")
                    payload.extend(chunk)
                if response.status_code in (401, 403):
                    raise SerpstatAPIError(f"Serpstat HTTP {response.status_code}: current authority was rejected", authority_rejected=True)
                if response.status_code != 200 or response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise SerpstatAPIError(f"Serpstat HTTP {response.status_code}: documented JSON success is unverified; no automatic retry")
                try:
                    raw = json.loads(payload, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    _bounded(raw)
                except (ValueError, UnicodeError, RecursionError):
                    raise SerpstatAPIError("Serpstat response JSON is unverified; credits may have been consumed") from None
                # Current examples omit jsonrpc. When present, the version is exact.
                if not isinstance(raw, dict) or raw.get("id") != identifier or "jsonrpc" in raw and raw["jsonrpc"] != "2.0":
                    raise SerpstatAPIError("Serpstat response identifier or JSON-RPC version is unverified")
                if "error" in raw:
                    error = raw["error"]
                    if "result" in raw or not isinstance(error, dict) or type(error.get("code")) is not int or not isinstance(error.get("message"), str):
                        raise SerpstatAPIError("Serpstat JSON-RPC error envelope is unverified")
                    # Never echo provider messages/data, which can contain the query token.
                    raise SerpstatAPIError("Serpstat rejected the JSON-RPC read; inspect actual access, credits and request parameters; no retry")
                if "result" not in raw or raw.get("status") in ("error", "rejected", "pending_approval", "not_executed", "forbidden"):
                    raise SerpstatAPIError("Serpstat read result was not verified")
                result = _projected(raw["result"], CONTRACTS[method])
                return _redact(result, current["api_token"])
    except SerpstatAPIError:
        raise
    except (httpx.HTTPError, OSError, ValueError, UnicodeError):
        raise SerpstatAPIError("Serpstat transport result is unverified; credits may have been consumed; no retry") from None
    finally:
        _PRIVATE_REQUEST.reset(private)


def _account(raw):
    data = raw.get("data") if isinstance(raw, dict) else None
    user = data.get("user_info") if isinstance(data, dict) else None
    account = user.get("user_id") if isinstance(user, dict) else None
    if not isinstance(account, str) or not account.strip() or len(account) > 128 or "[redacted]" in account or any(ord(c) < 32 for c in account):
        raise SerpstatAPIError("Serpstat protected account identifier is unverified")
    return {"protected_read_completed": True, "account_identity_verified": True, "account_id": account,
            "credit_limits": {k: data[k] for k in ("max_lines", "used_lines", "left_lines")},
            "plugin_limits": data["plugin_limits"], "method_spends_api_credits": False,
            "seo_rank_audit_permissions_verified": False}


def _paged(raw, page, size, *, kind="analytics"):
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list) or len(raw["data"]) > size or not isinstance(raw.get("summary_info"), dict):
        raise SerpstatAPIError("Serpstat page response is unverified")
    summary = raw["summary_info"]
    page_key, pages_key, total_key = ("current_page", "pages_count", "total_data") if kind == "rank_keywords" else ("page", "page_total", "total")
    if summary.get(page_key) != page or type(summary.get(page_key)) is not int:
        raise SerpstatAPIError("Serpstat returned another page")
    total = summary.get(total_key)
    if total is not None and (type(total) is not int or total < 0 or total < len(raw["data"])):
        raise SerpstatAPIError("Serpstat page total is unverified")
    if kind in ("projects", "rank_keywords"):
        pages = summary.get(pages_key)
        if type(pages) is not int or pages < 0 or pages == 0 and raw["data"] or pages < page and raw["data"]:
            raise SerpstatAPIError("Serpstat project page count is unverified")
        if total is None or pages != (total + size - 1) // size and not (total == 0 and pages == 1):
            raise SerpstatAPIError("Serpstat project pagination totals are inconsistent")
        capacity = summary.get("size" if kind == "rank_keywords" else "count")
        if type(capacity) is not int or capacity != size:
            raise SerpstatAPIError("Serpstat project page size is unverified")
        exhausted = page >= pages
    elif total is not None:
        exhausted = (page - 1) * size + len(raw["data"]) >= total
    else:
        exhausted = None
    return {"results": raw["data"], "summary_info": summary, "collection_exhausted": exhausted,
            "next_page": page + 1 if exhausted is False else None,
            "continuation_unknown": exhausted is None,
            **{key: raw[key] for key in ("spent_limits", "left_limits") if key in raw}}


def _unique_ids(rows, key):
    ids = []
    for row in rows:
        try:
            ids.append(_id(row.get(key)))
        except (ValueError, AttributeError):
            raise SerpstatAPIError("Serpstat resource identifier is unverified") from None
    if len(set(ids)) != len(ids):
        raise SerpstatAPIError("Serpstat resource identifiers repeat")
    return ids


async def _find_project(data, context, identifier, *, rank=False):
    method = "RtApiProjectProcedure.getProjects" if rank else "ProjectProcedure.getProjects"
    key = "id" if rank else "project_id"
    seen = set()
    for page in range(1, 6):
        raw = await _rpc(data, context, method, {"page": page, "pageSize" if rank else "size": 20})
        result = _paged(raw, page, 20, kind="projects")
        ids = _unique_ids(result["results"], key)
        if seen.intersection(ids):
            raise SerpstatAPIError("Serpstat project discovery repeats IDs across pages")
        seen.update(ids)
        if identifier in ids:
            return result["results"][ids.index(identifier)]
        if result["collection_exhausted"]:
            raise ValueError("Selected Serpstat project is not currently accessible")
    raise SerpstatAPIError("Serpstat project lookup reached its five-page bound before exhaustion; select a currently accessible project")


async def _audit_membership(data, context, project, report):
    await _find_project(data, context, project)
    seen = set()
    for offset in range(5):
        rows = await _rpc(data, context, "AuditSite.getList", {"projectId": int(project), "limit": 20, "offset": offset})
        ids = _unique_ids(rows, "reportId")
        if len(rows) > 20 or seen.intersection(ids):
            raise SerpstatAPIError("Serpstat audit report discovery is unverified")
        seen.update(ids)
        if report in ids:
            return
        if not rows:
            raise ValueError("Selected report is not currently listed in the selected audit project")
    raise SerpstatAPIError("Audit membership was not established within five documented batches; no report details were fetched")


class SerpstatNode(WorkflowNode):
    integration_type = "automation-serpstat"
    credential_provider_labels = {"serpstat": "Serpstat Account"}
    connection_evidence = ConnectionEvidence(identity_operation="test_connection", noun="Serpstat account", proves="account", identity_keys=("account_id",), label_keys=("account_id",))
    edit_examples = ["Read domain keyword rankings in the selected search database", "Compare related keyword metrics", "Read an existing scoped audit report without starting an audit"]

    @classmethod
    def get_config_model(cls):
        return SerpstatNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        _original_family(config_data)
        shaped = dict(config_data)
        if config_data.get("credentials") is not None:
            shaped["credentials"] = _shape(config_data["credentials"])
        try:
            SerpstatNodeConfig.model_validate(runtime_config_view(shaped, SerpstatNodeConfig))
        except ValueError:
            raise ValueError("Serpstat configuration or selected credential scope is invalid") from None
        return super().parse_config(shaped)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _original_family(config_data)
            shaped = dict(config_data)
            if config_data.get("credentials") is not None:
                shaped["credentials"] = _shape(config_data["credentials"])
            SerpstatNodeConfig.model_validate(runtime_config_view(shaped, SerpstatNodeConfig))
        except (ValueError, TypeError):
            return ValidationResult(valid=False, errors=["Serpstat configuration or credential family is invalid"], satisfied_set=None)
        return super().validate_config(shaped)

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(self.config, SerpstatNodeConfig) or self.config.credentials is None:
            raise ValueError("Serpstat requires explicit native credentials")
        context = {"_approval_pool": (self.node_data or {}).get("_approval_pool"), "_credential_id": (self.node_data or {}).get("credential_id"), "_user_id": self.user_id, "_organization_id": self.organization_id, "_workflow_id": self.workflow_id}
        data = _shape(self.config.credentials.model_dump())
        result = await self._operation(self.config.config, data, context)
        return {"status": "success", "operation": self.config.config.operation, "data": _redact(result, data["api_token"])}

    async def _operation(self, cfg, data, context):
        op = cfg.operation
        if op in ("test_connection", "get_credit_limits"):
            return _account(await _rpc(data, context, "SerpstatLimitsProcedure.getStats"))
        if op in ("list_projects", "list_rank_projects"):
            if cfg.size not in (20, 50, 100):
                raise ValueError("Use a documented project page size: 20, 50 or 100")
            rank = op == "list_rank_projects"
            result = _paged(await _rpc(data, context, "RtApiProjectProcedure.getProjects" if rank else "ProjectProcedure.getProjects", {"page": cfg.page, "pageSize" if rank else "size": cfg.size}), cfg.page, cfg.size, kind="projects")
            _unique_ids(result["results"], "id" if rank else "project_id")
            return result
        if op in ("list_rank_regions", "get_rank_status", "list_rank_keywords"):
            await _find_project(data, context, cfg.rank_project_id, rank=True)
            if op == "list_rank_keywords":
                raw = await _rpc(data, context, "RtApiProcedure.getProjectKeywords", {"project_id": int(cfg.rank_project_id), "page": cfg.page, "size": cfg.size, "sort": "added", "order": "desc"})
                result = _paged(raw, cfg.page, cfg.size, kind="rank_keywords")
                _unique_ids(result["results"], "id")
                return {"rank_project_id": cfg.rank_project_id, "parent_scope_source": "protected_project_list_and_request", **result}
            regions = await _rpc(data, context, "RtApiSearchEngineProcedure.getProjectRegions", {"projectId": int(cfg.rank_project_id)})
            if regions.get("projectId") != int(cfg.rank_project_id) or not isinstance(regions.get("regions"), list):
                raise SerpstatAPIError("Serpstat rank regions belong to an unverified project")
            ids = _unique_ids(regions["regions"], "id")
            if op == "list_rank_regions":
                return regions
            if cfg.rank_region_id not in ids:
                raise ValueError("Rank region does not belong to the selected project")
            result = await _rpc(data, context, "RtApiProjectProcedure.getProjectStatus", {"projectId": int(cfg.rank_project_id), "regionId": int(cfg.rank_region_id)})
            if result.get("projectId") != int(cfg.rank_project_id) or result.get("regionId") != int(cfg.rank_region_id) or type(result.get("parsing")) is not bool:
                raise SerpstatAPIError("Serpstat rank status scope or shape is unverified")
            return result
        if op == "list_audit_reports":
            await _find_project(data, context, cfg.project_id)
            rows = await _rpc(data, context, "AuditSite.getList", {"projectId": int(cfg.project_id), "limit": cfg.limit, "offset": cfg.offset})
            if len(rows) > cfg.limit:
                raise SerpstatAPIError("Serpstat audit batch exceeds the requested limit")
            _unique_ids(rows, "reportId")
            return {"project_id": cfg.project_id, "results": rows, "offset": cfg.offset, "offset_unit": "documented_batch_number", "collection_exhausted": True if not rows else None, "continuation_unknown": bool(rows)}
        if op in ("get_audit_status", "get_audit_categories"):
            await _audit_membership(data, context, cfg.project_id, cfg.audit_report_id)
            result = await _rpc(data, context, "AuditSite.getBasicInfo" if op == "get_audit_status" else "AuditSite.getCategoriesStatistic", {"reportId": int(cfg.audit_report_id)})
            if op == "get_audit_status" and result.get("reportId") != int(cfg.audit_report_id):
                raise SerpstatAPIError("Serpstat returned another audit report")
            return {"project_id": cfg.project_id, "audit_report_id": cfg.audit_report_id, "parent_scope_source": "protected_project_and_report_membership", "result": result}
        if op in ("get_backlink_summary", "list_referring_domains"):
            params = {"query": cfg.domain, "searchType": cfg.search_type}
            method = "SerpstatBacklinksProcedure.getSummaryV2" if op == "get_backlink_summary" else "SerpstatBacklinksProcedure.getRefDomains"
            if op == "list_referring_domains":
                params.update({"page": cfg.page, "size": cfg.size})
            raw = await _rpc(data, context, method, params)
            if op == "get_backlink_summary" and not isinstance(raw.get("data"), dict):
                raise SerpstatAPIError("Serpstat backlink summary data is unverified")
            return _paged(raw, cfg.page, cfg.size) if op == "list_referring_domains" else raw
        methods = {"get_domain_overview": "SerpstatDomainProcedure.getDomainsInfo", "get_domain_history": "SerpstatDomainProcedure.getDomainsHistory", "list_domain_keywords": "SerpstatDomainProcedure.getDomainKeywords", "list_domain_competitors": "SerpstatDomainProcedure.getOrganicCompetitorsPage", "get_keyword_metrics": "SerpstatKeywordProcedure.getKeywordsInfo", "list_related_keywords": "SerpstatKeywordProcedure.getRelatedKeywords", "get_keyword_trends": "SerpstatKeywordProcedure.getKeywordTrends", "get_keyword_top": "SerpstatKeywordProcedure.getKeywordTop"}
        if op not in methods:
            raise ValueError("Unsupported native Serpstat read")
        params = {"se": cfg.search_engine}
        if op == "get_domain_overview":
            params["domains"] = [cfg.domain]
        elif hasattr(cfg, "domain"):
            params["domain"] = cfg.domain
        elif hasattr(cfg, "keywords"):
            params["keywords"] = cfg.keywords
        else:
            params["keyword"] = cfg.keyword
        if hasattr(cfg, "page"):
            params.update({"page": cfg.page, "size": cfg.size})
        elif hasattr(cfg, "size"):
            params["size"] = cfg.size
        if op == "get_domain_history":
            params.update({"during_all_time": False, "withSubdomains": False})
        if op == "get_keyword_trends":
            params["months"] = cfg.months
        if op == "list_domain_keywords":
            params["withSubdomains"] = False
        raw = await _rpc(data, context, methods[op], params)
        if hasattr(cfg, "page"):
            return _paged(raw, cfg.page, cfg.size)
        if op == "get_keyword_top":
            top = raw.get("data")
            if not isinstance(top, dict) or not isinstance(top.get("top"), list) or len(top["top"]) > cfg.size:
                raise SerpstatAPIError("Serpstat keyword top data or requested bound is unverified")
        if op in ("get_domain_overview", "get_domain_history"):
            rows = raw.get("data")
            if not isinstance(rows, list) or len(rows) > (cfg.size if hasattr(cfg, "size") else 1) or any(row.get("domain") != cfg.domain for row in rows):
                raise SerpstatAPIError("Serpstat domain response scope or bound is unverified")
        if op in ("get_keyword_metrics", "get_keyword_trends"):
            rows = raw.get("data")
            if not isinstance(rows, list) or len(rows) > len(cfg.keywords) or any(row.get("keyword") not in cfg.keywords for row in rows):
                raise SerpstatAPIError("Serpstat keyword response scope or bound is unverified")
        return raw

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, search=None, page_token=None):
        if field_name not in ("project_id", "rank_project_id", "rank_region_id", "audit_report_id"):
            return {"options": [], "next_page_token": None}
        context = _context(credential_data, context or {})
        query = (search or "").strip() if isinstance(search, str) or search is None else None
        if query is None or len(query) > 128 or any(ord(c) < 32 for c in query):
            raise ValueError("Use a bounded Serpstat picker search")
        parent = _id(context.get("rank_project_id" if field_name == "rank_region_id" else "project_id")) if field_name in ("rank_region_id", "audit_report_id") else None
        data = _shape(credential_data)
        binding = hashlib.sha256(json.dumps([field_name, parent, query, _binding(data), context.get("_user_id"), context.get("_credential_id"), context.get("_organization_id"), context.get("_workflow_id")], separators=(",", ":")).encode()).hexdigest()
        page, seen = 1, []
        if page_token:
            try:
                if not isinstance(page_token, str) or len(page_token) > 8192:
                    raise ValueError()
                saved = json.loads(base64.urlsafe_b64decode(page_token + "=" * (-len(page_token) % 4)))
                if not isinstance(saved, dict) or set(saved) != {"binding", "page", "seen"} or saved["binding"] != binding or type(saved["page"]) is not int or not 2 <= saved["page"] <= 5 or not isinstance(saved["seen"], list) or len(saved["seen"]) > 100 or any(_id(v) != v for v in saved["seen"]) or len(set(saved["seen"])) != len(saved["seen"]):
                    raise ValueError()
                page, seen = saved["page"], saved["seen"]
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise ValueError("Serpstat picker continuation belongs to another current actor, credential, parent or search") from None
        if field_name in ("rank_region_id", "audit_report_id"):
            await _find_project(data, context, parent, rank=field_name == "rank_region_id")
        while page <= 5:
            if field_name == "rank_region_id":
                if page_token:
                    raise ValueError("Rank region list has no documented pagination")
                raw = await _rpc(data, context, "RtApiSearchEngineProcedure.getProjectRegions", {"projectId": int(parent)})
                if raw.get("projectId") != int(parent) or not isinstance(raw.get("regions"), list):
                    raise SerpstatAPIError("Serpstat region scope is unverified")
                rows, key, label, more = raw["regions"], "id", "country", False
            elif field_name == "audit_report_id":
                rows = await _rpc(data, context, "AuditSite.getList", {"projectId": int(parent), "limit": 20, "offset": page - 1})
                if len(rows) > 20:
                    raise SerpstatAPIError("Serpstat audit picker batch is unverified")
                key, label, more = "reportId", "date", bool(rows)
            else:
                rank = field_name == "rank_project_id"
                raw = await _rpc(data, context, "RtApiProjectProcedure.getProjects" if rank else "ProjectProcedure.getProjects", {"page": page, "pageSize" if rank else "size": 20})
                result = _paged(raw, page, 20, kind="projects")
                rows, key, label, more = result["results"], "id" if rank else "project_id", "projectName" if rank else "project_name", not result["collection_exhausted"]
            ids = _unique_ids(rows, key)
            if set(seen).intersection(ids):
                raise SerpstatAPIError("Serpstat picker repeats IDs across pages")
            seen += ids
            if more and (page >= 5 or len(seen) >= 100):
                raise SerpstatAPIError("Serpstat picker reached its bounded search before exhaustion; supply an exact scoped resource")
            options = [{"value": identifier, "label": str(row.get(label, identifier))} for identifier, row in zip(ids, rows) if not query or query.casefold() in str(row.get(label, identifier)).casefold() or query == identifier]
            page += 1
            token = base64.urlsafe_b64encode(json.dumps({"binding": binding, "page": page, "seen": seen}, separators=(",", ":")).encode()).decode().rstrip("=") if more else None
            if options or not more:
                return {"options": options, "next_page_token": token}
        raise SerpstatAPIError("Serpstat picker exhaustion was not established within its local bound")
