"""Starbridge public API v1.0: organization bridges and public-sector intelligence.

Contract: https://core-http2-157602306522.us-central1.run.app/external/public/swagger/documentation.yaml
"""
from typing import Annotated, Literal, Optional, Union, Any
from urllib.parse import quote
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE = "https://dashboard.starbridge.ai"

class StarbridgeCredential(BaseModel):
    model_config = ConfigDict(title="Starbridge API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dashboard.starbridge.ai",
        "x-credential-instructions": "Paste your Starbridge API bearer token. NoClick checks the bridges visible to your account."})
    credential_type: Literal["starbridge_api_token"] = Field("starbridge_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class StarbridgeSearchBuyersConfig(_Input):
    """Search Buyers."""
    operation: Literal['search_buyers'] = Field('search_buyers', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'Search Buyers'})
    buyerName: str = Field(..., description='Buyer name to search Buyer entity by.')
    buyerStateCode: Optional[str] = Field(None, description="StateMapping enum value for the buyer's ISO 3166-2 state code. Optional.")
    limit: Optional[str] = Field(None, description='Maximum number of buyers to return. Defaults to 10.')

class StarbridgeGetBuyerAttributesBulkConfig(_Input):
    """Get Buyer Attributes in bulk."""
    operation: Literal['get_buyer_attributes_bulk'] = Field('get_buyer_attributes_bulk', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'Get Buyer Attributes in bulk'})
    buyerId: str = Field(..., description='buyerId')
    attribute: Optional[list[Literal['Id', 'Name', 'CommonName', 'ParentName', 'ParentBuyerId', 'Type', 'Classifications', 'Url', 'LinkedinSlug', 'Zip', 'CountryCode', 'StateCode', 'StateName', 'City', 'County', 'Address', 'Street1', 'Street2', 'MainPhoneNumber', 'ContractVehicles', 'EmailDomains', 'Population', 'PopulationTrend', 'PopulationOneYearChangePercentage', 'PopulationFiveYearChangePercentage', 'PopulationDensityPerSquareMile', 'CountyHudAssistedHousingUnitCount', 'HudAreaMedianFamilyIncome', 'CountyMedicareAdvantageEnrollmentCount', 'CountyMedicareAdvantagePenetrationPercentage', 'CountyMedicareMedicaidEnrolleeCount', 'CountyOriginalMedicareEnrollmentCount', 'FemaDisasterDeclarationCount', 'FemaFireDisasterDeclarationCount', 'FemaFloodDisasterDeclarationCount', 'FemaSevereStormDisasterDeclarationCount', 'FemaWinterStormDisasterDeclarationCount', 'BudgetAmount', 'BudgetSbita', 'BudgetUrl', 'BudgetLatestYear', 'BudgetConfidence', 'SchoolDistrictType', 'HigherEdFullTimeEnrollment', 'HigherEdInstitutionType', 'DepartmentName', 'DepartmentCode', 'AgencyName', 'OfficeCodeArray', 'AgencyCode', 'AiAdoptionScore', 'AiAdoptionSummary', 'StartupFriendlinessScore', 'StartupFriendlinessSummary', 'ProcurementHellScore', 'AngelProcurementSummary', 'IpedsIdNumeric', 'TotalEnrollment', 'NcesId', 'NcesStateDistrictId', 'CensusIdPid6', 'CensusIdGidId', 'SgcId', 'HigherEdGraduationRate', 'HigherEdRetentionRate', 'HigherEdAcceptanceRate', 'HigherEdYieldRate', 'HigherEdGraduationEnrollment', 'HigherEdUndergradEnrollment', 'HigherEdOnlineOnlyEnrollment', 'HigherEdControlOfInstitution', 'HigherEdForProfitStatus', 'HigherEdHbcuStatus', 'HigherEdLevelOfInstitution', 'HigherEdRecruitmentAdmissionsCrmArray', 'HigherEdEndowment', 'HigherEdTotalExpenses', 'HigherEdMascot', 'HigherEdNumberOfOnCampusResidents', 'HigherEdNumberOfFullTimeEmployees', 'HigherEdSisModernizationStatus', 'HigherEdPrimaryRegionalAccreditor', 'HigherEdAccreditationSummary', 'HigherEdAccreditationStatus', 'DapipId', 'HigherEdNextAccreditationReviewDate', 'HigherEdSystem', 'CommunityCollegeSystem', 'HigherEdContinuingProfessionalEducationOffered', 'Sis', 'LmsArray', 'SchoolDistrictLocale', 'SchoolDistrictFullTimeEquivalentTeachers', 'LowestGradeOffered', 'HighestGradeOffered', 'SchoolYearStartDate', 'SchoolYearEndDate', 'SchoolDistrictNumberOfSchools', 'SchoolDistrictNewlyOpenedSchoolCount', 'SchoolDistrictClosedSchoolCount', 'SchoolDistrictElementarySchools', 'SchoolDistrictMiddleSchools', 'SchoolDistrictHighSchools', 'SchoolDistrictTotalStaff', 'SchoolDistrictMedianHouseholdIncome', 'SchoolDistrictSector', 'RegionalEducationServiceAgencyName', 'RegionalEducationServiceAgencyBuyerId', 'SchoolManagementOrganizationName', 'SchoolManagementOrganizationBuyerId', 'EnglishLearners', 'BlackPercentage', 'LatinoPercentage', 'WhitePercentage', 'StudentTeacherRatio', 'SchoolSector', 'SchoolLevel', 'AlternativeSchool', 'SchoolCurriculumProgramArray', 'ReligiousAffiliation', 'StudentGenderComposition', 'SchoolVirtualStatus', 'Subentity', 'FiscalYearStartDate', 'FreeOrReducedLunchEligiblePercentage', 'FdId', 'FireDepartmentType', 'FireDepartmentOrganizationType', 'FireDepartmentPrimaryAgency', 'FireDepartmentNumberOfStations', 'FireDepartmentActiveFirefightersCareer', 'FireDepartmentActiveFirefightersVolunteer', 'FireDepartmentActiveFirefightersPaidPerCall', 'FireDepartmentNonFirefightingCivilian', 'FireDepartmentNonFirefightingVolunteer', 'PoliceOri', 'PoliceOfficerCt', 'PoliceDepartmentType', 'HasCampusPolice', 'Psap', 'StateAgencySector', 'EmployeeFte', 'WaterSystemPopulationServed', 'SpecialDistrictResidentPopulationEstimate', 'MotorCarrierPowerUnits', 'PropensityToSpendScore', 'PropensityToSpendSummary', 'BudgetChangeAnalysisSourceUrls', 'PropensityToSpend', 'YoyChangeInEnrollment', 'EnrollmentTrend', 'EnrollmentTrendBasedOnFte', 'AtsiDesignation', 'SpecialEducationEnrollment', 'SpecialEducationEnrollmentPercentage', 'TsiDesignation', 'CsiDesignation', 'SchoolDistrictTotalRevenue', 'SchoolDistrictFederalRevenue', 'SchoolDistrictStateRevenue', 'SchoolDistrictLocalRevenue', 'PerPupilExpenditure', 'MathProficiencyPercentage', 'ElaProficiencyPercentage', 'GraduationRatePercentage', 'ChronicAbsenteeismPercentage', 'MathProficiencyStatePercentile', 'ElaProficiencyStatePercentile', 'TitleIFunding', 'TitleIiFunding', 'TitleIiiFunding', 'TitleIvFunding', 'TitleVFunding', 'FederalGrantComplianceRisk', 'FederalGrantComplianceCapSummary', 'ErateFunding', 'IhbgFinalAllocationAmount', 'TribalTransportationProgramShare', 'BuyerLocationLatitude', 'BuyerLocationLongitude', 'StarbridgeUrl']]] = Field(None, description='The attribute keys to retrieve. Pass multiple `attribute` parameters for multiple keys, or omit entirely to return all available attributes. Each key is a BuyerField value; `getBuyerSchema` lists them with what each one returns.')

