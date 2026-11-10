"""SimplyRETS MLS reads and a scheduled new/updated listing trigger.

Contract: https://docs.simplyrets.com/api/simplyrets-openapi.yaml (1.0.0).
The provider publishes read/OPTIONS endpoints only, authenticated with an API
key and secret via HTTP Basic. Requests stay on api.simplyrets.com.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit, parse_qs

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.simplyrets.com"
CREDENTIAL_TYPE = "simplyrets_api_key"


class SimplyRETSCredential(BaseModel):
    model_config = ConfigDict(title="SimplyRETS API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://simplyrets.com/account#/apps",
            "x-credential-instructions": "Copy your API key and API secret from your SimplyRETS app. NoClick sends them as the Basic username and password over HTTPS to api.simplyrets.com. Your MLS feed determines which listings and endpoints are available.",
        })
    credential_type: Literal["simplyrets_api_key"] = Field("simplyrets_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=4096, title="API Secret", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "api_secret")
    @classmethod
    def basic_component(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value) or ":" in value:
            raise ValueError("Paste the API key or secret without a Basic header or colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SimplyRETSListPropertiesConfig(_Input):
    operation: Literal['list_properties'] = Field('list_properties', json_schema_extra={"ui:hidden": True, "x-display-name": 'Search Listings', "x-is-trigger": False})
    q: list[str] | None = Field(None, description='A textual keyword search. This parameter will search  the following\nfields, when available:\n\n  - listingId (MLS #)\n  - street number\n  - street name\n  - unit number\n  - city\n  - postal code\n  - subdivision name\n  - mls area (major)\n\nThe `q` parameter can be specified multiple times in a\nquery. For example, `q=Houston&q=mlsid_12345`.')
    status: list[Literal['Active', 'Pending', 'Closed', 'ActiveUnderContract', 'Hold', 'Withdrawn', 'Expired', 'Delete', 'Incomplete', 'ComingSoon']] | None = Field(None, description="Request listings by a specific status. This parameter defaults to active and you can specify multiple statuses in a single query.\nListing statuses depend on your RETS vendor's field availability. Below is a brief description of each status with possible synonyms which may map to your RETS vendor-specific statuses.\n- **Active**: Active Listing which is still on the market\n- **ActiveUnderContract**: An offer has been accepted but the listing is still on market. Synonyms: Accepting Backup Offers, Backup Offer, Active With Accepted. Synonyms: Offer, Backup, Contingent\n- **Pending**: An offer has been accepted and the listing is no longer on market. Synonyms: Offer Accepted, Under Contract\n- **ComingSoon**: This is a listing that has not yet been on market but will be on market soon.\n- **Closed**: The purchase agreement has been fulfilled or the lease agreement has been executed. Synonyms: Sold, Leased, Rented, Closed Sale")
    type: list[Literal['residential', 'rental', 'mobilehome', 'condominium', 'multifamily', 'commercial', 'commerciallease', 'land', 'farm']] | None = Field(None, description='Request listings by a specific property type. This\ndefaults to Residential and Rental. You can specify\nmultiple property types in a single query.')
    subtype: list[Literal['apartment', 'boatslip', 'singlefamilyresidence', 'deededparking', 'cabin', 'condominium', 'duplex', 'manufacturedhome', 'ownyourown', 'quadruplex', 'stockcooperative', 'townhouse', 'timeshare', 'triplex', 'manufacturedonland', 'farmandranch', 'agriculture', 'business', 'hotelmotel', 'industrial', 'mixeduse', 'officespace', 'retail', 'unimprovedland', 'warehouse']] | None = Field(None, description='Request listings by a specific property sub type.\n\n*NOTE* not all sub type filters are available for all vendors.')
    subTypeText: list[str] | None = Field(None, description='Filter listings by `.property.subTypeText`. The `subTypeText`\nis the original MLS SubType value.  This parameter can be used\nmultiple times.\n\nPlease refer to your MLS for an exact list of possible values.')
    agent: list[str] | None = Field(None, description='Filter the listings returned by the `listAgent` id.  Note, the\nAgent ID is provided by your RETS vendor or MLS.\n\nThe co-listing agent is not included in this query parameter.')
    coListAgent: list[str] | None = Field(None, description='Filter the listings returned by the CoListAgent (`.coAgent.id`) field.\nNote, the CoListAgent ID is provided by the MLS.\n\nThe primary ListAgent is not included in this query parameter.')
    salesAgent: list[str] | None = Field(None, description="Filter the listings returned by the `sales.agent` id.  Note, the\nAgent ID is provided by your RETS vendor or MLS.\nThe co-sales or co-buyer's agent is not included in this query parameter.")
    brokers: list[str] | None = Field(None, description='Filter the listings returned by brokerage with a Broker\nID. For some MLS areas, this is the ListOfficeId (Listing\nOffice ID).  You can specific multiple broker\nparameters. Note, this query parameter is only available\nif a Broker ID is provided by your RETS vendor or MLS.')
    specialListingConditions: list[str] | None = Field(None, description='Filter the listings by special listing conditions like REO,\nShort Sale, Auction, etc.\n\nNote: The available `specialListingConditions` values are\ndependent on the data provided by your MLS.')
    ownership: list[str] | None = Field(None, description='Filter listings by the `ownership` field.\n\nNote: The possible values for this field varies. Consult your\nMLS for a list of available `ownership` values.')
    minprice: int | None = Field(None, description='Filter listings by a minimum price.')
    maxprice: int | None = Field(None, description='Filter listings by a maximum price')
    minarea: int | None = Field(None, description='Filter listings by a minimum area size in Sq Ft.')
    maxarea: int | None = Field(None, description='Filter listings by a maximum area size in Sq Ft.')
    minbaths: int | None = Field(None, description='Filter listings by a minimum number of bathrooms.')
    maxbaths: int | None = Field(None, description='Filter listings by a maximum number of bathrooms.')
    minbeds: int | None = Field(None, description='Filter listings by a minimum number of bedrooms.')
    maxbeds: int | None = Field(None, description='Filter listings by a maximum number of bedrooms.')
    maxdom: int | None = Field(None, description='Filter listings by a maximum number of days on market.  _Note\nthat your RETS vendor or MLS must provide Days on Market data._')
    minlistdate: str | None = Field(None, description='Query listings with a `.listDate` _after_ (or equal to) this value.\n\n**Note:** By default this is parsed and compared as UTC unless\na timezone is specified in the parameter.')
    maxlistdate: str | None = Field(None, description='Query listings with a `.listDate` _before_ (or equal to) this value.\n\n**Note:** By default this is parsed and compared as UTC unless\na timezone is specified in the parameter.')
    modified: str | None = Field(None, description='Return listings whose MLS modification timestamp is on or after\n(greater than or equal to) this value. Use this filter to retrieve\nlistings updated since a given date or time.\n\nAccepted values include `YYYY-MM-DD`, `MM/DD/YYYY`, and timestamps\nusing either a `T` or a space between the date and time, with\noptional fractional seconds. A timestamp can include `Z`, a numeric\ntimezone offset (such as `-07:00`), or a timezone abbreviation\n(such as `UTC` or `CST`). Examples: `2026-10-01`,\n`2026-10-01T13:27:01.42Z`, and `2026-10-01 13:27:01`.\n\nValues without a timezone are interpreted as UTC. A date without\na time is interpreted as midnight. URL-encode spaces and any `+`\nin timezone offsets when sending this parameter.\n\nInvalid values are ignored, so no modification-time filter is\napplied. This filter is also ignored for feeds that do not provide\nMLS modification timestamps. Other search filters still apply.')
    minyear: int | None = Field(None, description='Filter listings by a setting a minimum year built.')
    maxyear: int | None = Field(None, description='Filter listings by a setting a maximum year built.')
    minacres: int | None = Field(None, description='Filter listings by a setting a minimum acreage.')
    maxacres: int | None = Field(None, description='Filter listings by a setting a maximum acreage.')
    minGarageSpaces: int | None = Field(None, description='Filter listings by a minimum number of garage spaces.')
    maxGarageSpaces: int | None = Field(None, description='Filter listings by a maximum number of garage spaces.')
    limit: int | None = Field(None, description='Set the number of listings to return in the response.\nThis defaults to 20 listings, and can be a maximum of 500.\nTo paginate through to the next page of listings, take a\nlook at the `offset` parameter, or the Link in the HTTP\nHeader.', ge=1, le=500)
    offset: int | None = Field(None, description='Increase the offset parameter by the limit to go to the\nnext "page" of listings. Also take a look at the Link HTTP\nHeader for pre-built pagination.\n\n*NOTE:* Use the `lastId` field to paginate response\n\n*NOTE:* If you\'re offset is too high, you will receive an\n`HTTP 400 offset too high` error message.', ge=0, le=10000)
    lastId: int | None = Field(None, description='Used as a cursor for pagination. When using `lastId`, the `sort` parameter\nwill not work.', ge=0)
    vendor: str | None = Field(None, description="Used to specify the RETS vendor to search from. This\nparameter is required on multi-MLS apps. You can query one\nvendor at a time. To get your vendor id's make an HTTP\nOPTIONS request to https://api.simplyrets.com.\n\n`curl -XOPTIONS https://api.simplyrets.com/properties` Required on multi-MLS accounts; copy a vendor ID from Get Account Metadata.", json_schema_extra={"x-dynamic-options": {"field_name": "vendor", "allow_custom": True}})
    postalCodes: list[str] | None = Field(None, description='Filter the listings returned by postal codes / zip\ncode. You can specify multiple.')
    features: list[str] | None = Field(None, description='Filter the listings by specific **interior features**.  You can use the parameter multiple times to filter by multiple features. For example, to search for `Wet Bar` and `High Ceiling`:\n``` https://simplyrets.com/services?features=Wet%20Bar&features=High%20Ceiling ```\nThe list of `features` provided by your RETS vendor or MLS can be seen by sending an `OPTIONS` request to the `/properties` endpoint:\n``` curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/properties ```')
    exteriorFeatures: list[str] | None = Field(None, description='Filter the listings by specific **exterior features**.  You can use the parameter multiple times to filter by multiple features. For example, to search for `Proch` and `Fully Fenced`:\n``` https://simplyrets.com/services?exteriorFeatures=Porch&exteriorFeatures=Fully+Fenced ```')
    pool: list[str] | None = Field(None, description='Filter listings on pool features (`.property.pool`). There are multiple ways to use this parameter:\n- `pool=true`: Return listings where `.property.pool` is NOT\n  `false` or `null`.\n- `pool=false`: Return listings where `.property.pool` IS\n  `false` or `null`.\n- `pool=QUERY`: Return listings with a matching\n  `.property.pool` value. Example: `?pool=Private`.\n\nIf this parameter is used multiple times in a single query, return listings that match any of the provided values.')
    water: list[str] | None = Field(None, description='Filter listings on WaterBodyName (`.property.water`). There are multiple ways to use this parameter:\n- `water=true`: Return listings where `.property.water` is NOT\n  `false` or `null`.\n- `water=false`: Return listings where `.property.water` is\n  `false` or `null`.\n- `water=QUERY`: Return listings with a matching\n  `.property.water` value.\n\nIf this parameter is used multiple times in a single query, return listings that match any of the provided values.')
    neighborhoods: list[str] | None = Field(None, description='Filter the listings returned by specific neighborhoods and\nsubdivisions. You can specify multiple `neighborhoods` by\nusing the query parameter multiple times.\n\nThe `neighborhoods` query parameter is case-insensitive.\n\nThe list of `neighborhoods` provided by your RETS vendor or\nMLS can be seen by sending an `OPTIONS` request to the\n`/properties` endpoint:\n\n`curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/properties`')
    cities: list[str] | None = Field(None, description='Filter the listings returned by specific cities. You can\nspecify multiple `cities` query parameters.\n\nThe `cities` query parameter is case-insensitive.\n\nThe list of `cities` provided by your RETS vendor or MLS can\nbe seen by sending an `OPTIONS` request to the `/properties`\nendpoint:\n\n`curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/openhouses`')
    state: list[str] | None = Field(None, description='Filter the listings by state or province. You can specify multiple `state` parameters and the parameter is case insensitive.')
    counties: list[str] | None = Field(None, description='Filter the listings returned by specific counties. You can\nspecify multiple `counties` parameters.\n\nThe `counties` query parameter is case-insensitive.\n\nThe list of `counties` provided by your RETS vendor or MLS\ncan be seen by sending an `OPTIONS` request to the\n`/properties` endpoint:\n\n`curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/openhouses`')
    points: list[str] | None = Field(None, description='Return listings that are within a set of latitude\nlongitude coordinates. For example;\n```\n29.723837,-95.69778\n29.938275,-95.69778\n29.938275,-95.32974\n29.723837,-95.32974\n```\n\nNote that some RETS vendors do not provide latitude and\nlongitude with their listings, which is required for this\nparameter to work. In these cases, SimplyRETS offers a\n[Geocoding Addon](https://simplyrets.com/services#geocoding).\n\nCheck out our\n[blog post](https://simplyrets.com/blog/interactive-map-search.html)\non using the `points` parameter to build a map-based app\nin javascript.')
    idx: list[Literal['null', 'listing', 'address', 'ignore']] | None = Field(None, description="Specify the IDX display requirements for the listings in the response. The `idx` parameter checks if the `internetAddressDisplay` and `internetEntireListingDisplay` for each listing are true (or `null`) or false based on this setting.\n##### **`idx=null`** (default)\n  - `internetAddressDisplay` must be true\n  - `internetEntireListingDisplay` must be true\n##### **`idx=listing`**\n  - `internetAddressDisplay` is ignored\n  - `internetEntireListingDisplay` must be true\n##### **`idx=address`**\n  - `internetAddressDisplay` must be true\n  - `internetEntireListingDisplay` is ignored\n##### **`idx=ignore`**\n  - `internetAddressDisplay` is ignored\n  - `internetEntireListingDisplay` is ignored\n\nLearn more about SimplyRETS's [IDX compliance features here](/topics/fields-and-features-for-idx-compliance) and please check with your MLS or data feed provider on the rules and requirements for displaying restricted listings.")
    include: list[Literal['compliance', 'rooms']] | None = Field(None, description="Enable additional fields in the API response. The available\n`include` values are:\n\n- `include=compliance`: Adds `.compliance` data to the API\n  response.  Compliance data will contain extra fields that\n  may be required in your IDX display. Please check your MLS's\n  or association's specific IDX display requirements.\n\n- `include=rooms`: Adds `.rooms` data to the API response.\n  Rooms data contains additional information about individual\n  rooms on the property (e.g. bedrooms, living room). Not all\n  feeds support this extended data. Enabled upon request.")
    sort: Literal['listprice', '-listprice', 'listdate', '-listdate', 'closedate', '-closedate', 'beds', '-beds', 'baths', '-baths'] | None = Field(None, description='Sort the response by a specific field. Values starting\nwith a minus (-) denote descending order, while the others\nare ascending.')
    count: bool | None = Field(None, description='When set to `true`, The `X-Total-Count` header will be\nreturned, showing the total number of items matching the query.\n\nCounting the listings can contribute to slower API calls\ndue to the extra queries that need to be run to get an\nexact count.\n\nEnabling count may decrease API response/page load times,\nespecially on larger datasets.')

class SimplyRETSGetPropertyConfig(_Input):
    operation: Literal['get_property'] = Field('get_property', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Listing', "x-is-trigger": False})
    mlsId: int = Field(..., description='The `mlsId` field is a unique identifier which is specific\nto the SimplyRETS API only.  This field is different from\nthe `listingId` field (which is the public number given to\na listing by the RETS vendor or MLS and is not used here).', ge=1)
    vendor: str | None = Field(None, description='Specify the RETS vendor to search. This parameter is\n**required on multi-mls accounts**. You can query one\nvendor at a time. Your vendor IDs can be found in your\naccount panel, or you can make an HTTP OPTIONS request to\nhttps://api.simplyrets.com.\n\n```\ncurl -XOPTIONS https://api.simplyrets.com/properties\n``` Required on multi-MLS accounts; copy a vendor ID from Get Account Metadata.', json_schema_extra={"x-dynamic-options": {"field_name": "vendor", "allow_custom": True}})

class SimplyRETSListOpenhousesConfig(_Input):
    operation: Literal['list_openhouses'] = Field('list_openhouses', json_schema_extra={"ui:hidden": True, "x-display-name": 'Search Open Houses', "x-is-trigger": False})
    type: Literal['residential', 'rental', 'mobilehome', 'condominium', 'multifamily', 'commercial', 'commerciallease', 'land', 'farm'] | None = Field(None, description="Request open houses by it's listing's property type. This defaults to\nResidential, and you can only specify one type in a single query.")
    listingId: str | None = Field(None, description='Request open houses for a specific `listingId`.')
    cities: list[str] | None = Field(None, description='Filter the open houses returned by a list of valid cities.\n\nThe `cities` query parameter is case-insensitive.\n\nThe list of `cities` provided by your RETS vendor or MLS can\nbe seen by sending an `OPTIONS` request to the `/properties`\nendpoint:\n\n`curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/openhouses`')
    vendor: str | None = Field(None, description='Specify the RETS vendor to search. This parameter is\n**required on multi-mls accounts**. You can query one\nvendor at a time. Your vendor IDs can be found in your\naccount panel, or you can make an HTTP OPTIONS request to\nhttps://api.simplyrets.com.\n\n```\ncurl -XOPTIONS https://api.simplyrets.com/properties\n``` Required on multi-MLS accounts; copy a vendor ID from Get Account Metadata.', json_schema_extra={"x-dynamic-options": {"field_name": "vendor", "allow_custom": True}})
    brokers: list[str] | None = Field(None, description='Filter open houses by brokerage with a Broker ID.  You can specific\nmultiple broker parameters. Note, the Broker ID is provided by your\nRETS vendor or MLS.')
    agent: str | None = Field(None, description='Filter the open houses returned by an agent ID.  Note, the\nAgent ID is provided by your RETS vendor or MLS.')
    minprice: int | None = Field(None, description="Filter open houses by the minimum price of it's corresponding listing.")
    maxprice: int | None = Field(None, description="Filter open houses by the maximum price of it's corresponding listing.")
    startdate: str | None = Field(None, description='Scheduled date and time of the open house showing')
    lastId: int | None = Field(None, description='Used as a cursor for pagination.', ge=0)
    minarea: int | None = Field(None, description="Filter open houses by the minimum living area of it's corresponding\nlisting.")
    minbeds: int | None = Field(None, description="Filter open houses by the minimum number bedrooms of it's\ncorresponding listing.")
    minbaths: int | None = Field(None, description="Filter open houses by the minimum number of bathrooms of it's\ncorresponding listing.")
    offset: int | None = Field(None, description='Increase the offset parameter by the limit to go to the\nnext "page" of listings. Also take a look at the Link HTTP\nHeader for pre-built pagination.\n\n*NOTE:* Use the `lastId` parameter for pagination.', ge=0, le=10000)
    limit: int | None = Field(None, description='The number of records returned in the API response. This\ncan be set to any number between 1 and 500.\n\nThe default limit is 12 on the `/openhouses` endpoint.', ge=1, le=500)
    sort: Literal['listprice', '-listprice', 'listdate', '-listdate', 'beds', '-beds', 'baths', '-baths'] | None = Field(None, description='Sort the response by a specific field. Values starting\nwith a minus (-) denote descending order, while the others\nare ascending.')
    include: list[str] | None = Field(None, description="Include a extra fields which are not in the default response body. Available values:\n- 'rooms': include parameter will include\n   any additional rooms as a list.\n\nNote that your RETS vendor or MLS must provide these fields in their RETS data for them to be available in the API response. In the future, fields which require an 'include' may become available by default.")

class SimplyRETSGetOpenhouseConfig(_Input):
    operation: Literal['get_openhouse'] = Field('get_openhouse', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Open House', "x-is-trigger": False})
    openHouseKey: int = Field(..., description='A unique OpenHouse identification key', ge=1)
    vendor: str | None = Field(None, description='Specify the RETS vendor to search. This parameter is\n**required on multi-mls accounts**. You can query one\nvendor at a time. Your vendor IDs can be found in your\naccount panel, or you can make an HTTP OPTIONS request to\nhttps://api.simplyrets.com.\n\n```\ncurl -XOPTIONS https://api.simplyrets.com/properties\n``` Required on multi-MLS accounts; copy a vendor ID from Get Account Metadata.', json_schema_extra={"x-dynamic-options": {"field_name": "vendor", "allow_custom": True}})
    include: list[str] | None = Field(None, description="Include a extra fields which are not in the default\nresponse body. Available values:\n\n- 'rooms': include parameter will include\n   any additional rooms as a list.\n\nNote that your RETS vendor or MLS must provide these\nfields in their RETS data for them to be available in the\nAPI response. In the future, fields which require an\n'include' may become available by default.")

class SimplyRETSListPropertyKeysConfig(_Input):
    operation: Literal['list_property_keys'] = Field('list_property_keys', json_schema_extra={"ui:hidden": True, "x-display-name": 'Search Listing Keys', "x-is-trigger": False})
    q: list[str] | None = Field(None, description='A textual keyword search. This parameter will search  the following\nfields, when available:\n\n  - listingId (MLS #)\n  - street number\n  - street name\n  - unit number\n  - city\n  - postal code\n  - subdivision name\n  - mls area (major)\n\nThe `q` parameter can be specified multiple times in a\nquery. For example, `q=Houston&q=mlsid_12345`.')
    status: list[Literal['Active', 'Pending', 'Closed', 'ActiveUnderContract', 'Hold', 'Withdrawn', 'Expired', 'Delete', 'Incomplete', 'ComingSoon']] | None = Field(None, description="Request listings by a specific status. This parameter defaults to active and you can specify multiple statuses in a single query.\nListing statuses depend on your RETS vendor's field availability. Below is a brief description of each status with possible synonyms which may map to your RETS vendor-specific statuses.\n- **Active**: Active Listing which is still on the market\n- **ActiveUnderContract**: An offer has been accepted but the listing is still on market. Synonyms: Accepting Backup Offers, Backup Offer, Active With Accepted. Synonyms: Offer, Backup, Contingent\n- **Pending**: An offer has been accepted and the listing is no longer on market. Synonyms: Offer Accepted, Under Contract\n- **ComingSoon**: This is a listing that has not yet been on market but will be on market soon.\n- **Closed**: The purchase agreement has been fulfilled or the lease agreement has been executed. Synonyms: Sold, Leased, Rented, Closed Sale")
    type: list[Literal['residential', 'rental', 'mobilehome', 'condominium', 'multifamily', 'commercial', 'commerciallease', 'land', 'farm']] | None = Field(None, description='Request listings by a specific property type. This\ndefaults to Residential and Rental. You can specify\nmultiple property types in a single query.')
    subtype: list[Literal['apartment', 'boatslip', 'singlefamilyresidence', 'deededparking', 'cabin', 'condominium', 'duplex', 'manufacturedhome', 'ownyourown', 'quadruplex', 'stockcooperative', 'townhouse', 'timeshare', 'triplex', 'manufacturedonland', 'farmandranch', 'agriculture', 'business', 'hotelmotel', 'industrial', 'mixeduse', 'officespace', 'retail', 'unimprovedland', 'warehouse']] | None = Field(None, description='Request listings by a specific property sub type.\n\n*NOTE* not all sub type filters are available for all vendors.')
    subTypeText: list[str] | None = Field(None, description='Filter listings by `.property.subTypeText`. The `subTypeText`\nis the original MLS SubType value.  This parameter can be used\nmultiple times.\n\nPlease refer to your MLS for an exact list of possible values.')
    agent: list[str] | None = Field(None, description='Filter the listings returned by the `listAgent` id.  Note, the\nAgent ID is provided by your RETS vendor or MLS.\n\nThe co-listing agent is not included in this query parameter.')
    coListAgent: list[str] | None = Field(None, description='Filter the listings returned by the CoListAgent (`.coAgent.id`) field.\nNote, the CoListAgent ID is provided by the MLS.\n\nThe primary ListAgent is not included in this query parameter.')
    salesAgent: list[str] | None = Field(None, description="Filter the listings returned by the `sales.agent` id.  Note, the\nAgent ID is provided by your RETS vendor or MLS.\nThe co-sales or co-buyer's agent is not included in this query parameter.")
    brokers: list[str] | None = Field(None, description='Filter the listings returned by brokerage with a Broker\nID. For some MLS areas, this is the ListOfficeId (Listing\nOffice ID).  You can specific multiple broker\nparameters. Note, this query parameter is only available\nif a Broker ID is provided by your RETS vendor or MLS.')
    specialListingConditions: list[str] | None = Field(None, description='Filter the listings by special listing conditions like REO,\nShort Sale, Auction, etc.\n\nNote: The available `specialListingConditions` values are\ndependent on the data provided by your MLS.')
    ownership: list[str] | None = Field(None, description='Filter listings by the `ownership` field.\n\nNote: The possible values for this field varies. Consult your\nMLS for a list of available `ownership` values.')
    minprice: int | None = Field(None, description='Filter listings by a minimum price.')
    maxprice: int | None = Field(None, description='Filter listings by a maximum price')
    minarea: int | None = Field(None, description='Filter listings by a minimum area size in Sq Ft.')
    maxarea: int | None = Field(None, description='Filter listings by a maximum area size in Sq Ft.')
    minbaths: int | None = Field(None, description='Filter listings by a minimum number of bathrooms.')
    maxbaths: int | None = Field(None, description='Filter listings by a maximum number of bathrooms.')
    minbeds: int | None = Field(None, description='Filter listings by a minimum number of bedrooms.')
    maxbeds: int | None = Field(None, description='Filter listings by a maximum number of bedrooms.')
    maxdom: int | None = Field(None, description='Filter listings by a maximum number of days on market.  _Note\nthat your RETS vendor or MLS must provide Days on Market data._')
    minlistdate: str | None = Field(None, description='Query listings with a `.listDate` _after_ (or equal to) this value.\n\n**Note:** By default this is parsed and compared as UTC unless\na timezone is specified in the parameter.')
    maxlistdate: str | None = Field(None, description='Query listings with a `.listDate` _before_ (or equal to) this value.\n\n**Note:** By default this is parsed and compared as UTC unless\na timezone is specified in the parameter.')
    modified: str | None = Field(None, description='Return listings whose MLS modification timestamp is on or after\n(greater than or equal to) this value. Use this filter to retrieve\nlistings updated since a given date or time.\n\nAccepted values include `YYYY-MM-DD`, `MM/DD/YYYY`, and timestamps\nusing either a `T` or a space between the date and time, with\noptional fractional seconds. A timestamp can include `Z`, a numeric\ntimezone offset (such as `-07:00`), or a timezone abbreviation\n(such as `UTC` or `CST`). Examples: `2026-10-01`,\n`2026-10-01T13:27:01.42Z`, and `2026-10-01 13:27:01`.\n\nValues without a timezone are interpreted as UTC. A date without\na time is interpreted as midnight. URL-encode spaces and any `+`\nin timezone offsets when sending this parameter.\n\nInvalid values are ignored, so no modification-time filter is\napplied. This filter is also ignored for feeds that do not provide\nMLS modification timestamps. Other search filters still apply.')
    minyear: int | None = Field(None, description='Filter listings by a setting a minimum year built.')
    maxyear: int | None = Field(None, description='Filter listings by a setting a maximum year built.')
    minacres: int | None = Field(None, description='Filter listings by a setting a minimum acreage.')
    maxacres: int | None = Field(None, description='Filter listings by a setting a maximum acreage.')
    minGarageSpaces: int | None = Field(None, description='Filter listings by a minimum number of garage spaces.')
    maxGarageSpaces: int | None = Field(None, description='Filter listings by a maximum number of garage spaces.')
    limit: int | None = Field(None, description='Set the number of listing keys to return. Defaults to 20 and is\ncapped at 5000 when using offset pagination, or 500 when using\nthe `lastId` cursor.', ge=1, le=5000)
    offset: int | None = Field(None, description='Increase the offset parameter by the limit to go to the\nnext "page" of listings. Also take a look at the Link HTTP\nHeader for pre-built pagination.\n\n*NOTE:* Use the `lastId` field to paginate response\n\n*NOTE:* If you\'re offset is too high, you will receive an\n`HTTP 400 offset too high` error message.', ge=0, le=10000)
    lastId: int | None = Field(None, description='Used as a cursor for pagination. When using `lastId`, the `sort` parameter\nwill not work.', ge=0)
    vendor: str | None = Field(None, description="Used to specify the RETS vendor to search from. This\nparameter is required on multi-MLS apps. You can query one\nvendor at a time. To get your vendor id's make an HTTP\nOPTIONS request to https://api.simplyrets.com.\n\n`curl -XOPTIONS https://api.simplyrets.com/properties` Required on multi-MLS accounts; copy a vendor ID from Get Account Metadata.", json_schema_extra={"x-dynamic-options": {"field_name": "vendor", "allow_custom": True}})
    postalCodes: list[str] | None = Field(None, description='Filter the listings returned by postal codes / zip\ncode. You can specify multiple.')
    features: list[str] | None = Field(None, description='Filter the listings by specific **interior features**.  You can use the parameter multiple times to filter by multiple features. For example, to search for `Wet Bar` and `High Ceiling`:\n``` https://simplyrets.com/services?features=Wet%20Bar&features=High%20Ceiling ```\nThe list of `features` provided by your RETS vendor or MLS can be seen by sending an `OPTIONS` request to the `/properties` endpoint:\n``` curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/properties ```')
    exteriorFeatures: list[str] | None = Field(None, description='Filter the listings by specific **exterior features**.  You can use the parameter multiple times to filter by multiple features. For example, to search for `Proch` and `Fully Fenced`:\n``` https://simplyrets.com/services?exteriorFeatures=Porch&exteriorFeatures=Fully+Fenced ```')
    water: list[str] | None = Field(None, description='Filter listings on WaterBodyName (`.property.water`). There are multiple ways to use this parameter:\n- `water=true`: Return listings where `.property.water` is NOT\n  `false` or `null`.\n- `water=false`: Return listings where `.property.water` is\n  `false` or `null`.\n- `water=QUERY`: Return listings with a matching\n  `.property.water` value.\n\nIf this parameter is used multiple times in a single query, return listings that match any of the provided values.')
    neighborhoods: list[str] | None = Field(None, description='Filter the listings returned by specific neighborhoods and\nsubdivisions. You can specify multiple `neighborhoods` by\nusing the query parameter multiple times.\n\nThe `neighborhoods` query parameter is case-insensitive.\n\nThe list of `neighborhoods` provided by your RETS vendor or\nMLS can be seen by sending an `OPTIONS` request to the\n`/properties` endpoint:\n\n`curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/properties`')
    cities: list[str] | None = Field(None, description='Filter the listings returned by specific cities. You can\nspecify multiple `cities` query parameters.\n\nThe `cities` query parameter is case-insensitive.\n\nThe list of `cities` provided by your RETS vendor or MLS can\nbe seen by sending an `OPTIONS` request to the `/properties`\nendpoint:\n\n`curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/openhouses`')
    state: list[str] | None = Field(None, description='Filter the listings by state or province. You can specify multiple `state` parameters and the parameter is case insensitive.')
    counties: list[str] | None = Field(None, description='Filter the listings returned by specific counties. You can\nspecify multiple `counties` parameters.\n\nThe `counties` query parameter is case-insensitive.\n\nThe list of `counties` provided by your RETS vendor or MLS\ncan be seen by sending an `OPTIONS` request to the\n`/properties` endpoint:\n\n`curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/openhouses`')
    points: list[str] | None = Field(None, description='Return listings that are within a set of latitude\nlongitude coordinates. For example;\n```\n29.723837,-95.69778\n29.938275,-95.69778\n29.938275,-95.32974\n29.723837,-95.32974\n```\n\nNote that some RETS vendors do not provide latitude and\nlongitude with their listings, which is required for this\nparameter to work. In these cases, SimplyRETS offers a\n[Geocoding Addon](https://simplyrets.com/services#geocoding).\n\nCheck out our\n[blog post](https://simplyrets.com/blog/interactive-map-search.html)\non using the `points` parameter to build a map-based app\nin javascript.')
    idx: list[Literal['null', 'listing', 'address', 'ignore']] | None = Field(None, description="Specify the IDX display requirements for the listings in the response. The `idx` parameter checks if the `internetAddressDisplay` and `internetEntireListingDisplay` for each listing are true (or `null`) or false based on this setting.\n##### **`idx=null`** (default)\n  - `internetAddressDisplay` must be true\n  - `internetEntireListingDisplay` must be true\n##### **`idx=listing`**\n  - `internetAddressDisplay` is ignored\n  - `internetEntireListingDisplay` must be true\n##### **`idx=address`**\n  - `internetAddressDisplay` must be true\n  - `internetEntireListingDisplay` is ignored\n##### **`idx=ignore`**\n  - `internetAddressDisplay` is ignored\n  - `internetEntireListingDisplay` is ignored\n\nLearn more about SimplyRETS's [IDX compliance features here](/topics/fields-and-features-for-idx-compliance) and please check with your MLS or data feed provider on the rules and requirements for displaying restricted listings.")
    sort: Literal['listprice', '-listprice', 'listdate', '-listdate', 'closedate', '-closedate', 'beds', '-beds', 'baths', '-baths'] | None = Field(None, description='Sort the response by a specific field. Values starting\nwith a minus (-) denote descending order, while the others\nare ascending.')

class SimplyRETSListAgentsConfig(_Input):
    operation: Literal['list_agents'] = Field('list_agents', json_schema_extra={"ui:hidden": True, "x-display-name": 'Search Agents', "x-is-trigger": False})
    q: str | None = Field(None, description='A keyword search on the Agents API. The `q` parameter will\nsearch the `.id` and `.contact.email` fields, and return\nlistings matching the criteria. `q` can be provided multiple\ntimes.')
    name: str | None = Field(None, description='Filter agents by name. You can provide a first name, last\nname, or both.')
    state: str | None = Field(None, description='Filter agents by their `address.state` field.')

class SimplyRETSListOfficesConfig(_Input):
    operation: Literal['list_offices'] = Field('list_offices', json_schema_extra={"ui:hidden": True, "x-display-name": 'Search Offices', "x-is-trigger": False})
    q: list[str] | None = Field(None, description='Search offices by MLS office ID, main office MLS ID, email, or name.\nIDs and email use exact matches; names use case-insensitive partial\nmatches. Repeat `q` to match any of the supplied values, for example\n`?q=ABC123&q=Example`.')
    name: str | None = Field(None, description='Filter offices by a case-insensitive partial match on their name.')
    state: str | None = Field(None, description='Filter offices by a case-insensitive partial match on `address.state`.')
    count: bool | None = Field(None, description='Set to `true` to include the total number of matching offices in the\n`X-Total-Count` response header.')
    offset: int | None = Field(None, description='Number of matching offices to skip. Increase by `limit` to request\nthe next page, or follow the `Link` response header. A positive\noffset that returns no offices produces an HTTP 400 error.', ge=0, le=10000)
    limit: int | None = Field(None, description='Number of offices to return per page.', ge=1, le=500)
    vendor: str | None = Field(None, description="Used to specify the RETS vendor to search from. This\nparameter is required on multi-MLS apps. You can query one\nvendor at a time. To get your vendor id's make an HTTP\nOPTIONS request to https://api.simplyrets.com.\n\n`curl -XOPTIONS https://api.simplyrets.com/properties` Required on multi-MLS accounts; copy a vendor ID from Get Account Metadata.", json_schema_extra={"x-dynamic-options": {"field_name": "vendor", "allow_custom": True}})
    username: str | None = Field(None, description='Select the feed username when your API credentials have multiple\nusernames for the selected vendor. Required in that case; the\nusername must be associated with your API credentials.')

class SimplyRETSGetMarketAnalyticsConfig(_Input):
    operation: Literal['get_market_analytics'] = Field('get_market_analytics', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Market Analytics', "x-is-trigger": False})
    q: list[str] | None = Field(None, description='A textual keyword search. This parameter will search  the following\nfields, when available:\n\n  - listingId (MLS #)\n  - street number\n  - street name\n  - unit number\n  - city\n  - postal code\n  - subdivision name\n  - mls area (major)\n\nThe `q` parameter can be specified multiple times in a\nquery. For example, `q=Houston&q=mlsid_12345`.')
    status: list[Literal['Active', 'Pending', 'Closed', 'ActiveUnderContract', 'Hold', 'Withdrawn', 'Expired', 'Delete', 'Incomplete', 'ComingSoon']] | None = Field(None, description="Request listings by a specific status. This parameter defaults to active and you can specify multiple statuses in a single query.\nListing statuses depend on your RETS vendor's field availability. Below is a brief description of each status with possible synonyms which may map to your RETS vendor-specific statuses.\n- **Active**: Active Listing which is still on the market\n- **ActiveUnderContract**: An offer has been accepted but the listing is still on market. Synonyms: Accepting Backup Offers, Backup Offer, Active With Accepted. Synonyms: Offer, Backup, Contingent\n- **Pending**: An offer has been accepted and the listing is no longer on market. Synonyms: Offer Accepted, Under Contract\n- **ComingSoon**: This is a listing that has not yet been on market but will be on market soon.\n- **Closed**: The purchase agreement has been fulfilled or the lease agreement has been executed. Synonyms: Sold, Leased, Rented, Closed Sale")
    type: list[Literal['residential', 'rental', 'mobilehome', 'condominium', 'multifamily', 'commercial', 'commerciallease', 'land', 'farm']] | None = Field(None, description='Request listings by a specific property type. This\ndefaults to Residential and Rental. You can specify\nmultiple property types in a single query.')
    subtype: list[Literal['apartment', 'boatslip', 'singlefamilyresidence', 'deededparking', 'cabin', 'condominium', 'duplex', 'manufacturedhome', 'ownyourown', 'quadruplex', 'stockcooperative', 'townhouse', 'timeshare', 'triplex', 'manufacturedonland', 'farmandranch', 'agriculture', 'business', 'hotelmotel', 'industrial', 'mixeduse', 'officespace', 'retail', 'unimprovedland', 'warehouse']] | None = Field(None, description='Request listings by a specific property sub type.\n\n*NOTE* not all sub type filters are available for all vendors.')
    agent: list[str] | None = Field(None, description='Filter the listings returned by the `listAgent` id.  Note, the\nAgent ID is provided by your RETS vendor or MLS.\n\nThe co-listing agent is not included in this query parameter.')
    salesAgent: list[str] | None = Field(None, description="Filter the listings returned by the `sales.agent` id.  Note, the\nAgent ID is provided by your RETS vendor or MLS.\nThe co-sales or co-buyer's agent is not included in this query parameter.")
    brokers: list[str] | None = Field(None, description='Filter the listings returned by brokerage with a Broker\nID. For some MLS areas, this is the ListOfficeId (Listing\nOffice ID).  You can specific multiple broker\nparameters. Note, this query parameter is only available\nif a Broker ID is provided by your RETS vendor or MLS.')
    minprice: int | None = Field(None, description='Filter listings by a minimum price.')
    maxprice: int | None = Field(None, description='Filter listings by a maximum price')
    minarea: int | None = Field(None, description='Filter listings by a minimum area size in Sq Ft.')
    maxarea: int | None = Field(None, description='Filter listings by a maximum area size in Sq Ft.')
    minbaths: int | None = Field(None, description='Filter listings by a minimum number of bathrooms.')
    maxbaths: int | None = Field(None, description='Filter listings by a maximum number of bathrooms.')
    minbeds: int | None = Field(None, description='Filter listings by a minimum number of bedrooms.')
    maxbeds: int | None = Field(None, description='Filter listings by a maximum number of bedrooms.')
    maxdom: int | None = Field(None, description='Filter listings by a maximum number of days on market.  _Note\nthat your RETS vendor or MLS must provide Days on Market data._')
    minyear: int | None = Field(None, description='Filter listings by a setting a minimum year built.')
    maxyear: int | None = Field(None, description='Filter listings by a setting a maximum year built.')
    minacres: int | None = Field(None, description='Filter listings by a setting a minimum acreage.')
    maxacres: int | None = Field(None, description='Filter listings by a setting a maximum acreage.')
    minGarageSpaces: int | None = Field(None, description='Filter listings by a minimum number of garage spaces.')
    maxGarageSpaces: int | None = Field(None, description='Filter listings by a maximum number of garage spaces.')
    limit: int | None = Field(None, description='Set the number of listings to return in the response.\nThis defaults to 20 listings, and can be a maximum of 500.\nTo paginate through to the next page of listings, take a\nlook at the `offset` parameter, or the Link in the HTTP\nHeader.', ge=1, le=500)
    offset: int | None = Field(None, description='Increase the offset parameter by the limit to go to the\nnext "page" of listings. Also take a look at the Link HTTP\nHeader for pre-built pagination.\n\n*NOTE:* Use the `lastId` field to paginate response\n\n*NOTE:* If you\'re offset is too high, you will receive an\n`HTTP 400 offset too high` error message.', ge=0, le=10000)
    lastId: int | None = Field(None, description='Used as a cursor for pagination. When using `lastId`, the `sort` parameter\nwill not work.', ge=0)
    vendor: str | None = Field(None, description="Used to specify the RETS vendor to search from. This\nparameter is required on multi-MLS apps. You can query one\nvendor at a time. To get your vendor id's make an HTTP\nOPTIONS request to https://api.simplyrets.com.\n\n`curl -XOPTIONS https://api.simplyrets.com/properties` Required on multi-MLS accounts; copy a vendor ID from Get Account Metadata.", json_schema_extra={"x-dynamic-options": {"field_name": "vendor", "allow_custom": True}})
    postalCodes: list[str] | None = Field(None, description='Filter the listings returned by postal codes / zip\ncode. You can specify multiple.')
    features: list[str] | None = Field(None, description='Filter the listings by specific **interior features**.  You can use the parameter multiple times to filter by multiple features. For example, to search for `Wet Bar` and `High Ceiling`:\n``` https://simplyrets.com/services?features=Wet%20Bar&features=High%20Ceiling ```\nThe list of `features` provided by your RETS vendor or MLS can be seen by sending an `OPTIONS` request to the `/properties` endpoint:\n``` curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/properties ```')
    exteriorFeatures: list[str] | None = Field(None, description='Filter the listings by specific **exterior features**.  You can use the parameter multiple times to filter by multiple features. For example, to search for `Proch` and `Fully Fenced`:\n``` https://simplyrets.com/services?exteriorFeatures=Porch&exteriorFeatures=Fully+Fenced ```')
    pool: list[str] | None = Field(None, description='Filter listings on pool features (`.property.pool`). There are multiple ways to use this parameter:\n- `pool=true`: Return listings where `.property.pool` is NOT\n  `false` or `null`.\n- `pool=false`: Return listings where `.property.pool` IS\n  `false` or `null`.\n- `pool=QUERY`: Return listings with a matching\n  `.property.pool` value. Example: `?pool=Private`.\n\nIf this parameter is used multiple times in a single query, return listings that match any of the provided values.')
    water: list[str] | None = Field(None, description='Filter listings on WaterBodyName (`.property.water`). There are multiple ways to use this parameter:\n- `water=true`: Return listings where `.property.water` is NOT\n  `false` or `null`.\n- `water=false`: Return listings where `.property.water` is\n  `false` or `null`.\n- `water=QUERY`: Return listings with a matching\n  `.property.water` value.\n\nIf this parameter is used multiple times in a single query, return listings that match any of the provided values.')
    neighborhoods: list[str] | None = Field(None, description='Filter the listings returned by specific neighborhoods and\nsubdivisions. You can specify multiple `neighborhoods` by\nusing the query parameter multiple times.\n\nThe `neighborhoods` query parameter is case-insensitive.\n\nThe list of `neighborhoods` provided by your RETS vendor or\nMLS can be seen by sending an `OPTIONS` request to the\n`/properties` endpoint:\n\n`curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/properties`')
    cities: list[str] | None = Field(None, description='Filter the listings returned by specific cities. You can\nspecify multiple `cities` query parameters.\n\nThe `cities` query parameter is case-insensitive.\n\nThe list of `cities` provided by your RETS vendor or MLS can\nbe seen by sending an `OPTIONS` request to the `/properties`\nendpoint:\n\n`curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/openhouses`')
    counties: list[str] | None = Field(None, description='Filter the listings returned by specific counties. You can\nspecify multiple `counties` parameters.\n\nThe `counties` query parameter is case-insensitive.\n\nThe list of `counties` provided by your RETS vendor or MLS\ncan be seen by sending an `OPTIONS` request to the\n`/properties` endpoint:\n\n`curl -XOPTIONS -u simplyrets:simplyrets https://api.simplyrets.com/openhouses`')
    points: list[str] | None = Field(None, description='Return listings that are within a set of latitude\nlongitude coordinates. For example;\n```\n29.723837,-95.69778\n29.938275,-95.69778\n29.938275,-95.32974\n29.723837,-95.32974\n```\n\nNote that some RETS vendors do not provide latitude and\nlongitude with their listings, which is required for this\nparameter to work. In these cases, SimplyRETS offers a\n[Geocoding Addon](https://simplyrets.com/services#geocoding).\n\nCheck out our\n[blog post](https://simplyrets.com/blog/interactive-map-search.html)\non using the `points` parameter to build a map-based app\nin javascript.')
    idx: list[Literal['null', 'listing', 'address', 'ignore']] | None = Field(None, description="Specify the IDX display requirements for the listings in the response. The `idx` parameter checks if the `internetAddressDisplay` and `internetEntireListingDisplay` for each listing are true (or `null`) or false based on this setting.\n##### **`idx=null`** (default)\n  - `internetAddressDisplay` must be true\n  - `internetEntireListingDisplay` must be true\n##### **`idx=listing`**\n  - `internetAddressDisplay` is ignored\n  - `internetEntireListingDisplay` must be true\n##### **`idx=address`**\n  - `internetAddressDisplay` must be true\n  - `internetEntireListingDisplay` is ignored\n##### **`idx=ignore`**\n  - `internetAddressDisplay` is ignored\n  - `internetEntireListingDisplay` is ignored\n\nLearn more about SimplyRETS's [IDX compliance features here](/topics/fields-and-features-for-idx-compliance) and please check with your MLS or data feed provider on the rules and requirements for displaying restricted listings.")
    include: list[Literal['compliance', 'rooms']] | None = Field(None, description="Enable additional fields in the API response. The available\n`include` values are:\n\n- `include=compliance`: Adds `.compliance` data to the API\n  response.  Compliance data will contain extra fields that\n  may be required in your IDX display. Please check your MLS's\n  or association's specific IDX display requirements.\n\n- `include=rooms`: Adds `.rooms` data to the API response.\n  Rooms data contains additional information about individual\n  rooms on the property (e.g. bedrooms, living room). Not all\n  feeds support this extended data. Enabled upon request.")
    sort: Literal['listprice', '-listprice', 'listdate', '-listdate', 'closedate', '-closedate', 'beds', '-beds', 'baths', '-baths'] | None = Field(None, description='Sort the response by a specific field. Values starting\nwith a minus (-) denote descending order, while the others\nare ascending.')
    count: bool | None = Field(None, description='When set to `true`, The `X-Total-Count` header will be\nreturned, showing the total number of items matching the query.\n\nCounting the listings can contribute to slower API calls\ndue to the extra queries that need to be run to get an\nexact count.\n\nEnabling count may decrease API response/page load times,\nespecially on larger datasets.')

class SimplyRETSGetPropertyAnalyticsConfig(_Input):
    operation: Literal['get_property_analytics'] = Field('get_property_analytics', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Listing Analytics', "x-is-trigger": False})
    mlsId: int = Field(..., description='The `mlsId` field is a unique identifier which is specific\nto the SimplyRETS API only.  This field is different from\nthe `listingId` field (which is the public number given to\na listing by the RETS vendor or MLS and is not used here).', ge=1)
    vendor: str | None = Field(None, description="Used to specify the RETS vendor to search from. This\nparameter is required on multi-MLS apps. You can query one\nvendor at a time. To get your vendor id's make an HTTP\nOPTIONS request to https://api.simplyrets.com.\n\n`curl -XOPTIONS https://api.simplyrets.com/properties` Required on multi-MLS accounts; copy a vendor ID from Get Account Metadata.", json_schema_extra={"x-dynamic-options": {"field_name": "vendor", "allow_custom": True}})

class SimplyRETSGetAccountMetadataConfig(_Input):
    operation: Literal['get_account_metadata'] = Field('get_account_metadata', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Account Metadata', "x-is-trigger": False})

class SimplyRETSGetPropertyMetadataConfig(_Input):
    operation: Literal['get_property_metadata'] = Field('get_property_metadata', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Listing Metadata', "x-is-trigger": False})
    vendor: str | None = Field(None, description="Used to specify the RETS vendor to search from. This\nparameter is required on multi-MLS apps. You can query one\nvendor at a time. To get your vendor id's make an HTTP\nOPTIONS request to https://api.simplyrets.com.\n\n`curl -XOPTIONS https://api.simplyrets.com/properties` Required on multi-MLS accounts; copy a vendor ID from Get Account Metadata.", json_schema_extra={"x-dynamic-options": {"field_name": "vendor", "allow_custom": True}})

class SimplyRETSGetOfficeMetadataConfig(_Input):
    operation: Literal['get_office_metadata'] = Field('get_office_metadata', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get Office Metadata', "x-is-trigger": False})


class SimplyRETSOnNewOrUpdatedPropertyConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_property"] = Field("on_new_or_updated_property", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers",
        "x-display-name": "On New or Updated Listing",
    })
    vendor: str | None = Field(None, description="Vendor ID, required for multi-MLS accounts.", json_schema_extra={"x-dynamic-options": {"field_name": "vendor", "allow_custom": True}})
    modified: str | None = Field(None, description="Optional fixed earliest MLS modification time, e.g. 2026-10-01T00:00:00Z. Feeds without modification timestamps ignore this filter. First poll establishes a baseline.")
    cities: list[str] | None = None
    status: list[Literal["Active", "Pending", "Closed", "ActiveUnderContract", "Hold", "Withdrawn", "Expired", "Delete", "Incomplete", "ComingSoon"]] | None = Field(None, description="Statuses to monitor. When omitted SimplyRETS defaults to Active.")

SimplyRETSOperation = Annotated[Union[SimplyRETSListPropertiesConfig, SimplyRETSGetPropertyConfig, SimplyRETSListOpenhousesConfig, SimplyRETSGetOpenhouseConfig, SimplyRETSListPropertyKeysConfig, SimplyRETSListAgentsConfig, SimplyRETSListOfficesConfig, SimplyRETSGetMarketAnalyticsConfig, SimplyRETSGetPropertyAnalyticsConfig, SimplyRETSGetAccountMetadataConfig, SimplyRETSGetPropertyMetadataConfig, SimplyRETSGetOfficeMetadataConfig, SimplyRETSOnNewOrUpdatedPropertyConfig], Field(discriminator="operation")]


class SimplyRETSNodeConfig(NodeConfig[SimplyRETSOperation, SimplyRETSCredential]):
    pass

ROUTES = {'list_properties': ('GET', '/properties'), 'get_property': ('GET', '/properties/{mlsId}'), 'list_openhouses': ('GET', '/openhouses'), 'get_openhouse': ('GET', '/openhouses/{openHouseKey}'), 'list_property_keys': ('GET', '/properties/keys'), 'list_agents': ('GET', '/agents'), 'list_offices': ('GET', '/offices'), 'get_market_analytics': ('GET', '/properties/analytics'), 'get_property_analytics': ('GET', '/properties/{mlsId}/analytics'), 'get_account_metadata': ('OPTIONS', '/'), 'get_property_metadata': ('OPTIONS', '/properties'), 'get_office_metadata': ('OPTIONS', '/offices')}
QUERY_FIELDS = {'list_properties': ['q', 'status', 'type', 'subtype', 'subTypeText', 'agent', 'coListAgent', 'salesAgent', 'brokers', 'specialListingConditions', 'ownership', 'minprice', 'maxprice', 'minarea', 'maxarea', 'minbaths', 'maxbaths', 'minbeds', 'maxbeds', 'maxdom', 'minlistdate', 'maxlistdate', 'modified', 'minyear', 'maxyear', 'minacres', 'maxacres', 'minGarageSpaces', 'maxGarageSpaces', 'limit', 'offset', 'lastId', 'vendor', 'postalCodes', 'features', 'exteriorFeatures', 'pool', 'water', 'neighborhoods', 'cities', 'state', 'counties', 'points', 'idx', 'include', 'sort', 'count'], 'get_property': ['vendor'], 'list_openhouses': ['type', 'listingId', 'cities', 'vendor', 'brokers', 'agent', 'minprice', 'maxprice', 'startdate', 'lastId', 'minarea', 'minbeds', 'minbaths', 'offset', 'limit', 'sort', 'include'], 'get_openhouse': ['vendor', 'include'], 'list_property_keys': ['q', 'status', 'type', 'subtype', 'subTypeText', 'agent', 'coListAgent', 'salesAgent', 'brokers', 'specialListingConditions', 'ownership', 'minprice', 'maxprice', 'minarea', 'maxarea', 'minbaths', 'maxbaths', 'minbeds', 'maxbeds', 'maxdom', 'minlistdate', 'maxlistdate', 'modified', 'minyear', 'maxyear', 'minacres', 'maxacres', 'minGarageSpaces', 'maxGarageSpaces', 'limit', 'offset', 'lastId', 'vendor', 'postalCodes', 'features', 'exteriorFeatures', 'water', 'neighborhoods', 'cities', 'state', 'counties', 'points', 'idx', 'sort'], 'list_agents': ['q', 'name', 'state'], 'list_offices': ['q', 'name', 'state', 'count', 'offset', 'limit', 'vendor', 'username'], 'get_market_analytics': ['q', 'status', 'type', 'subtype', 'agent', 'salesAgent', 'brokers', 'minprice', 'maxprice', 'minarea', 'maxarea', 'minbaths', 'maxbaths', 'minbeds', 'maxbeds', 'maxdom', 'minyear', 'maxyear', 'minacres', 'maxacres', 'minGarageSpaces', 'maxGarageSpaces', 'limit', 'offset', 'lastId', 'vendor', 'postalCodes', 'features', 'exteriorFeatures', 'pool', 'water', 'neighborhoods', 'cities', 'counties', 'points', 'idx', 'include', 'sort', 'count'], 'get_property_analytics': ['vendor'], 'get_account_metadata': [], 'get_property_metadata': ['vendor'], 'get_office_metadata': []}
RESPONSE_SHAPES = {'list_properties': 'list', 'get_property': 'dict', 'list_openhouses': 'list', 'get_openhouse': 'dict', 'list_property_keys': 'dict', 'list_agents': 'list', 'list_offices': 'list', 'get_market_analytics': 'dict', 'get_property_analytics': 'dict', 'get_account_metadata': 'dict', 'get_property_metadata': 'dict', 'get_office_metadata': 'dict'}


class SimplyRETSNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-simplyrets"
    connection_evidence = ConnectionEvidence(field="vendor", noun="MLS feeds")

    @classmethod
    def get_config_model(cls):
        return SimplyRETSNodeConfig

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "vendor":
            return []
        credential = SimplyRETSCredential.model_validate(credential_data)
        probe = cls(node_id="simplyrets-feed-options", node_type="automation-simplyrets", node_data={},
            config=SimplyRETSNodeConfig(config=SimplyRETSGetAccountMetadataConfig(), credentials=credential))
        body, _ = await probe._request("OPTIONS", "/")
        vendors = body.get("vendors") if isinstance(body, dict) else None
        if not isinstance(vendors, list) or any(not isinstance(vendor, str) for vendor in vendors):
            raise ValueError("SimplyRETS did not return its documented vendor list")
        return [{"value": vendor, "label": vendor} for vendor in vendors
            if not search or search.casefold() in vendor.casefold()]

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_or_updated_property":
            return bool(output.get("new_or_updated_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        listings = output.get("listings")
        if not isinstance(listings, list) or not listings:
            return None
        lines = [f"{len(listings)} new or updated SimplyRETS MLS listing(s)"]
        for row in listings:
            address = row.get("address") or {}
            mls = row.get("mls") or {}
            agent = row.get("agent") or {}
            name = " ".join(str(agent[key]) for key in ("firstName", "lastName") if agent.get(key))
            lines.append(f"Listing {row['mlsId']}: {address.get('full') or row.get('listingId') or 'Address unavailable'}; "
                f"status {mls.get('status')}; price {row.get('listPrice')}; agent {name or agent.get('id')}; "
                f"modified {row.get('modified')}. {row.get('remarks') or ''}")
        if output.get("vendor"):
            lines.append(f"Vendor: {output['vendor']}")
        return {"text": "\n".join(lines), "data": {"listings": listings, "vendor": output.get("vendor")}}

    async def _request(self, method, path, params=None):
        credential = self.config.credentials
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                auth=httpx.BasicAuth(credential.api_key, credential.api_secret),
                headers={"Accept": "application/json"}, params=params or {})
        if response.status_code != 200:
            # Preserve provider rejection text for connection evidence, redact
            # credentials if a provider happens to echo them in an error.
            try:
                message = response.json().get("message")
            except (ValueError, AttributeError):
                message = None
            text = message if isinstance(message, str) else "SimplyRETS request failed"
            for secret in (credential.api_key, credential.api_secret):
                text = text.replace(secret, "[redacted]")
            raise ValueError(f"SimplyRETS HTTP {response.status_code}: {text[:1000]}")
        body = response.json()
        if isinstance(body, dict) and "error" in body:
            raise ValueError("SimplyRETS returned an error response")
        return body, response

    @staticmethod
    def _page(response, path):
        """Expose pagination values; never follow a provider-supplied URL."""
        link = response.links.get("next", {}).get("url")
        if not link:
            return None
        parsed = urlsplit(link)
        if parsed.scheme != "https" or parsed.netloc != "api.simplyrets.com" or parsed.path != path or parsed.fragment:
            raise ValueError("SimplyRETS returned an unexpected pagination URL")
        params = parse_qs(parsed.query)
        result = {}
        for key in ("lastId", "offset", "limit"):
            values = params.get(key)
            if values:
                if len(values) != 1 or not values[0].isdigit():
                    raise ValueError("SimplyRETS returned invalid pagination values")
                result[key] = int(values[0])
        return result or None

    async def _poll_listings(self, config):
        filters = config.model_dump(include={"vendor", "modified", "cities", "status"}, exclude_none=True)
        rows = []
        visited = set()
        page = {"offset": 0, "limit": 500}
        for _ in range(20):
            body, response = await self._request("GET", "/properties", {**filters, **page})
            if not isinstance(body, list) or any(not isinstance(row, dict) for row in body):
                raise ValueError("SimplyRETS listings must be an array of objects")
            rows.extend(body)
            following = self._page(response, "/properties")
            if following:
                cursor = {key: value for key, value in following.items() if key in {"offset", "lastId"}}
                if not cursor or cursor == {key: value for key, value in page.items() if key != "limit"}:
                    raise ValueError("SimplyRETS listing pagination did not advance")
                marker = json.dumps(cursor, sort_keys=True)
                if marker in visited:
                    raise ValueError("SimplyRETS listing pagination repeated a cursor")
                visited.add(marker)
                page = {**cursor, "limit": 500}
            elif len(body) < 500:
                break
            else:
                raise ValueError("SimplyRETS returned a full page without a next link; narrow the trigger filters")
        else:
            raise ValueError("SimplyRETS trigger exceeds 10000 listings; narrow the filters before polling")
        if len(rows) > 10000:
            raise ValueError("SimplyRETS trigger exceeds 10000 listings; narrow the filters")
        ids = []
        for row in rows:
            if type(row.get("mlsId")) is not int:
                raise ValueError("SimplyRETS listing is missing its numeric mlsId")
            ids.append(row["mlsId"])
        if len(set(ids)) != len(ids):
            raise ValueError("SimplyRETS repeated a listing across pages; retry the poll")
        # Timestamp-less feeds are documented: fingerprint the entire returned
        # listing so changes still fire without inventing a modification date.
        fresh = await self._filter_unseen(rows, lambda row: str(row["mlsId"]) + ":" +
            hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        return {"listings": fresh, "new_or_updated_count": len(fresh), "vendor": config.vendor}

    async def execute(self, inputs):
        if not isinstance(self.config, SimplyRETSNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a SimplyRETS API key and secret")
        config = self.config.config
        if isinstance(config, SimplyRETSOnNewOrUpdatedPropertyConfig):
            return await self._poll_listings(config)
        operation = config.operation
        method, path = ROUTES[operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for name in ("mlsId", "openHouseKey"):
            marker = "{" + name + "}"
            if marker in path:
                path = path.replace(marker, str(values.pop(name)))
        params = {key: values[key] for key in QUERY_FIELDS[operation] if key in values}
        body, response = await self._request(method, path, params)
        expected = list if RESPONSE_SHAPES[operation] == "list" else dict
        if not isinstance(body, expected):
            raise ValueError("SimplyRETS returned an unexpected response shape")
        return {"data": body, "next_page": self._page(response, path),
            "total_count": response.headers.get("X-Total-Count"),
            "last_update": response.headers.get("X-SimplyRETS-LastUpdate")}
