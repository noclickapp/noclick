"""HigherGov v1.2 data reads using an administrator-created API key.

Each operation maps to one published endpoint. Account-owned pursuits supply
connection evidence; pagination is explicit and provider links are never followed.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote, quote_plus

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://www.highergov.com"
CREDENTIAL_TYPE = "highergov_api_key"


class HigherGovAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="HigherGov API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.highergov.com/api-external/schema/",
            "x-credential-instructions": "An account administrator can create an API key in HigherGov: open the gear menu, then API. Paste only the key. HigherGov requires it as an api_key query parameter over HTTPS. Connecting reads your internal pursuits; reads consume your API record allowance.",
        })
    credential_type: Literal["highergov_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the HigherGov API key")
        return value


class _Page(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    page_number: int = Field(1, ge=1, title="Page Number", description="Read one page. Use next_page_number from the previous result.")
    page_size: int = Field(10, ge=1, le=100, title="Page Size", description="Records per page, up to the documented maximum of 100.")


class ListAgencies(_Page):
    """Description:Federal and State and Local Agencies and hierarchies.    Update Frequency: Ad Hoc as new agencies are created or become relevant."""
    operation: Literal['list_agencies'] = Field('list_agencies', json_schema_extra={"ui:hidden": True})
    agency_key: int | None = Field(None, title='Agency Key', description='HigherGov Agency key')


class ListAwardees(_Page):
    """Description: Federal Awardees registered in SAM and DSBS.    Update Frequency: Updated Monthly.    Update Check Field: registration_last_update_date"""
    operation: Literal['list_awardees'] = Field('list_awardees', json_schema_extra={"ui:hidden": True})
    awardee_key_parent: int | None = Field(None, title='Awardee Key Parent', description='HigherGov Awardee Key (Parent Level)')
    cage_code: str | None = Field(None, title='Cage Code', description='CAGE Code', min_length=1, max_length=4096)
    ordering: Literal['-last_update_date', 'last_update_date'] | None = Field(None, title='Ordering', description='Which field to use when ordering the results.')
    primary_naics: str | None = Field(None, title='Primary Naics', description='Primary registered NAICS Code', min_length=1, max_length=4096)
    registration_last_update_date: date | None = Field(None, title='Registration Last Update Date', description='The date the awardee last updated their registration in SAM')
    uei: str | None = Field(None, title='Uei', description='UEI', min_length=1, max_length=4096)


class ListMentorProtegeRelationships(_Page):
    """Read the published HigherGov mentor_protege_relationships endpoint."""
    operation: Literal['list_mentor_protege_relationships'] = Field('list_mentor_protege_relationships', json_schema_extra={"ui:hidden": True})
    awardee_key_mentor: int | None = Field(None, title='Awardee Key Mentor', description='HigherGov Awardee Key of the Mentor')
    awardee_key_mentor_parent: int | None = Field(None, title='Awardee Key Mentor Parent', description='HigherGov Awardee Key of the Mentor Parent')
    awardee_key_protege: int | None = Field(None, title='Awardee Key Protege', description='HigherGov Awardee Key of the Protege')
    awardee_key_protege_parent: int | None = Field(None, title='Awardee Key Protege Parent', description='HigherGov Awardee Key of the Protege parent')


class ListPrimeSubPartnerships(_Page):
    """Description: Teaming partnerships between different Awardees.    Update Frequency: Updated Weekly with new subaward data."""
    operation: Literal['list_prime_sub_partnerships'] = Field('list_prime_sub_partnerships', json_schema_extra={"ui:hidden": True})
    awardee_key_prime: int | None = Field(None, title='Awardee Key Prime', description='HigherGov Awardee Key of the prime recipient')
    awardee_key_prime_parent: int | None = Field(None, title='Awardee Key Prime Parent', description='HigherGov Awardee Key of the prime recipient parent')
    awardee_key_sub: int | None = Field(None, title='Awardee Key Sub', description='HigherGov Awardee Key of the subawardee')
    awardee_key_sub_parent: int | None = Field(None, title='Awardee Key Sub Parent', description='HigherGov Awardee Key of the subawardee parent')


class ListContracts(_Page):
    """Description: Federal prime contract awards.    Update Frequency: Daily by 2am (for two days prior)   Update Check Field: last_modified_date."""
    operation: Literal['list_contracts'] = Field('list_contracts', json_schema_extra={"ui:hidden": True})
    award_id: str | None = Field(None, title='Award Id', description='The government Award ID', min_length=1, max_length=4096)
    awardee_key: int | None = Field(None, title='Awardee Key', description='HigherGov Awardee Key')
    awardee_key_parent: int | None = Field(None, title='Awardee Key Parent', description='HigherGov Awardee Key (Parent Level)')
    awardee_uei: str | None = Field(None, title='Awardee Uei', description='Awardee UEI', min_length=1, max_length=4096)
    awardee_uei_parent: str | None = Field(None, title='Awardee Uei Parent', description='Awardee UEI Parent', min_length=1, max_length=4096)
    awarding_agency_key: int | None = Field(None, title='Awarding Agency Key', description='HigherGov Awarding Agency key')
    captured_date: date | None = Field(None, title='Captured Date', description='Date HigherGov captured the last amendment. Due to legally defined delays in government reporting, this may differ from last_modified_date by up to 1-90 days.')
    funding_agency_key: int | None = Field(None, title='Funding Agency Key', description='HigherGov Funding Agency key')
    last_modified_date: date | None = Field(None, title='Last Modified Date', description='Last modified date filter (format: YYYY-MM-DD)')
    naics_code: str | None = Field(None, title='Naics Code', description='Awards NAICS code', min_length=1, max_length=4096)
    ordering: Literal['-action_date', '-current_total_value_of_award', '-last_modified_date', '-period_of_performance_potential_end_date', '-period_of_performance_start_date', '-potential_total_value_of_award', '-total_dollars_obligated', 'action_date', 'current_total_value_of_award', 'last_modified_date', 'period_of_performance_potential_end_date', 'period_of_performance_start_date', 'potential_total_value_of_award', 'total_dollars_obligated'] | None = Field(None, title='Ordering', description='Which field to use when ordering the results.')
    parent_award_id: str | None = Field(None, title='Parent Award Id', description='The government Award ID of the parent Award', min_length=1, max_length=4096)
    psc_code: str | None = Field(None, title='Psc Code', description='PSC code', min_length=1, max_length=4096)
    search_id: str | None = Field(None, title='Search Id', description='HigherGov SearchID', min_length=1, max_length=4096)
    vehicle_key: int | None = Field(None, title='Vehicle Key', description='HigherGov Vehicle key')


class ListDocuments(_Page):
    """Description: Returns paths for downloading the documents associated with the opportunity. The related_key is required and is found in the document_path field in the Opportunity endpoint.   Update Frequency: Real time."""
    operation: Literal['list_documents'] = Field('list_documents', json_schema_extra={"ui:hidden": True})
    ordering: str | None = Field(None, title='Ordering', description='Which field to use when ordering the results.', min_length=1, max_length=4096)
    related_key: str = Field(..., title='Related Key', description='Document Key', min_length=1, max_length=4096)


class ListGrants(_Page):
    """Description: Federal prime grant awards.    Update Frequency: Daily by 2am (for two days prior)   Update Check Field: last_modified_date."""
    operation: Literal['list_grants'] = Field('list_grants', json_schema_extra={"ui:hidden": True})
    award_id: str | None = Field(None, title='Award Id', description='The government Award ID', min_length=1, max_length=4096)
    awardee_key: int | None = Field(None, title='Awardee Key', description='HigherGov Awardee Key')
    awardee_key_parent: int | None = Field(None, title='Awardee Key Parent', description='HigherGov Awardee Key (Parent Level)')
    awardee_uei: str | None = Field(None, title='Awardee Uei', description='Awardee UEI', min_length=1, max_length=4096)
    awardee_uei_parent: str | None = Field(None, title='Awardee Uei Parent', description='Awardee UEI Parent', min_length=1, max_length=4096)
    awarding_agency_key: int | None = Field(None, title='Awarding Agency Key', description='HigherGov Awarding Agency key')
    cfda_program_number: str | None = Field(None, title='Cfda Program Number', description='Grant Program Number (CFDA)', min_length=1, max_length=4096)
    funding_agency_key: int | None = Field(None, title='Funding Agency Key', description='HigherGov Funding Agency key')
    last_modified_date: date | None = Field(None, title='Last Modified Date', description='Last modified date filter (format: YYYY-MM-DD)')
    ordering: Literal['-action_date', '-last_modified_date', '-total_obligated_amount', 'action_date', 'last_modified_date', 'total_obligated_amount'] | None = Field(None, title='Ordering', description='Which field to use when ordering the results.')
    search_id: str | None = Field(None, title='Search Id', description='HigherGov SearchID', min_length=1, max_length=4096)


class ListGrantPrograms(_Page):
    """Description:Government Assistance Programs (Grant Programs or CFDAs).    Update Frequency: Ad hoc as new programs are released, typically monthly."""
    operation: Literal['list_grant_programs'] = Field('list_grant_programs', json_schema_extra={"ui:hidden": True})
    agency_key: int | None = Field(None, title='Agency Key', description='HigherGov Agency key')
    cfda_program_number: str | None = Field(None, title='Cfda Program Number', description='CFDA Program Number for the grant program', min_length=1, max_length=4096)


class ListIndefiniteDeliveryVehicles(_Page):
    """Description: Federal prime IDV awards.    Update Frequency: Daily by 2am (for two days prior)   Update Check Field: last_modified_date."""
    operation: Literal['list_indefinite_delivery_vehicles'] = Field('list_indefinite_delivery_vehicles', json_schema_extra={"ui:hidden": True})
    award_id: str | None = Field(None, title='Award Id', description='The government Award ID', min_length=1, max_length=4096)
    awardee_key: int | None = Field(None, title='Awardee Key', description='HigherGov Awardee Key')
    awardee_key_parent: int | None = Field(None, title='Awardee Key Parent', description='HigherGov Awardee Key (Parent Level)')
    awardee_uei: str | None = Field(None, title='Awardee Uei', description='Awardee UEI', min_length=1, max_length=4096)
    awardee_uei_parent: str | None = Field(None, title='Awardee Uei Parent', description='Awardee UEI Parent', min_length=1, max_length=4096)
    awarding_agency_key: int | None = Field(None, title='Awarding Agency Key', description='HigherGov Awarding Agency key')
    funding_agency_key: int | None = Field(None, title='Funding Agency Key', description='HigherGov Funding Agency key')
    last_modified_date: date | None = Field(None, title='Last Modified Date', description='Last modified date filter (format: YYYY-MM-DD)')
    naics_code: str | None = Field(None, title='Naics Code', description='Awards NAICS code', min_length=1, max_length=4096)
    ordering: Literal['-action_date', '-last_modified_date_ordering', '-ordering_period_end_date', '-period_of_performance_start_date', '-potential_total_value_of_award', 'action_date', 'last_modified_date_ordering', 'ordering_period_end_date', 'period_of_performance_start_date', 'potential_total_value_of_award'] | None = Field(None, title='Ordering', description='Which field to use when ordering the results.')
    parent_award_id: str | None = Field(None, title='Parent Award Id', description='The government Award ID of the parent Award', min_length=1, max_length=4096)
    psc_code: str | None = Field(None, title='Psc Code', description='PSC code', min_length=1, max_length=4096)
    vehicle_key: int | None = Field(None, title='Vehicle Key', description='HigherGov Vehicle key')


class ListNaicsCodes(_Page):
    """Description: North American Industry Classification System (NAICS) codes.    Update Frequency: Updated Ad Hoc when codes added or removed by the Census Bureau or the SBA changes size standards"""
    operation: Literal['list_naics_codes'] = Field('list_naics_codes', json_schema_extra={"ui:hidden": True})
    naics_code: str | None = Field(None, title='Naics Code', description='Awards NAICS code', min_length=1, max_length=4096)
    ordering: Literal['-naics_code', 'naics_code'] | None = Field(None, title='Ordering', description='Which field to use when ordering the results.')


class ListNationalStockNumbers(_Page):
    """Description: NATO Stock Number Lookup."""
    operation: Literal['list_national_stock_numbers'] = Field('list_national_stock_numbers', json_schema_extra={"ui:hidden": True})
    cage_code: str | None = Field(None, title='Cage Code', description='Supplier CAGE', min_length=1, max_length=4096)
    nsn: str | None = Field(None, title='Nsn', description='National Stock Number (NSN)', min_length=1, max_length=4096)
    ordering: Literal['-last_price', '-opp_count', '-unit_price', 'last_price', 'opp_count', 'unit_price'] | None = Field(None, title='Ordering', description='Which field to use when ordering the results.')
    part_number: str | None = Field(None, title='Part Number', description='Part Number', min_length=1, max_length=4096)


class ListOpportunities(_Page):
    """Description: Includes federal Contract, DIBBS, Grants, and State and Local Opportunities.    Update Frequency: Updated every 30 minutes   Update Check Field: captured_date."""
    operation: Literal['list_opportunities'] = Field('list_opportunities', json_schema_extra={"ui:hidden": True})
    agency_key: int | None = Field(None, title='Agency Key', description='HigherGov Agency key')
    captured_date: date | None = Field(None, title='Captured Date', description='Date the opportunity was added to HigherGov')
    opp_key: str | None = Field(None, title='Opp Key', description='The HigherGov opportunity key', min_length=1, max_length=4096)
    ordering: Literal['-captured_date', '-due_date', '-posted_date', 'captured_date', 'due_date', 'posted_date'] | None = Field(None, title='Ordering', description='Which field to use when ordering the results.')
    posted_date: date | None = Field(None, title='Posted Date', description='Date the opportunity was posted by the agency in YYYY-MM-DD format')
    search_id: str | None = Field(None, title='Search Id', description='HigherGov SearchID.  The following search search fields are currently supported: Active, Applicant Type (Grant Only), Agency, CAGE Code, Date Due, Date Posted, Exclude Sole Source, Funding Category (Grant Only), Funding Instrument (Grant Only), Grant Program, Keywords, NAICS, NSN, Place of Performance (Federal Contracts Only), PSC, Set Aside, State (State and Local Only), and Value Range', min_length=1, max_length=4096)
    source_id: str | None = Field(None, title='Source Id', description='The source opportunity ID', min_length=1, max_length=4096)
    source_type: str | None = Field(None, title='Source Type', description='Opportunity source type (sam, dibbs, sbir, grant, sled)', min_length=1, max_length=4096)
    version_key: str | None = Field(None, title='Version Key', description='The HigherGov opportunity version key', min_length=1, max_length=4096)


class ListPeople(_Page):
    """Description: Federal and State and Local People.    Update Frequency: Updated in real time.   Update Check Field: as_of_date."""
    operation: Literal['list_people'] = Field('list_people', json_schema_extra={"ui:hidden": True})
    contact_email: str | None = Field(None, title='Contact Email', description='Email address', min_length=1, max_length=4096)
    ordering: Literal['-last_seen', 'last_seen'] | None = Field(None, title='Ordering', description='Which field to use when ordering the results.')


class ListProductServiceCodes(_Page):
    """Description: Product Service Codes (PSC) Codes.    Update Frequency: Updated Ad Hoc when codes added or removed"""
    operation: Literal['list_product_service_codes'] = Field('list_product_service_codes', json_schema_extra={"ui:hidden": True})
    psc_code: str | None = Field(None, title='Psc Code', description='PSC code', min_length=1, max_length=4096)


class ListPursuits(_Page):
    """Description: Returns the authenticated client's HigherGov pursuits tied to their account and managed in https://www.highergov.com/pursuit/. This endpoint is for a user's internal pursuit records, not for searching government opportunities. If you want to look up federal contract, grant, or other opportunities or forecasts, use the Opportunity endpoint instead.   Update Frequency: Real time."""
    operation: Literal['list_pursuits'] = Field('list_pursuits', json_schema_extra={"ui:hidden": True})
    reference_id: int | None = Field(None, title='Reference Id', description='Reference ID for the pursuit (maps to pursuit_key_external).')
    search_id: str | None = Field(None, title='Search Id', description='HigherGov SearchID', min_length=1, max_length=4096)
    unique_key: str | None = Field(None, title='Unique Key', description='Unique internal pursuit key (maps to pursuit_key_internal).', min_length=1, max_length=4096)


class ListStateLocalContracts(_Page):
    """State and Local Government contract awards."""
    operation: Literal['list_state_local_contracts'] = Field('list_state_local_contracts', json_schema_extra={"ui:hidden": True})
    captured_date: date | None = Field(None, title='Captured Date', description='Date the opportunity was added to HigherGov')
    end_date: date | None = Field(None, title='End Date', description='Latest end date for the award. Format: YYYY-MM-DD.')
    keyword: str | None = Field(None, title='Keyword', description='Free-text search across state/local contract awards.', min_length=1, max_length=4096)
    ordering: Literal['-award_amount', '-captured_date', '-end_date', '-start_date', 'award_amount', 'captured_date', 'end_date', 'start_date'] | None = Field(None, title='Ordering', description="Order results by a particular field. Prefix with '-' for descending order.")
    search_id: str | None = Field(None, title='Search Id', description='HigherGov SearchID', min_length=1, max_length=4096)
    start_date: date | None = Field(None, title='Start Date', description='Earliest start date for the award. Format: YYYY-MM-DD.')


class ListSubcontracts(_Page):
    """Description: Federal prime subcontract award data.    Update Frequency: Updated weekly.    Update Check Field: last_modified_date (note that data is often reported late by prime awardees and we recommend periodically looking back over the prior year to fully sync new records)."""
    operation: Literal['list_subcontracts'] = Field('list_subcontracts', json_schema_extra={"ui:hidden": True})
    awardee_key: int | None = Field(None, title='Awardee Key', description='HigherGov Awardee Key')
    awardee_key_parent: int | None = Field(None, title='Awardee Key Parent', description='HigherGov Awardee Key (Parent Level)')
    awardee_uei: str | None = Field(None, title='Awardee Uei', description='Awardee UEI', min_length=1, max_length=4096)
    awardee_uei_parent: str | None = Field(None, title='Awardee Uei Parent', description='Awardee UEI Parent', min_length=1, max_length=4096)
    awarding_agency_key: int | None = Field(None, title='Awarding Agency Key', description='HigherGov Awarding Agency key')
    funding_agency_key: int | None = Field(None, title='Funding Agency Key', description='HigherGov Funding Agency key')
    last_modified_date: date | None = Field(None, title='Last Modified Date', description='Last modified date filter (format: YYYY-MM-DD)')
    ordering: Literal['-last_modified_date', '-subaward_action_date', '-subaward_amount_total', 'last_modified_date', 'subaward_action_date', 'subaward_amount_total'] | None = Field(None, title='Ordering', description='Which field to use when ordering the results.')


class ListSubgrants(_Page):
    """Description: Federal prime subgrant award data.    Update Frequency: Updated weekly.    Update Check Field: last_modified_date (note that data is often reported late by prime awardees and we recommend periodically looking back over the prior year to fully sync new records)."""
    operation: Literal['list_subgrants'] = Field('list_subgrants', json_schema_extra={"ui:hidden": True})
    awardee_key: int | None = Field(None, title='Awardee Key', description='HigherGov Awardee Key')
    awardee_key_parent: int | None = Field(None, title='Awardee Key Parent', description='HigherGov Awardee Key (Parent Level)')
    awardee_uei: str | None = Field(None, title='Awardee Uei', description='Awardee UEI', min_length=1, max_length=4096)
    awardee_uei_parent: str | None = Field(None, title='Awardee Uei Parent', description='Awardee UEI Parent', min_length=1, max_length=4096)
    awarding_agency_key: int | None = Field(None, title='Awarding Agency Key', description='HigherGov Awarding Agency key')
    funding_agency_key: int | None = Field(None, title='Funding Agency Key', description='HigherGov Funding Agency key')
    last_modified_date: date | None = Field(None, title='Last Modified Date', description='Last modified date filter (format: YYYY-MM-DD)')
    ordering: Literal['-last_modified_date', '-subaward_action_date', '-subaward_amount_total', 'last_modified_date', 'subaward_action_date', 'subaward_amount_total'] | None = Field(None, title='Ordering', description='Which field to use when ordering the results.')


class ListContractVehicles(_Page):
    """Description: Federal multi-award contract vehicles.    Update Frequency: Updated ad hoc as new awards are made."""
    operation: Literal['list_contract_vehicles'] = Field('list_contract_vehicles', json_schema_extra={"ui:hidden": True})
    ordering: Literal['-award_date', 'award_date'] | None = Field(None, title='Ordering', description='Which field to use when ordering the results.')
    vehicle_key: int | None = Field(None, title='Vehicle Key', description='HigherGov Vehicle key')


OPERATIONS = {'list_agencies': '/api-external/agency/', 'list_awardees': '/api-external/awardee/', 'list_mentor_protege_relationships': '/api-external/awardee-mp/', 'list_prime_sub_partnerships': '/api-external/awardee-partnership/', 'list_contracts': '/api-external/contract/', 'list_documents': '/api-external/document/', 'list_grants': '/api-external/grant/', 'list_grant_programs': '/api-external/grant-program/', 'list_indefinite_delivery_vehicles': '/api-external/idv/', 'list_naics_codes': '/api-external/naics/', 'list_national_stock_numbers': '/api-external/nsn/', 'list_opportunities': '/api-external/opportunity/', 'list_people': '/api-external/people/', 'list_product_service_codes': '/api-external/psc/', 'list_pursuits': '/api-external/pursuit/', 'list_state_local_contracts': '/api-external/sl-contract/', 'list_subcontracts': '/api-external/subcontract/', 'list_subgrants': '/api-external/subgrant/', 'list_contract_vehicles': '/api-external/vehicle/'}

Operation = Annotated[Union[ListAgencies, ListAwardees, ListMentorProtegeRelationships, ListPrimeSubPartnerships, ListContracts, ListDocuments, ListGrants, ListGrantPrograms, ListIndefiniteDeliveryVehicles, ListNaicsCodes, ListNationalStockNumbers, ListOpportunities, ListPeople, ListProductServiceCodes, ListPursuits, ListStateLocalContracts, ListSubcontracts, ListSubgrants, ListContractVehicles], Field(discriminator="operation")]


class HigherGovConfig(NodeConfig[Operation, HigherGovAPIKeyCredential]):
    pass


def _redact(value, secret):
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items() if k.lower() not in {"api_key", "authorization"}}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, str):
        for token in {secret, quote(secret, safe=""), quote_plus(secret)}:
            value = value.replace(token, "[redacted]")
        return value
    return value


class HigherGovNode(WorkflowNode):
    integration_type = "automation-highergov"
    connection_evidence = ConnectionEvidence(
        noun="pursuits", operation="list_pursuits",
        label_keys=("pursuit_name", "reference_id", "unique_key"),
    )

    @classmethod
    def get_config_model(cls):
        return HigherGovConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a HigherGov API key")
        credential = self.config.credentials
        config = self.config.config
        params = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        # page_size is a string in HigherGov's published schema.
        params["page_size"] = str(params["page_size"])
        params["api_key"] = credential.api_key
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                async with client.stream("GET", BASE_URL + OPERATIONS[config.operation],
                        params=params, headers={"Accept": "application/json"}) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 16 * 1024 * 1024:
                            raise ValueError("HigherGov response exceeds 16 MiB; reduce the page size")
                    if response.status_code != 200:
                        message = bytes(raw).decode("utf-8", errors="replace")[:2000]
                        output = {"status": "error", "status_code": response.status_code,
                                  "error": "HigherGov HTTP " + str(response.status_code) + ": " + message}
                    else:
                        media = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
                        if media != "application/json":
                            raise ValueError("HigherGov returned a non-JSON response")
                        try:
                            body = json.loads(raw)
                        except (ValueError, UnicodeError):
                            raise ValueError("HigherGov returned invalid JSON") from None
                        output = self._page(body, config)
        except (httpx.HTTPError, OSError, SSRFError):
            # HTTP client exceptions contain the authenticated query URL.
            raise ValueError("HigherGov request did not complete; try again later") from None
        output = _redact(output, credential.api_key)
        await self.emit(output)
        return output

    @staticmethod
    def _page(body, config):
        if not isinstance(body, dict) or body.get("error") or body.get("errors") or body.get("success") is False:
            raise ValueError("HigherGov returned an unexpected or failed response")
        results = body.get("results")
        if not isinstance(results, list) or any(not isinstance(row, dict) for row in results):
            raise ValueError("HigherGov response must contain a results array of records")
        meta = body.get("meta", {})
        if not isinstance(meta, dict):
            raise ValueError("HigherGov pagination metadata is invalid")
        pagination = meta.get("pagination", {})
        if not isinstance(pagination, dict):
            raise ValueError("HigherGov pagination metadata is invalid")
        for key in ("page", "pages", "count"):
            if key in pagination and (type(pagination[key]) is not int or pagination[key] < 0):
                raise ValueError("HigherGov pagination counters are invalid")
        current, pages = pagination.get("page"), pagination.get("pages")
        next_page = current + 1 if current is not None and pages is not None and current < pages else None
        # Deliberately omit links: they may repeat the secret api_key. Continue
        # with a numeric page on this operation's fixed origin and route.
        return {"status": "success", "operation": config.operation, "results": results,
                "pagination": pagination, "next_page_number": next_page,
                "pagination_known": current is not None and pages is not None}