class StarbridgeGetFileDownloadLinksConfig(_Input):
    """Get Buyer File Download Links."""
    operation: Literal['get_file_download_links'] = Field('get_file_download_links', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'Get Buyer File Download Links'})
    fileId: UUID = Field(..., description='Buyer file ID, from `researchBuyerFiles`.')

class StarbridgeGetOpportunityConfig(_Input):
    """Get Opportunity."""
    operation: Literal['get_opportunity'] = Field('get_opportunity', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'Get Opportunity'})
    opportunityId: str = Field(..., description='opportunityId')
    includeFiles: Optional[bool] = Field(None, description='Whether to include the source files. Set false when you only need the record.')
    includeLineItems: Optional[bool] = Field(None, description='Whether to include parsed purchase-order line items. Set false to skip an extra lookup.')

class StarbridgeListBridgesConfig(_Input):
    """List Bridges."""
    operation: Literal['list_bridges'] = Field('list_bridges', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'List Bridges'})
    sortField: Optional[Literal['Name', 'RowsCount', 'Type', 'CreatedBy', 'CreditUsage', 'SharedWith', 'LastUpdatedByUser', 'CreatedAt']] = Field(None, description='Name, EntriesCount, Type, CreatedBy, CreditUsage, SharedWith, LastUpdatedByUser or CreatedAt')
    sortDirection: Optional[Literal['ASC', 'DESC']] = Field(None, description='ASC or DESC')
    query: Optional[str] = Field(None, description='Filter by bridge name (substring match)')
    viewMode: Optional[str] = Field(None, description='viewMode')
    folderId: Optional[str] = Field(None, description='Only bridges inside this folder (UUID)')
    subscribedOnly: Optional[str] = Field(None, description='true to return only bridges you are subscribed to')
    live: Optional[str] = Field(None, description='true for only bridges with live updates on, false for only those with them off; a bridge type without the setting counts as on')
    pageNumber: Optional[int] = Field(None, description='Page number, 1-based. Minimum 1.', ge=1)
    pageSize: Optional[int] = Field(None, description='Page size. Must be > 0 and <= 100. Prefer <= 20.', ge=1, le=100)
    filterType: Optional[list[Literal['RFP', 'Meeting', 'Purchase', 'Buyer', 'TopBuyer', 'Contact', 'Signal', 'Conference', 'JobChange', 'VendorPresence', 'ProductCompetitorPresence', 'CompanionPresence']]] = Field(None, description='Bridge type(s) to include. Without it the list holds RFP, Meeting, Purchase, Buyer, Contact, Signal, Conference, JobChange, VendorPresence bridges; name TopBuyer, ProductCompetitorPresence or CompanionPresence to list those')
    statuses: Optional[list[Literal['Initializing', 'Matching', 'Draft', 'Open', 'Failed', 'Deleting']]] = Field(None, description='Bridge lifecycle status(es) to include: Open (live), Initializing and Matching (still building), Draft, Failed, Deleting')
    createdByUserId: Optional[list[str]] = Field(None, description='Only bridges owned by these user id(s)')
    userIdsHaveAccessTo: Optional[list[str]] = Field(None, description='Only bridges these user id(s) can see — how you find what a teammate has access to')
    buyerListId: Optional[list[str]] = Field(None, description='Only bridges whose buyer scope is one of these saved buyer lists')

