"""GLEIF public JSON:API reads, pinned to the publisher's saved Postman examples.

No sign-in is required. The published API is read-only; this node makes one
request per operation and returns pagination metadata without following links.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://api.gleif.org/api/v1"


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _LEI(_Input):
    lei: str = Field(..., title="LEI", pattern=r"^[A-Z0-9]{20}$", description="The entity's 20-character Legal Entity Identifier.")


class _Identifier(_Input):
    resource_id: str = Field(..., title="Resource ID", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class _Search(_Input):
    query: str = Field(..., title="Search term", min_length=1, max_length=500)
    field: Literal["entity.legalName", "fulltext", "owns", "ownedBy"] = Field("entity.legalName", title="Search field")


class GleifGetLeiRecordConfig(_LEI):
    operation: Literal["get_lei_record"] = Field("get_lei_record", title='LEI Record By ID (LEI)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'LEI Record By ID (LEI)'})


class GleifListLeiRecordsConfig(_Input):
    operation: Literal["list_lei_records"] = Field("list_lei_records", title='All LEI Records', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'All LEI Records'})
    page_size: int = Field(20, ge=1, le=200, title="Page size")
    page_number: int = Field(1, ge=1, title="Page number")


class GleifGetDirectParentRelationshipConfig(_LEI):
    operation: Literal["get_direct_parent_relationship"] = Field("get_direct_parent_relationship", title='Direct Parent Relationship(s)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Direct Parent Relationship(s)'})


class GleifGetDirectParentReportingExceptionConfig(_LEI):
    operation: Literal["get_direct_parent_reporting_exception"] = Field("get_direct_parent_reporting_exception", title='Direct Parent Reporting Exception(s)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Direct Parent Reporting Exception(s)'})


class GleifGetUltimateParentRelationshipConfig(_LEI):
    operation: Literal["get_ultimate_parent_relationship"] = Field("get_ultimate_parent_relationship", title='Ultimate Parent Relationship(s)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Ultimate Parent Relationship(s)'})


class GleifGetUltimateParentReportingExceptionConfig(_LEI):
    operation: Literal["get_ultimate_parent_reporting_exception"] = Field("get_ultimate_parent_reporting_exception", title='Ultimate Parent Reporting Exception(s)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Ultimate Parent Reporting Exception(s)'})


class GleifGetUltimateParentConfig(_LEI):
    operation: Literal["get_ultimate_parent"] = Field("get_ultimate_parent", title="Ultimate Parent's LEI Record", json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": "Ultimate Parent's LEI Record"})


class GleifGetDirectParentConfig(_LEI):
    operation: Literal["get_direct_parent"] = Field("get_direct_parent", title="Direct Parent's LEI Record", json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": "Direct Parent's LEI Record"})


class GleifListUltimateChildRelationshipsConfig(_LEI):
    operation: Literal["list_ultimate_child_relationships"] = Field("list_ultimate_child_relationships", title='Ultimate Child Relationship(s)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Ultimate Child Relationship(s)'})


class GleifListDirectChildRelationshipsConfig(_LEI):
    operation: Literal["list_direct_child_relationships"] = Field("list_direct_child_relationships", title='Direct Child Relationship(s)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Direct Child Relationship(s)'})


class GleifListUltimateChildrenConfig(_LEI):
    operation: Literal["list_ultimate_children"] = Field("list_ultimate_children", title='Ultimate Child(ren)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Ultimate Child(ren)'})


class GleifListDirectChildrenConfig(_LEI):
    operation: Literal["list_direct_children"] = Field("list_direct_children", title='Direct Child(ren)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Direct Child(ren)'})


class GleifGetLeiIssuerConfig(_LEI):
    operation: Literal["get_lei_issuer"] = Field("get_lei_issuer", title='LEI Issuer', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'LEI Issuer'})


class GleifGetAssociatedEntityConfig(_LEI):
    operation: Literal["get_associated_entity"] = Field("get_associated_entity", title='Associated Entity (Fund Manager Legal Entity)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Associated Entity (Fund Manager Legal Entity)'})


class GleifGetSuccessorEntityConfig(_LEI):
    operation: Literal["get_successor_entity"] = Field("get_successor_entity", title='Successor Entity (Legal Entity this Registration is Replaced By)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Successor Entity (Legal Entity this Registration is Replaced By)'})


class GleifGetManagingLouConfig(_LEI):
    operation: Literal["get_managing_lou"] = Field("get_managing_lou", title='Managing LOU (LEI Issuer)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Managing LOU (LEI Issuer)'})


class GleifListFieldModificationsConfig(_LEI):
    operation: Literal["list_field_modifications"] = Field("list_field_modifications", title='All LEI Record field modifications', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'All LEI Record field modifications'})


class GleifListLeiIssuersConfig(_Input):
    operation: Literal["list_lei_issuers"] = Field("list_lei_issuers", title='LEI Issuers', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'LEI Issuers'})


class GleifGetIssuerConfig(_Identifier):
    operation: Literal["get_issuer"] = Field("get_issuer", title='LEI Issuer By ID', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'LEI Issuer By ID'})


class GleifSearchFuzzyConfig(_Search):
    operation: Literal["search_fuzzy"] = Field("search_fuzzy", title='Fuzzy Completions (Approximate Match)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Fuzzy Completions (Approximate Match)'})


class GleifSearchAutocompleteConfig(_Search):
    operation: Literal["search_autocomplete"] = Field("search_autocomplete", title='Auto-Completions (Suggested Search Terms)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Auto-Completions (Suggested Search Terms)'})


class GleifListLegalFormsConfig(_Input):
    operation: Literal["list_legal_forms"] = Field("list_legal_forms", title='Entity Legal Forms (ELF Codes)', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Entity Legal Forms (ELF Codes)'})


class GleifGetLegalFormConfig(_Identifier):
    operation: Literal["get_legal_form"] = Field("get_legal_form", title='Entity Legal Form Details By ID', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Entity Legal Form Details By ID'})


class GleifListRegistrationAuthoritiesConfig(_Input):
    operation: Literal["list_registration_authorities"] = Field("list_registration_authorities", title='Registration Authorities', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Registration Authorities'})


class GleifGetRegistrationAuthorityConfig(_Identifier):
    operation: Literal["get_registration_authority"] = Field("get_registration_authority", title='Registration Authority Details By ID', json_schema_extra={"ui:hidden": True, "x-category": "GLEIF", "x-display-name": 'Registration Authority Details By ID'})


GleifConfig = Annotated[Union[
    GleifGetLeiRecordConfig,
    GleifListLeiRecordsConfig,
    GleifGetDirectParentRelationshipConfig,
    GleifGetDirectParentReportingExceptionConfig,
    GleifGetUltimateParentRelationshipConfig,
    GleifGetUltimateParentReportingExceptionConfig,
    GleifGetUltimateParentConfig,
    GleifGetDirectParentConfig,
    GleifListUltimateChildRelationshipsConfig,
    GleifListDirectChildRelationshipsConfig,
    GleifListUltimateChildrenConfig,
    GleifListDirectChildrenConfig,
    GleifGetLeiIssuerConfig,
    GleifGetAssociatedEntityConfig,
    GleifGetSuccessorEntityConfig,
    GleifGetManagingLouConfig,
    GleifListFieldModificationsConfig,
    GleifListLeiIssuersConfig,
    GleifGetIssuerConfig,
    GleifSearchFuzzyConfig,
    GleifSearchAutocompleteConfig,
    GleifListLegalFormsConfig,
    GleifGetLegalFormConfig,
    GleifListRegistrationAuthoritiesConfig,
    GleifGetRegistrationAuthorityConfig
], Field(discriminator="operation")]


class GleifFullConfig(NodeConfig[GleifConfig, None]):
    @field_validator("credentials", mode="before")
    @classmethod
    def public_api(cls, value):
        # Credential-free callers may supply an empty credential container.
        return None if value == {} else value


ROUTES = {
    'get_lei_record': '/lei-records/{id}',
    'list_lei_records': '/lei-records',
    'get_direct_parent_relationship': '/lei-records/{id}/direct-parent-relationship',
    'get_direct_parent_reporting_exception': '/lei-records/{id}/direct-parent-reporting-exception',
    'get_ultimate_parent_relationship': '/lei-records/{id}/ultimate-parent-relationship',
    'get_ultimate_parent_reporting_exception': '/lei-records/{id}/ultimate-parent-reporting-exception',
    'get_ultimate_parent': '/lei-records/{id}/ultimate-parent',
    'get_direct_parent': '/lei-records/{id}/direct-parent',
    'list_ultimate_child_relationships': '/lei-records/{id}/ultimate-child-relationships',
    'list_direct_child_relationships': '/lei-records/{id}/direct-child-relationships',
    'list_ultimate_children': '/lei-records/{id}/ultimate-children',
    'list_direct_children': '/lei-records/{id}/direct-children',
    'get_lei_issuer': '/lei-records/{id}/lei-issuer',
    'get_associated_entity': '/lei-records/{id}/associated-entity',
    'get_successor_entity': '/lei-records/{id}/successor-entity',
    'get_managing_lou': '/lei-records/{id}/managing-lou',
    'list_field_modifications': '/lei-records/{id}/field-modifications',
    'list_lei_issuers': '/lei-issuers',
    'get_issuer': '/lei-issuers/{id}',
    'search_fuzzy': '/fuzzycompletions',
    'search_autocomplete': '/autocompletions',
    'list_legal_forms': '/entity-legal-forms',
    'get_legal_form': '/entity-legal-forms/{id}',
    'list_registration_authorities': '/registration-authorities',
    'get_registration_authority': '/registration-authorities/{id}',
}


class GleifNode(WorkflowNode):
    integration_type = "automation-gleif"
    connection_evidence = ConnectionEvidence(operation="list_lei_records", noun="public LEI records", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return GleifFullConfig

    async def execute(self, inputs):
        config = self.config.config
        operation = config.operation
        path = ROUTES[operation]
        if "{id}" in path:
            identifier = config.lei if isinstance(config, _LEI) else config.resource_id
            path = path.replace("{id}", quote(identifier, safe=""))
        params = {}
        if operation == "list_lei_records":
            params = {"page[size]": config.page_size, "page[number]": config.page_number}
        elif isinstance(config, _Search):
            params = {"field": config.field, "q": config.query}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.get(BASE + path, params=params, headers={"Accept": "application/vnd.api+json"})
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("GLEIF returned a redirect instead of JSON:API data")
        body = response.json()
        if not isinstance(body, dict) or "errors" in body or "data" not in body:
            raise ValueError("GLEIF returned an invalid JSON:API envelope")
        if body["data"] is not None and not isinstance(body["data"], (dict, list)):
            raise ValueError("GLEIF returned invalid JSON:API resource data")
        return {"status": "success", "operation": operation, **body}