class StarbridgeGetBridgeConfig(_Input):
    """Get Bridge."""
    operation: Literal['get_bridge'] = Field('get_bridge', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'Get Bridge'})
    bridgeId: UUID = Field(..., description='bridgeId')

class StarbridgeListBridgeRowsConfig(_Input):
    """List Bridge Rows."""
    operation: Literal['list_bridge_rows'] = Field('list_bridge_rows', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'List Bridge Rows'})
    bridgeId: UUID = Field(..., description='bridgeId')
    pageNumber: Optional[int] = Field(None, description='Page number, 1-based. Minimum 1.', ge=1)
    pageSize: Optional[int] = Field(None, description='Page size. Must be > 0 and <= 100. Prefer <= 20.', ge=1, le=100)
    filters: Optional[dict[str, Any]] = Field(None, description='\n        Filter criteria for bridge rows. All `terms` are combined with logical AND — a row must\n        satisfy every term to be included. Provide an empty `terms` list (or omit `filters`) to\n        return all rows.\n    ')
    sorts: Optional[list[dict[str, Any]]] = Field(None, description='\n        Sort specification for rows. For each sort term, `column` should be a bridge\n        column\'s `columnId` UUID — call `getBridgeColumnMetadata` to look it up. The\n        column\'s display name, `key`, or any prefixed reference is not a valid value.\n        A small set of common entry-level fields (`entryId`, `entryName`, `triggeredAt`)\n        is also accepted but discouraged. Fields computed per row when the Bridge is read —\n        `op:added_date` ("Added to Bridge") and `bridge:entry_url` — are never sortable and\n        return 400; sort by `triggeredAt` instead. The synthetic column `rowUpdatedAt` sorts by when\n        the row was last updated — sort `DESC` to poll for recently-changed rows, matching the\n        `updatedAt` field in the response. Sort columns that are not mapped on the server return 400.\n     Omit `sorts` for the bridge\'s default order, the order `runRows: FirstFiveRows` takes its five rows from. A sort on an object column is refused: sort a Top Buyers bridge by its Account Scoring Score column, not the Account Score object. An enumeration column such as Fit Band sorts alphabetically, so filter it with `Any` instead. A `processBridgeRows` `limit` takes its rows from the same default order.')
    query: Optional[str] = Field(None, description="Full-text search across the rows' searchable content")
    buyerScope: Optional[dict[str, Any]] = Field(None, description='Narrows the rows to those whose buyer matches this scope, on top of `filters`. Either a saved buyer list (`buyerListId`) or inline `terms` — never both. Use `listBuyerLists` to find a list id.')
    columnIds: Optional[list[str]] = Field(None, description="Project each row's `columns` down to these column ids. Every id must belong to this bridge. Omit to get every column `getBridgeFull` lists, including the ones hidden from the table view — send it whenever you only need a few, it is the cheapest way to keep a wide bridge inside a context window, and a link column left out is not resolved at all.")
    archived: Optional[bool] = Field(None, description="True to list the bridge's archived rows instead of its live ones, most recently archived first unless `sorts` is sent — `rowArchivedAt` sorts by archive date; `filters`, `query`, `buyerScope` and `columnIds` apply the same way")
    includeBasis: Optional[bool] = Field(None, description="Whether to add each cell's `basis`: the reasoning, confidence and cited sources behind its value, for explaining why a row holds what it does. Only columns that research the web, such as web agent columns, record one. A basis can run to thousands of characters, so send it with `columnIds` set to just the columns you are explaining and a `pageSize` of 5 or fewer. Each cell lists at most its first 10 citations, each with at most 3 excerpts cut to 500 characters. Defaults to false.")

class StarbridgeSetBridgeRowStatusConfig(_Input):
    """Set Bridge Row Status."""
    operation: Literal['set_bridge_row_status'] = Field('set_bridge_row_status', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'Set Bridge Row Status'})
    bridgeId: UUID = Field(..., description='bridgeId')
    rowId: str = Field(..., description='rowId')
    newStatus: Literal['New', 'Actioned', 'Saved', 'Attending', 'Sponsoring', 'Not Interested'] = Field(..., description='newStatus')

class StarbridgeGetBridgeColumnMetadataConfig(_Input):
    """List existing columns with their per-type settings."""
    operation: Literal['get_bridge_column_metadata'] = Field('get_bridge_column_metadata', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'List existing columns with their per-type settings'})
    bridgeId: UUID = Field(..., description='bridgeId')

class StarbridgeListRecentBuyerSignalsConfig(_Input):
    """List Recent Buyer Signals."""
    operation: Literal['list_recent_buyer_signals'] = Field('list_recent_buyer_signals', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'List Recent Buyer Signals'})
    triggerIds: Optional[list[str]] = Field(None, description='Limit results to signals from these bridge ids.')
    query: Optional[str] = Field(None, description='Free-text search over signal name and column values')
    sort: Optional[Literal['Date', 'Hotness']] = Field(None, description='Sort field. Date = by signal date, Hotness = by hotness score. Always descending. Date is the default.')
    pageNumber: Optional[int] = Field(None, description='Page number (1-based)', ge=1)
    pageSize: Optional[int] = Field(None, description='Page size', ge=1, le=100)
    buyerId: str = Field(..., description='UUID of the buyer whose signals to return.')
    filterType: Optional[list[Literal['RFP', 'Meeting', 'Purchase', 'Buyer', 'TopBuyer', 'Contact', 'Signal', 'Conference', 'JobChange', 'VendorPresence', 'ProductCompetitorPresence', 'CompanionPresence']]] = Field(None, description='Filter by bridge filter type (repeatable).')
    status: Optional[list[Literal['New', 'Actioned', 'Saved', 'Attending', 'Sponsoring', 'NotInterested']]] = Field(None, description='Filter by row status. Defaults to New when omitted.')
    relativeDatePeriodFrom: Optional[Literal['LastOneDay', 'LastSevenDays', 'LastThirtyDays', 'LastSixtyDays', 'LastOneMonths', 'LastTwoMonths', 'LastThreeMonths', 'LastSixMonths', 'LastNineMonths', 'LastYear', 'LastTwoYears']] = Field(None, description='Lower bound on the signal date as a relative period.')

class StarbridgeListTopRecentSignalsConfig(_Input):
    """List Top Recent Signals."""
    operation: Literal['list_top_recent_signals'] = Field('list_top_recent_signals', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'List Top Recent Signals'})
    triggerIds: Optional[list[str]] = Field(None, description='Limit results to signals from these bridge ids.')
    query: Optional[str] = Field(None, description='Free-text search over signal name and column values')
    sort: Optional[Literal['Date', 'Hotness']] = Field(None, description='Sort field. Hotness = by hotness score, Date = by signal date. Always descending. Hotness is the default.')
    pageNumber: Optional[int] = Field(None, description='Page number (1-based)', ge=1)
    pageSize: Optional[int] = Field(None, description='Page size', ge=1, le=100)
    filterType: Optional[list[Literal['RFP', 'Meeting', 'Purchase', 'Buyer', 'TopBuyer', 'Contact', 'Signal', 'Conference', 'JobChange', 'VendorPresence', 'ProductCompetitorPresence', 'CompanionPresence']]] = Field(None, description='Filter by bridge filter type (repeatable).')
    status: Optional[list[Literal['New', 'Actioned', 'Saved', 'Attending', 'Sponsoring', 'NotInterested']]] = Field(None, description='Filter by row status. Defaults to New when omitted.')
    relativeDatePeriodFrom: Optional[Literal['LastOneDay', 'LastSevenDays', 'LastThirtyDays', 'LastSixtyDays', 'LastOneMonths', 'LastTwoMonths', 'LastThreeMonths', 'LastSixMonths', 'LastNineMonths', 'LastYear', 'LastTwoYears']] = Field(None, description='Lower bound on the signal date as a relative period.')

class StarbridgeGetBuyerSummaryConfig(_Input):
    """Get Buyer Summary."""
    operation: Literal['get_buyer_summary'] = Field('get_buyer_summary', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'Get Buyer Summary'})
    buyerId: str = Field(..., description='buyerId')

class StarbridgeGetBuyerSummaryV2Config(_Input):
    """Get Buyer Summary V2."""
    operation: Literal['get_buyer_summary_v2'] = Field('get_buyer_summary_v2', json_schema_extra={"ui:hidden": True, "x-is-trigger": False, "x-display-name": 'Get Buyer Summary V2'})
    buyerId: str = Field(..., description='buyerId')

class StarbridgeOnUpdatedRowConfig(PollTriggerConfigBase):
    """New or updated bridge rows. Technical maintenance can also advance updatedAt.

    Polls up to 2,000 rows; larger bridges fail without advancing the baseline.
    """
    operation: Literal["on_new_or_updated_row"] = Field("on_new_or_updated_row", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "New or updated bridge row"})
    bridgeId: UUID = Field(..., title="Bridge ID")

StarbridgeConfig = Annotated[Union[StarbridgeSearchBuyersConfig, StarbridgeGetBuyerAttributesBulkConfig, StarbridgeGetFileDownloadLinksConfig, StarbridgeGetOpportunityConfig, StarbridgeListBridgesConfig, StarbridgeGetBridgeConfig, StarbridgeListBridgeRowsConfig, StarbridgeSetBridgeRowStatusConfig, StarbridgeGetBridgeColumnMetadataConfig, StarbridgeListRecentBuyerSignalsConfig, StarbridgeListTopRecentSignalsConfig, StarbridgeGetBuyerSummaryConfig, StarbridgeGetBuyerSummaryV2Config, StarbridgeOnUpdatedRowConfig], Field(discriminator="operation")]

class StarbridgeFullConfig(NodeConfig[StarbridgeConfig, StarbridgeCredential]):
    pass

OPERATIONS = {'search_buyers': {'method': 'GET', 'path': '/api/external/buyer/quick/search', 'parameters': [{'name': 'buyerName', 'in': 'query', 'description': 'Buyer name to search Buyer entity by.', 'required': True, 'schema': {'type': 'string'}}, {'name': 'buyerStateCode', 'in': 'query', 'description': "StateMapping enum value for the buyer's ISO 3166-2 state code. Optional.", 'schema': {'type': 'string'}}, {'name': 'limit', 'in': 'query', 'description': 'Maximum number of buyers to return. Defaults to 10.', 'schema': {'type': 'string'}}], 'body': []}, 'get_buyer_attributes_bulk': {'method': 'GET', 'path': '/api/external/buyer/{buyerId}/attributes', 'parameters': [{'name': 'buyerId', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}, {'name': 'attribute', 'in': 'query', 'description': 'The attribute keys to retrieve. Pass multiple `attribute` parameters for multiple keys, or omit entirely to return all available attributes. Each key is a BuyerField value; `getBuyerSchema` lists them with what each one returns.', 'schema': {'type': 'array', 'items': {'type': 'string', 'enum': ['Id', 'Name', 'CommonName', 'ParentName', 'ParentBuyerId', 'Type', 'Classifications', 'Url', 'LinkedinSlug', 'Zip', 'CountryCode', 'StateCode', 'StateName', 'City', 'County', 'Address', 'Street1', 'Street2', 'MainPhoneNumber', 'ContractVehicles', 'EmailDomains', 'Population', 'PopulationTrend', 'PopulationOneYearChangePercentage', 'PopulationFiveYearChangePercentage', 'PopulationDensityPerSquareMile', 'CountyHudAssistedHousingUnitCount', 'HudAreaMedianFamilyIncome', 'CountyMedicareAdvantageEnrollmentCount', 'CountyMedicareAdvantagePenetrationPercentage', 'CountyMedicareMedicaidEnrolleeCount', 'CountyOriginalMedicareEnrollmentCount', 'FemaDisasterDeclarationCount', 'FemaFireDisasterDeclarationCount', 'FemaFloodDisasterDeclarationCount', 'FemaSevereStormDisasterDeclarationCount', 'FemaWinterStormDisasterDeclarationCount', 'BudgetAmount', 'BudgetSbita', 'BudgetUrl', 'BudgetLatestYear', 'BudgetConfidence', 'SchoolDistrictType', 'HigherEdFullTimeEnrollment', 'HigherEdInstitutionType', 'DepartmentName', 'DepartmentCode', 'AgencyName', 'OfficeCodeArray', 'AgencyCode', 'AiAdoptionScore', 'AiAdoptionSummary', 'StartupFriendlinessScore', 'StartupFriendlinessSummary', 'ProcurementHellScore', 'AngelProcurementSummary', 'IpedsIdNumeric', 'TotalEnrollment', 'NcesId', 'NcesStateDistrictId', 'CensusIdPid6', 'CensusIdGidId', 'SgcId', 'HigherEdGraduationRate', 'HigherEdRetentionRate', 'HigherEdAcceptanceRate', 'HigherEdYieldRate', 'HigherEdGraduationEnrollment', 'HigherEdUndergradEnrollment', 'HigherEdOnlineOnlyEnrollment', 'HigherEdControlOfInstitution', 'HigherEdForProfitStatus', 'HigherEdHbcuStatus', 'HigherEdLevelOfInstitution', 'HigherEdRecruitmentAdmissionsCrmArray', 'HigherEdEndowment', 'HigherEdTotalExpenses', 'HigherEdMascot', 'HigherEdNumberOfOnCampusResidents', 'HigherEdNumberOfFullTimeEmployees', 'HigherEdSisModernizationStatus', 'HigherEdPrimaryRegionalAccreditor', 'HigherEdAccreditationSummary', 'HigherEdAccreditationStatus', 'DapipId', 'HigherEdNextAccreditationReviewDate', 'HigherEdSystem', 'CommunityCollegeSystem', 'HigherEdContinuingProfessionalEducationOffered', 'Sis', 'LmsArray', 'SchoolDistrictLocale', 'SchoolDistrictFullTimeEquivalentTeachers', 'LowestGradeOffered', 'HighestGradeOffered', 'SchoolYearStartDate', 'SchoolYearEndDate', 'SchoolDistrictNumberOfSchools', 'SchoolDistrictNewlyOpenedSchoolCount', 'SchoolDistrictClosedSchoolCount', 'SchoolDistrictElementarySchools', 'SchoolDistrictMiddleSchools', 'SchoolDistrictHighSchools', 'SchoolDistrictTotalStaff', 'SchoolDistrictMedianHouseholdIncome', 'SchoolDistrictSector', 'RegionalEducationServiceAgencyName', 'RegionalEducationServiceAgencyBuyerId', 'SchoolManagementOrganizationName', 'SchoolManagementOrganizationBuyerId', 'EnglishLearners', 'BlackPercentage', 'LatinoPercentage', 'WhitePercentage', 'StudentTeacherRatio', 'SchoolSector', 'SchoolLevel', 'AlternativeSchool', 'SchoolCurriculumProgramArray', 'ReligiousAffiliation', 'StudentGenderComposition', 'SchoolVirtualStatus', 'Subentity', 'FiscalYearStartDate', 'FreeOrReducedLunchEligiblePercentage', 'FdId', 'FireDepartmentType', 'FireDepartmentOrganizationType', 'FireDepartmentPrimaryAgency', 'FireDepartmentNumberOfStations', 'FireDepartmentActiveFirefightersCareer', 'FireDepartmentActiveFirefightersVolunteer', 'FireDepartmentActiveFirefightersPaidPerCall', 'FireDepartmentNonFirefightingCivilian', 'FireDepartmentNonFirefightingVolunteer', 'PoliceOri', 'PoliceOfficerCt', 'PoliceDepartmentType', 'HasCampusPolice', 'Psap', 'StateAgencySector', 'EmployeeFte', 'WaterSystemPopulationServed', 'SpecialDistrictResidentPopulationEstimate', 'MotorCarrierPowerUnits', 'PropensityToSpendScore', 'PropensityToSpendSummary', 'BudgetChangeAnalysisSourceUrls', 'PropensityToSpend', 'YoyChangeInEnrollment', 'EnrollmentTrend', 'EnrollmentTrendBasedOnFte', 'AtsiDesignation', 'SpecialEducationEnrollment', 'SpecialEducationEnrollmentPercentage', 'TsiDesignation', 'CsiDesignation', 'SchoolDistrictTotalRevenue', 'SchoolDistrictFederalRevenue', 'SchoolDistrictStateRevenue', 'SchoolDistrictLocalRevenue', 'PerPupilExpenditure', 'MathProficiencyPercentage', 'ElaProficiencyPercentage', 'GraduationRatePercentage', 'ChronicAbsenteeismPercentage', 'MathProficiencyStatePercentile', 'ElaProficiencyStatePercentile', 'TitleIFunding', 'TitleIiFunding', 'TitleIiiFunding', 'TitleIvFunding', 'TitleVFunding', 'FederalGrantComplianceRisk', 'FederalGrantComplianceCapSummary', 'ErateFunding', 'IhbgFinalAllocationAmount', 'TribalTransportationProgramShare', 'BuyerLocationLatitude', 'BuyerLocationLongitude', 'StarbridgeUrl']}}, 'style': 'form', 'explode': False}], 'body': []}, 'get_file_download_links': {'method': 'GET', 'path': '/api/external/buyer/file/{fileId}/download-links', 'parameters': [{'name': 'fileId', 'in': 'path', 'description': 'Buyer file ID, from `researchBuyerFiles`.', 'required': True, 'schema': {'type': 'string', 'format': 'uuid'}}], 'body': []}, 'get_opportunity': {'method': 'GET', 'path': '/api/external/opportunity/{opportunityId}/details', 'parameters': [{'name': 'opportunityId', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}, {'name': 'includeFiles', 'in': 'query', 'description': 'Whether to include the source files. Set false when you only need the record.', 'schema': {'type': 'boolean', 'default': 'true'}}, {'name': 'includeLineItems', 'in': 'query', 'description': 'Whether to include parsed purchase-order line items. Set false to skip an extra lookup.', 'schema': {'type': 'boolean', 'default': 'true'}}], 'body': []}, 'list_bridges': {'method': 'GET', 'path': '/api/external/bridge', 'parameters': [{'name': 'sortField', 'in': 'query', 'description': 'Name, EntriesCount, Type, CreatedBy, CreditUsage, SharedWith, LastUpdatedByUser or CreatedAt', 'schema': {'type': 'string', 'default': 'Name', 'enum': ['Name', 'RowsCount', 'Type', 'CreatedBy', 'CreditUsage', 'SharedWith', 'LastUpdatedByUser', 'CreatedAt']}}, {'name': 'sortDirection', 'in': 'query', 'description': 'ASC or DESC', 'schema': {'type': 'string', 'default': 'ASC', 'enum': ['ASC', 'DESC']}}, {'name': 'query', 'in': 'query', 'description': 'Filter by bridge name (substring match)', 'schema': {'type': 'string'}}, {'name': 'viewMode', 'in': 'query', 'schema': {'type': 'string'}}, {'name': 'folderId', 'in': 'query', 'description': 'Only bridges inside this folder (UUID)', 'schema': {'type': 'string'}}, {'name': 'subscribedOnly', 'in': 'query', 'description': 'true to return only bridges you are subscribed to', 'schema': {'type': 'string'}}, {'name': 'live', 'in': 'query', 'description': 'true for only bridges with live updates on, false for only those with them off; a bridge type without the setting counts as on', 'schema': {'type': 'string'}}, {'name': 'pageNumber', 'in': 'query', 'description': 'Page number, 1-based. Minimum 1.', 'schema': {'type': 'integer', 'default': '1'}}, {'name': 'pageSize', 'in': 'query', 'description': 'Page size. Must be > 0 and <= 100. Prefer <= 20.', 'schema': {'type': 'integer', 'default': '10'}}, {'name': 'filterType', 'in': 'query', 'description': 'Bridge type(s) to include. Without it the list holds RFP, Meeting, Purchase, Buyer, Contact, Signal, Conference, JobChange, VendorPresence bridges; name TopBuyer, ProductCompetitorPresence or CompanionPresence to list those', 'schema': {'type': 'array', 'items': {'type': 'string', 'enum': ['RFP', 'Meeting', 'Purchase', 'Buyer', 'TopBuyer', 'Contact', 'Signal', 'Conference', 'JobChange', 'VendorPresence', 'ProductCompetitorPresence', 'CompanionPresence']}}, 'style': 'form', 'explode': False}, {'name': 'statuses', 'in': 'query', 'description': 'Bridge lifecycle status(es) to include: Open (live), Initializing and Matching (still building), Draft, Failed, Deleting', 'schema': {'type': 'array', 'items': {'type': 'string', 'enum': ['Initializing', 'Matching', 'Draft', 'Open', 'Failed', 'Deleting']}}, 'style': 'form', 'explode': False}, {'name': 'createdByUserId', 'in': 'query', 'description': 'Only bridges owned by these user id(s)', 'schema': {'type': 'array', 'items': {'type': 'string'}}, 'style': 'form', 'explode': False}, {'name': 'userIdsHaveAccessTo', 'in': 'query', 'description': 'Only bridges these user id(s) can see — how you find what a teammate has access to', 'schema': {'type': 'array', 'items': {'type': 'string'}}, 'style': 'form', 'explode': False}, {'name': 'buyerListId', 'in': 'query', 'description': 'Only bridges whose buyer scope is one of these saved buyer lists', 'schema': {'type': 'array', 'items': {'type': 'string', 'format': 'uuid'}}, 'style': 'form', 'explode': False}], 'body': []}, 'get_bridge': {'method': 'GET', 'path': '/api/external/bridge/{bridgeId}', 'parameters': [{'name': 'bridgeId', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}], 'body': []}, 'list_bridge_rows': {'method': 'PUT', 'path': '/api/external/bridge/{bridgeId}/row', 'parameters': [{'name': 'bridgeId', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}, {'name': 'pageNumber', 'in': 'query', 'description': 'Page number, 1-based. Minimum 1.', 'schema': {'type': 'integer', 'default': '1'}}, {'name': 'pageSize', 'in': 'query', 'description': 'Page size. Must be > 0 and <= 100. Prefer <= 20.', 'schema': {'type': 'integer', 'default': '10'}}], 'body': ['filters', 'sorts', 'query', 'buyerScope', 'columnIds', 'archived', 'includeBasis']}, 'set_bridge_row_status': {'method': 'PATCH', 'path': '/api/external/bridge/{bridgeId}/row/{rowId}/status', 'parameters': [{'name': 'bridgeId', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}, {'name': 'rowId', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}], 'body': ['newStatus']}, 'get_bridge_column_metadata': {'method': 'GET', 'path': '/api/external/bridge/{bridgeId}/column/metadata', 'parameters': [{'name': 'bridgeId', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}], 'body': []}, 'list_recent_buyer_signals': {'method': 'GET', 'path': '/api/external/feed/all/buyer-signals', 'parameters': [{'name': 'triggerIds', 'in': 'query', 'description': 'Limit results to signals from these bridge ids.', 'schema': {'type': 'array', 'items': {'type': 'string', 'format': 'uuid'}}, 'style': 'form', 'explode': False}, {'name': 'query', 'in': 'query', 'description': 'Free-text search over signal name and column values', 'schema': {'type': 'string'}}, {'name': 'sort', 'in': 'query', 'description': 'Sort field. Date = by signal date, Hotness = by hotness score. Always descending. Date is the default.', 'schema': {'type': 'string', 'default': 'Date', 'enum': ['Date', 'Hotness']}}, {'name': 'pageNumber', 'in': 'query', 'description': 'Page number (1-based)', 'schema': {'type': 'integer', 'default': '1'}}, {'name': 'pageSize', 'in': 'query', 'description': 'Page size', 'schema': {'type': 'integer', 'default': '10'}}, {'name': 'buyerId', 'in': 'query', 'description': 'UUID of the buyer whose signals to return.', 'required': True, 'schema': {'type': 'string', 'format': 'uuid'}}, {'name': 'filterType', 'in': 'query', 'description': 'Filter by bridge filter type (repeatable).', 'schema': {'type': 'array', 'items': {'type': 'string', 'enum': ['RFP', 'Meeting', 'Purchase', 'Buyer', 'TopBuyer', 'Contact', 'Signal', 'Conference', 'JobChange', 'VendorPresence', 'ProductCompetitorPresence', 'CompanionPresence']}}, 'style': 'form', 'explode': False}, {'name': 'status', 'in': 'query', 'description': 'Filter by row status. Defaults to New when omitted.', 'schema': {'type': 'array', 'items': {'type': 'string', 'enum': ['New', 'Actioned', 'Saved', 'Attending', 'Sponsoring', 'NotInterested']}}, 'style': 'form', 'explode': False}, {'name': 'relativeDatePeriodFrom', 'in': 'query', 'description': 'Lower bound on the signal date as a relative period.', 'schema': {'type': 'string', 'default': 'LastOneMonths', 'enum': ['LastOneDay', 'LastSevenDays', 'LastThirtyDays', 'LastSixtyDays', 'LastOneMonths', 'LastTwoMonths', 'LastThreeMonths', 'LastSixMonths', 'LastNineMonths', 'LastYear', 'LastTwoYears']}}], 'body': []}, 'list_top_recent_signals': {'method': 'GET', 'path': '/api/external/feed/all/top-signals', 'parameters': [{'name': 'triggerIds', 'in': 'query', 'description': 'Limit results to signals from these bridge ids.', 'schema': {'type': 'array', 'items': {'type': 'string', 'format': 'uuid'}}, 'style': 'form', 'explode': False}, {'name': 'query', 'in': 'query', 'description': 'Free-text search over signal name and column values', 'schema': {'type': 'string'}}, {'name': 'sort', 'in': 'query', 'description': 'Sort field. Hotness = by hotness score, Date = by signal date. Always descending. Hotness is the default.', 'schema': {'type': 'string', 'default': 'Hotness', 'enum': ['Date', 'Hotness']}}, {'name': 'pageNumber', 'in': 'query', 'description': 'Page number (1-based)', 'schema': {'type': 'integer', 'default': '1'}}, {'name': 'pageSize', 'in': 'query', 'description': 'Page size', 'schema': {'type': 'integer', 'default': '10'}}, {'name': 'filterType', 'in': 'query', 'description': 'Filter by bridge filter type (repeatable).', 'schema': {'type': 'array', 'items': {'type': 'string', 'enum': ['RFP', 'Meeting', 'Purchase', 'Buyer', 'TopBuyer', 'Contact', 'Signal', 'Conference', 'JobChange', 'VendorPresence', 'ProductCompetitorPresence', 'CompanionPresence']}}, 'style': 'form', 'explode': False}, {'name': 'status', 'in': 'query', 'description': 'Filter by row status. Defaults to New when omitted.', 'schema': {'type': 'array', 'items': {'type': 'string', 'enum': ['New', 'Actioned', 'Saved', 'Attending', 'Sponsoring', 'NotInterested']}}, 'style': 'form', 'explode': False}, {'name': 'relativeDatePeriodFrom', 'in': 'query', 'description': 'Lower bound on the signal date as a relative period.', 'schema': {'type': 'string', 'default': 'LastSevenDays', 'enum': ['LastOneDay', 'LastSevenDays', 'LastThirtyDays', 'LastSixtyDays', 'LastOneMonths', 'LastTwoMonths', 'LastThreeMonths', 'LastSixMonths', 'LastNineMonths', 'LastYear', 'LastTwoYears']}}], 'body': []}, 'get_buyer_summary': {'method': 'GET', 'path': '/api/external/buyer/{buyerId}/summary', 'parameters': [{'name': 'buyerId', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}], 'body': []}, 'get_buyer_summary_v2': {'method': 'GET', 'path': '/api/external/buyer/{buyerId}/summary-v2', 'parameters': [{'name': 'buyerId', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}], 'body': []}}

class StarbridgeNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-starbridge"
    connection_evidence = ConnectionEvidence(operation="list_bridges", noun="bridges")

    @classmethod
    def get_config_model(cls):
        return StarbridgeFullConfig

    async def _request(self, method, path, *, params=None, body=None):
        if not self.config.credentials:
            raise ValueError("Connect a Starbridge API token")
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, params=params,
                json=body, headers={"Authorization": "Bearer " + self.config.credentials.api_token, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            # Never reflect request headers, tokens, or arbitrary error bodies.
            raise ValueError(f"Starbridge request failed (HTTP {response.status_code})")
        return response.json() if response.content else None

    async def execute(self, inputs):
        op = self.config.config
        if op.operation == "on_new_or_updated_row":
            rows = []
            for page in range(1, 21):
                data = await self._request("PUT", "/api/external/bridge/" + quote(str(op.bridgeId), safe="") + "/row",
                    params={"pageNumber": page, "pageSize": 100},
                    body={"sorts": [{"column": "rowUpdatedAt", "direction": "DESC"}]})
                batch = data["result"]
                if not isinstance(batch, list):
                    raise ValueError("Starbridge returned invalid bridge rows")
                for row in batch:
                    if not row.get("rowId") or not row.get("updatedAt") or row.get("bridgeId") != str(op.bridgeId):
                        raise ValueError("Starbridge returned a row without identity, version or matching bridge")
                rows.extend(batch)
                if not batch or page >= data["totalPages"]:
                    break
            else:
                raise ValueError("Bridge exceeds 2,000 rows; choose a smaller bridge")
            fresh = await self._filter_unseen(rows, lambda row: row["rowId"] + ":" + row["updatedAt"])
            output = {"rows": fresh, "count": len(fresh)}
        else:
            spec = OPERATIONS[op.operation]
            values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
            path = spec["path"]
            params = []
            for param in spec["parameters"]:
                key = param["name"]
                if key not in values:
                    continue
                value = values[key]
                if param["in"] == "path":
                    path = path.replace("{" + key + "}", quote(str(value), safe=""))
                elif isinstance(value, list):
                    if param.get("explode", True):
                        params.extend((key, v) for v in value)
                    else:
                        params.append((key, ",".join(str(v) for v in value)))
                else:
                    params.append((key, str(value).lower() if isinstance(value, bool) else value))
            body = {key: values[key] for key in spec["body"] if key in values} if spec["body"] else None
            output = {"data": await self._request(spec["method"], path, params=params, body=body)}
        await self.emit(output)
        return output

    @classmethod
    def resolve_agent_event(cls, output):
        rows = output.get("rows")
        if not rows:
            return None
        lines = [f"- {r.get('name') or 'Bridge row'}: {r.get('status')} in bridge {r['bridgeId']} "
                 f"(row {r['rowId']}, buyer {r.get('buyerId') or 'unspecified'}, updated {r['updatedAt']}) "
                 f"{r.get('url') or ''}; columns: {r.get('columns', {})}" for r in rows[:10]]
        return {"text": f"Starbridge: {len(rows)} new or updated rows\n" + "\n".join(lines), "conversation_key": None}
