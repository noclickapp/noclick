"""Addressfinder's 17 published lookup and verification endpoints.

Server-to-server key + secret authentication follows the provider's guide:
https://addressfinder.com/au/docs/api/authentication/overview
The pinned 1.1.0 API exposes reads only. Verification outcomes are preserved
separately from transport success; a successful lookup need not verify a value.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, SSRFError

NODE_TYPE = "automation-addressfinder"
BASE = "https://api.addressfinder.io/api"


class AddressfinderAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Addressfinder API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://portal.addressfinder.net/",
            "x-credential-instructions": "Copy the API key and secret from your Addressfinder project's Keys section. NoClick sends the key as a query parameter and the raw secret in the Authorization header for server-to-server calls. The connection check searches Australian addresses and proves API reachability, not account identity. Your project needs the services used by your operations. Lookups may incur provider charges.",
        })
    credential_type: Literal["addressfinder_api_key"] = Field("addressfinder_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=4096, title="API secret", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        if not isinstance(value, str):
            raise ValueError("Paste the issued credential value")
        value = clean_secret(value, field_name=info.field_name, key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the credential without whitespace or an authorization prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def single_line(cls, value):
        if isinstance(value, str) and (not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Use nonempty single-line text")
        return value


class SearchAuAddressesConfig(_Input):
    """Address Autocomplete API: /au/address/autocomplete."""
    operation: Literal['search_au_addresses'] = Field('search_au_addresses', title='Search AU Addresses', json_schema_extra={"ui:hidden": True})
    q: str = Field('Unit 2, 21 Kent Road', description='The partial address being searched', max_length=200)
    source: Literal['GNAF,PAF', 'GNAF', 'PAF'] | None = Field(None, description='Determines the source of the addresses being searched and returned.\n  * `GNAF` - Returns physical addresses from the GNAF address dataset.\n  * `PAF` - Returns postal addresses, including PO Box type addresses, from the Australia Post postal address file.\n  * `GNAF,PAF` - Returns addresses from either of the PAF or GNAF address datasets.')
    post_box: Literal['0', '1'] | None = Field(None, description='Return PO Box style addresses. This includes PO Box, Locked Bag, GPO Box, CMB, RMS, Care PO, MS, RSD, Parcel Locker and Parcel Collect. Used with the `source` filter above:\n  * `0` - Set this option to exclude PO Box style addresses from your search results\n  * `1` - Returns only PO Box style addresses\n  * Omit to return PO Box addresses with deliverable addresses')
    canonical: Literal['1'] | None = Field(None, description='Return canonical and/or alias addresses - this allows for vanity suburbs, historic street names, and more:\n  * `1` - Alias addresses are not included in the search results\n  * Omit to return canonical and alias addresses are returned (most common option)')
    state_codes: str | None = Field(None, description='Filter the results according to the states or territories. Use a comma to separate multiple values:\n  * `ACT` - Only returns addresses from Australian Capital Territory\n  * `NSW` - Only returns addresses from New South Wales\n  * `NT` - Only returns addresses from Northern Territory\n  * `QLD` - Only returns addresses from Queensland\n  * `SA` - Only returns addresses from South Australia\n  * `TAS` - Only returns addresses from Tasmania\n  * `VIC` - Only returns addresses from Victoria\n  * `WA` - Only returns addresses from Western Australia\n  * `OT` - Only returns addresses from Other Territories', min_length=1, max_length=2048)
    domain: str | None = Field(None, description='Used to identify which of your services is calling the API for activity monitoring purposes. This domain needs to be registered in the portal.', min_length=1, max_length=2048)
    max: int | None = Field(None, description='The maximum number of results to return. The default is 10 results.', ge=1, le=100, strict=True)
    highlight: Literal['1'] | None = Field(None, description="Returns an additional attribute in the response called `highlighted_full_address`. This attribute wraps the matching terms in the address with `<span class='af_hl'></span>` in order to highlight those terms:\n  * `1` - Matching terms in the returned addresses are highlighted.\n  * Omit to not return additional `highlighted_full_address` property")
    ascii: Literal['1'] | None = Field(None, description='Set to `1` to reformat special characters like macrons and other accents characters with their ASCII equivalent (e.g. *Pōneke* and *Café* will be returned as *Poneke* and *Cafe*).')

class GetAuAddressMetadataConfig(_Input):
    """Address Metadata API: /au/address/metadata."""
    operation: Literal['get_au_address_metadata'] = Field('get_au_address_metadata', title='Get AU Address Metadata', json_schema_extra={"ui:hidden": True})
    id: str | None = Field(None, description='Unique address identifier obtained from the Address Autocomplete API.\nYou must supply either an id, or a gnaf_id, or a dpid field.', min_length=1, max_length=2048)
    gnaf_id: str | None = Field(None, description='Unique id from the G-NAF dataset.\n\nYou must supply either an id, or a gnaf_id, or a dpid field.', min_length=1, max_length=2048)
    dpid: str | None = Field(None, description='Australia Post delivery point identifier.\n\nYou must supply either an id, or a gnaf_id, or a dpid field.', min_length=1, max_length=2048)
    source: Literal['GNAF,PAF', 'GNAF', 'PAF'] | None = Field(None, description='Determines the source of the address and metadata returned..\n  * `GNAF` - Returns physical addresses from the GNAF address dataset.\n  * `PAF` - Returns postal addresses, including PO Box type addresses, from the Australia Post postal address file.\n  * `GNAF,PAF` - Returns addresses from either of the PAF or GNAF address datasets.')
    gps: Literal['1'] | None = Field(None, description='Request GPS coordinates for `latitude` and `longitude` be returned when available:\n  * `1` - GPS coordinates wil be included in the response\n  * Omit to GPS coordinates')
    domain: str | None = Field(None, description='Used to identify which of your services is calling the API for activity monitoring purposes. This domain needs to be registered in the portal.', min_length=1, max_length=2048)
    census: Literal[2016, 2021] | None = Field(None, description='Used to determine which census year’s statistical area identifiers (Meshblock, SA1 & SA2) will be returned in the response. Defaults to `2016` if omitted.')
    ascii: Literal['1'] | None = Field(None, description='Set to `1` to reformat special characters like macrons and other accents characters with their ASCII equivalent (e.g. *Pōneke* and *Café* will be returned as *Poneke* and *Cafe*).')

    @model_validator(mode="after")
    def identifier(self):
        if not any((self.id, self.gnaf_id, self.dpid)):
            raise ValueError("Supply id, gnaf_id or dpid from Addressfinder")
        return self

class VerifyAuAddressConfig(_Input):
    """Address Verification API: /au/address/v2/verification."""
    operation: Literal['verify_au_address'] = Field('verify_au_address', title='Verify AU Address', json_schema_extra={"ui:hidden": True})
    q: str = Field(..., description='The address to be verified.', min_length=1, max_length=200)
    gnaf: Literal['1'] | None = Field(None, description='Returns physical addresses from the GNAF database. One or both of GNAF or PAF databases need to be selected.\n  * `1` - Queries the GNAF database')
    paf: Literal['1'] | None = Field(None, description='Returns postal addresses from the PAF database. One or both of GNAF or PAF databases need to be selected.\n  * `1` - queries the AU PAF database')
    post_box: Literal['0'] | None = Field(None, description='Box type addresses are included by default (only available from PAF database). Box type addresses include PO Box, Locked Bag, GPO Box, CMB, RMS, Care PO, MS, RSD, Parcel Locker and Parcel Collect. Use this attribute to exclude them.\n * `0` - Excludes Box type addresses from the verification results.')
    gps: Literal['1'] | None = Field(None, description='Returns gps coordinates from the datasource specified (when available).\n * `1` - Returns latitude and longitude.')
    extended: Literal['1'] | None = Field(None, description='Returns `lga_name`, `lga_type_code`, `gnaf_id` and `legal_parcel_id` from the GNAF database.\n * `1` - Returns additional data available from GNAF.')
    census: Literal[2016, 2021] | None = Field(None, description='Returns statistical area identifiers (Meshblock, SA1 & SA2) from the specified census year. These attributes are only available from the GNAF database and are not returned if census is omitted.')
    state_codes: Literal['ACT', 'NSW', 'NT', 'QLD', 'SA', 'TAS', 'VIC', 'WA', 'OT'] | None = Field(None, description='Filter the results according to the states or territories. Use a comma to separate multiple values:\n  * `ACT` - Only returns addresses from Australian Capital Territory\n  * `NSW` - Only returns addresses from New South Wales\n  * `NT` - Only returns addresses from Northern Territory\n  * `QLD` - Only returns addresses from Queensland\n  * `SA` - Only returns addresses from South Australia\n  * `TAS` - Only returns addresses from Tasmania\n  * `VIC` - Only returns addresses from Victoria\n  * `WA` - Only returns addresses from Western Australia\n  * `OT` - Only returns addresses from Other Territories')
    domain: str | None = Field(None, description='Used to identify which of your services is calling the API for activity monitoring purposes. This domain needs to be registered in the portal.', min_length=1, max_length=2048)
    ascii: Literal['1'] | None = Field(None, description='Set to `1` to reformat special characters like macrons and other accents characters with their ASCII equivalent (e.g. *Pōneke* and *Café* will be returned as *Poneke* and *Cafe*).')

class SearchAuLocationsConfig(_Input):
    """Location Autocomplete API: /au/location/autocomplete."""
    operation: Literal['search_au_locations'] = Field('search_au_locations', title='Search AU Locations', json_schema_extra={"ui:hidden": True})
    q: str = Field(..., description='The query string to be matched with the location.', min_length=1, max_length=200)
    location_types: str | None = Field(None, description='A comma-separated list of location types to filter the results. Leave empty to allow any location type. Options are `street`, `locality` (suburb), and `state`.', min_length=1, max_length=2048)
    state_codes: str | None = Field(None, description='A comma-separated list of states or territories to filter results. Options: ACT, NSW, NT, QLD, SA, TAS, VIC, WA, OT.', min_length=1, max_length=2048)
    domain: str | None = Field(None, description='Used to identify in the Addressfinder Portal which of your services is calling the API for activity monitoring purposes. The domain needs to be registered in the Portal.', min_length=1, max_length=2048)
    max: int | None = Field(None, description='Maximum number of results to return (1–100).', ge=1, le=100, strict=True)
    highlight: Literal[0, 1] | None = Field(None, description="Set to `1` to include a `highlighted_full_location` field in results, wrapping matching terms with `<span class='af_hl'></span>`.")

class GetAuLocationMetadataConfig(_Input):
    """Location Metadata API: /au/location/metadata."""
    operation: Literal['get_au_location_metadata'] = Field('get_au_location_metadata', title='Get AU Location Metadata', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Unique location identifier obtained from the Location Autocomplete API.', min_length=1, max_length=2048)
    domain: str | None = Field(None, description='Used to identify in the Addressfinder Portal which of your services is calling the API. The domain needs to be registered in the Portal.', min_length=1, max_length=2048)

class SearchNzAddressesConfig(_Input):
    """Address Autocomplete API: /nz/address/autocomplete."""
    operation: Literal['search_nz_addresses'] = Field('search_nz_addresses', title='Search NZ Addresses', json_schema_extra={"ui:hidden": True})
    q: str = Field(..., description='The partial address being searched', min_length=1, max_length=200)
    delivered: Literal['0', '1'] | None = Field(None, description='This filter determines if the results are either delivered or not delivered by NZ Post:\n  * `0` A rarely used option that excludes addresses that NZ Post deliver to.\n  * `1` - Only returns addresses that are delivered to by NZ Post.\n  * Omit to not filter. Returns delivered and non-delivered addresses in the response.')
    post_box: Literal['0', '1'] | None = Field(None, description='This filter includes/excludes PO Box style addresses.\n  * `0` - Excludes PO Box type addresses from being returned in the response.\n  * `1` - Returns only PO Box, Private Bag, Community Mailbox and Counter Delivery address types.\n  * Omit to not filter. Returns PO Box type and standard addresses in the response.')
    rural: Literal['0', '1'] | None = Field(None, description='This filter includes/excludes rural/urban addresses:\n  * `0` - Excludes addresses likely to be considered rural by a courier company.\n  * `1` - A rarely used option that returns rural addresses only.\n  * Omit to not filter. Returns rural and urban addresses in the response')
    strict: Literal['0', '1', '2'] | None = Field(None, description='Determines how closely matched the results should be to the `q` parameter:\n  * `0` - Normal search - Allows some address elements to be omitted but does not allow spelling errors.\n  * `1` - Strict search - Requires all address elements entered in `q` to be ordered and spelt correctly.\n  * `2` - Fuzzy search - Allows spelling errors and inaccurate address elements.')
    region_code: Literal['1', '2', '3', '4', '5', '6', '7', '8', '9', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'] | None = Field(None, description="Only return addresses within the boundary of the selected region (Regional Authority):\n  * `1` -  Only returns addresses from the Auckland Region\n  * `2` -  Only returns addresses from the Bay of Plenty Region\n  * `3` -  Only returns addresses from the Canterbury Region\n  * `4` -  Only returns addresses from the Gisbourne Region\n  * `5` -  Only returns addresses from the Hawke's Bay Region\n  * `6` -  Only returns addresses from the Manawatu-Wanganui Region\n  * `7` -  Only returns addresses from the Marlborough Region\n  * `8` -  Only returns addresses from the Nelson Region\n  * `9` -  Only returns addresses from the Northland Region\n  * `A` -  Only returns addresses from the Otago Region\n  * `B` -  Only returns addresses from the Southland Region\n  * `C` -  Only returns addresses from the Taranaki Region\n  * `D` -  Only returns addresses from the Tasman Region\n  * `E` -  Only returns addresses from the Waikato Region\n  * `F` -  Only returns addresses from the Wellington Region\n  * `G` -  Only returns addresses from the West Coast Region\n  * `H` -  Only returns addresses from the Chatham Islands Region\n  * Omit to not filter. Returns addresses from all Regions")
    domain: str | None = Field(None, description='Used to identify which of your services is calling the API for activity monitoring purposes. This domain needs to be registered in the portal.', min_length=1, max_length=2048)
    max: int | None = Field(None, description='The maximum number of results to return. The default is 10 results.', ge=1, le=100, strict=True)
    highlight: Literal['1'] | None = Field(None, description="Returns an additional attribute in the response called highlighted_a. This attribute wraps the matching terms in the address with `<span class='af_hl'></span>` in order to highlight those terms:\n  * `1` - Highlighted.\n  * Omit to not return additional `highlighted_a` property")
    ascii: Literal['1'] | None = Field(None, description='Set to `1` to reformat special characters like macrons and other accents characters with their ASCII equivalent (e.g. *Pōneke* and *Café* will be returned as *Poneke* and *Cafe*).')

class GetNzAddressMetadataConfig(_Input):
    """Address Metadata API: /nz/address/metadata."""
    operation: Literal['get_nz_address_metadata'] = Field('get_nz_address_metadata', title='Get NZ Address Metadata', json_schema_extra={"ui:hidden": True})
    pxid: str | None = Field(None, description='Unique address identifier obtained from the NZ Address Autocomplete or NZ Address Bounding Box APIs.\nYou must supply either a pxid or dpid field.', min_length=1, max_length=2048)
    dpid: str | None = Field(None, description='Unique reference number assigned to a delivery address by NZ Post.\n\nYou must supply either a pxid or dpid field.', min_length=1, max_length=2048)
    census: Literal[2018, 2023] | None = Field(None, description='Desired data source for Statistics NZ metadata.')
    domain: str | None = Field(None, description='Used to identify which of your services is calling the API for activity monitoring purposes. This domain needs to be registered in the portal.', min_length=1, max_length=2048)
    ascii: Literal['1'] | None = Field(None, description='Set to `1` to reformat special characters like macrons and other accents characters with their ASCII equivalent (e.g. *Pōneke* and *Café* will be returned as *Poneke* and *Cafe*).')

    @model_validator(mode="after")
    def identifier(self):
        if not any((self.pxid, self.dpid)):
            raise ValueError("Supply pxid or dpid from Addressfinder")
        return self

class VerifyNzAddressConfig(_Input):
    """Address Verification API: /nz/address/verification."""
    operation: Literal['verify_nz_address'] = Field('verify_nz_address', title='Verify NZ Address', json_schema_extra={"ui:hidden": True})
    q: str = Field(..., description='The address to be verified.', min_length=1, max_length=200)
    post_box: Literal['0', '1'] | None = Field(None, description='This filter includes/excludes PO Box style addresses.\n  * `0` - Excludes PO Box type addresses from being returned in the response.\n  * `1` - Returns only PO Box, Private Bag, Community Mailbox and Counter Delivery address types.\n  * Omit to not filter. Returns PO Box type and standard addresses in the response.')
    region_code: Literal['1', '2', '3', '4', '5', '6', '7', '8', '9', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'] | None = Field(None, description="Will only match and return an address if exists within the selected region (Regional Authority).\n\n  Including a region can improve your match success rate as it removes the possibility of matching addresses outside the selected region.\n\n  * `1` -  Only returns addresses from the Auckland Region\n  * `2` -  Only returns addresses from the Bay of Plenty Region\n  * `3` -  Only returns addresses from the Canterbury Region\n  * `4` -  Only returns addresses from the Gisbourne Region\n  * `5` -  Only returns addresses from the Hawke's Bay Region\n  * `6` -  Only returns addresses from the Manawatu-Wanganui Region\n  * `7` -  Only returns addresses from the Marlborough Region\n  * `8` -  Only returns addresses from the Nelson Region\n  * `9` -  Only returns addresses from the Northland Region\n  * `A` -  Only returns addresses from the Otago Region\n  * `B` -  Only returns addresses from the Southland Region\n  * `C` -  Only returns addresses from the Taranaki Region\n  * `D` -  Only returns addresses from the Tasman Region\n  * `E` -  Only returns addresses from the Waikato Region\n  * `F` -  Only returns addresses from the Wellington Region\n  * `G` -  Only returns addresses from the West Coast Region\n  * `H` -  Only returns addresses from the Chatham Islands Region\n  * Omit to not filter. Returns addresses from all Regions")
    census: Literal[2018, 2023] | None = Field(None, description='Desired data source for Statistics NZ metadata.')
    domain: str | None = Field(None, description='Used to identify which of your services is calling the API for activity monitoring purposes. This domain needs to be registered in the portal.', min_length=1, max_length=2048)
    ascii: Literal['1'] | None = Field(None, description='Set to `1` to reformat special characters like macrons and other accents characters with their ASCII equivalent (e.g. *Pōneke* and *Café* will be returned as *Poneke* and *Cafe*).')

class SearchNzLocationsConfig(_Input):
    """Location Autocomplete API: /nz/location/autocomplete."""
    operation: Literal['search_nz_locations'] = Field('search_nz_locations', title='Search NZ Locations', json_schema_extra={"ui:hidden": True})
    q: str = Field(..., description='The query string to be matched with the location.', min_length=1, max_length=200)
    street: Literal['0', '1'] | None = Field(None, description='Set to 0 to exclude streets, 1 to include only streets.')
    suburb: Literal['0', '1'] | None = Field(None, description='Set to 0 to exclude suburbs, 1 to include only suburbs.')
    city: Literal['0', '1'] | None = Field(None, description='Set to 0 to exclude cities, 1 to include only cities.')
    region: Literal['0', '1'] | None = Field(None, description='Set to 0 to exclude regions, 1 to include only regions.')
    region_code: str | None = Field(None, description="Restricts results to a region. Valid codes include: Auckland `1`, Bay of Plenty `2`, Canterbury `3`, Gisborne `4`, Hawke's Bay `5`, Manawatū-Whanganui `6`, Marlborough `7`, Nelson `8`, Northland `9`, Otago `A`, Southland `B`, Taranaki `C`, Tasman `D`, Waikato `E`, Wellington `F`, West Coast `G`, Chatham Islands `H`.", min_length=1, max_length=2048)
    strict: Literal['0', '1', '2'] | None = Field(None, description='Match strictness: - `0`: normal (no spelling errors) - `1`: strict (must be ordered and spelled correctly) - `2`: fuzzy (allows misspelling)')
    domain: str | None = Field(None, description='Used to identify the calling service in the Addressfinder Portal. Must be a registered domain.', min_length=1, max_length=2048)
    max: int | None = Field(None, description='Max results to return (1–100).', ge=1, le=100, strict=True)
    highlight: Literal[0, 1] | None = Field(None, description="Set to 1 to return an attribute `highlighted_a` which wraps matched text with `<span class='af_hl'></span>`.")

class GetNzLocationMetadataConfig(_Input):
    """Location Metadata API: /nz/location/metadata."""
    operation: Literal['get_nz_location_metadata'] = Field('get_nz_location_metadata', title='Get NZ Location Metadata', json_schema_extra={"ui:hidden": True})
    pxid: str = Field(..., description='Unique address identifier from the Location Autocomplete API.', min_length=1, max_length=2048)
    domain: str | None = Field(None, description='Used to identify your calling service for usage tracking in the Addressfinder Portal. Must be registered in the Portal.', min_length=1, max_length=2048)

class SearchNzPointsOfInterestConfig(_Input):
    """POI Autocomplete API: /nz/points_of_interest/autocomplete."""
    operation: Literal['search_nz_points_of_interest'] = Field('search_nz_points_of_interest', title='Search NZ Points Of Interest', json_schema_extra={"ui:hidden": True})
    q: str = Field(..., description='The query string to match against POI names and addresses.', min_length=1, max_length=200)
    domain: str | None = Field(None, description='Used to identify your service in the Addressfinder Portal. Must be a registered domain in the Portal.', min_length=1, max_length=2048)
    max: int | None = Field(None, description='Maximum number of results to return (1–100).', ge=1, le=100, strict=True)
    highlight: Literal[0, 1] | None = Field(None, description="Set to `1` to include `highlighted_name_and_address` in results, wrapping matched text with `<span class='af_hl'></span>`.")

class GetNzPointOfInterestMetadataConfig(_Input):
    """POI Metadata API: /nz/points_of_interest/metadata."""
    operation: Literal['get_nz_point_of_interest_metadata'] = Field('get_nz_point_of_interest_metadata', title='Get NZ Point Of Interest Metadata', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Unique POI identifier from the autocomplete API.', min_length=1, max_length=2048)
    domain: str | None = Field(None, description='Used to identify your service in the Addressfinder Portal. Must be registered in the Portal.', min_length=1, max_length=2048)

class GetNzReverseGeocodeConfig(_Input):
    """Address Reverse Geocode API: /nz/address/reverse_geocode."""
    operation: Literal['get_nz_reverse_geocode'] = Field('get_nz_reverse_geocode', title='Get NZ Reverse Geocode', json_schema_extra={"ui:hidden": True})
    x: str = Field(..., description='Longitude in WGS84 format.', min_length=1, max_length=2048)
    y: str = Field(..., description='Latitude in WGS84 format.', min_length=1, max_length=2048)
    domain: str | None = Field(None, description='Used to identify your service in the Addressfinder Portal. Must be registered in the Portal.', min_length=1, max_length=2048)
    max: int | None = Field(None, description='Maximum number of results to return (1–100).', ge=1, le=100, strict=True)

class VerifyEmailConfig(_Input):
    """Email Verification API: /email/v1/verification."""
    operation: Literal['verify_email'] = Field('verify_email', title='Verify Email', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., description='The email to be verified.', min_length=1, max_length=2048)
    domain: str | None = Field(None, description='Used to identify which of your services is calling the API for activity monitoring purposes. This domain needs to be registered in the portal.', min_length=1, max_length=2048)
    features: str | None = Field(None, description='A comma-separated list of parameters that controls the methods of verification to be completed. This will impact the query processing time and data returned in the response.\nOptions:\n  * `domain` checks if the domain is configured to receive emails;\n  * `connection` checks if the email account exists;\n  * `provider` checks and returns the email service provider;\n  * `format` validates the syntax of the email address only. When\n    `format` is the only feature, no domain, connection or provider\n    checks are performed, so the response is returned faster and\n    `is_verified` reflects the format check alone. The\n    `is_disposable`, `is_role`, `is_public` and `is_catch_all`\n    attributes are returned as `null` because they are not\n    evaluated. Combining `format` with any other feature runs a\n    standard verification.', min_length=1, max_length=2048)

class VerifyPhoneConfig(_Input):
    """Phone Verification API: /phone/v1/verification."""
    operation: Literal['verify_phone'] = Field('verify_phone', title='Verify Phone', json_schema_extra={"ui:hidden": True})
    phone_number: str = Field(..., description='The phone number to be verified.', min_length=1, max_length=2048)
    domain: str | None = Field(None, description='Used to identify which of your services is calling the API for activity monitoring purposes. This domain needs to be registered in the portal.', min_length=1, max_length=2048)
    default_country_code: str = Field(..., description='The iso2 country code to be used by default when the phone number does not include a country calling code.', min_length=1, max_length=2048)
    mobile_only: bool | None = Field(None, description='Require that the supplied number is a mobile phone.', strict=True)
    timeout: float | None = Field(None, description='Maximum wait time permitted when verifying the number. If exceeded, will return a status of indeterminate.', strict=True, gt=0, le=60, allow_inf_nan=False)
    allowed_country_codes: str | None = Field(None, description='Require that the supplied phone number is registered in one of these supplied countries (comma separated using iso2 codes).', min_length=1, max_length=2048)
    verify_format_only: bool | None = Field(None, description='Set to `true` to validate the syntax and number range of the phone number only. The network check for a connection status is skipped, so `line_status` is not returned and `line_type` is derived from the number range alone.', strict=True)

class SearchInternationalAddressesConfig(_Input):
    """International Address Autocomplete API: /{country}/address/v2/autocomplete."""
    operation: Literal['search_international_addresses'] = Field('search_international_addresses', title='Search International Addresses', json_schema_extra={"ui:hidden": True})
    country: str = Field(..., description='ISO 3166 alpha-2 country code.', min_length=1, max_length=2048, pattern=r'^[a-z]{2}$')
    q: str = Field(..., description='The partial address being searched. Max length 200 characters.', min_length=1, max_length=200)
    domain: str | None = Field(None, description='Used to identify in the Addressfinder Portal which of your services is calling the API for activity monitoring purposes. The domain needs to be registered in the Portal.', min_length=1, max_length=2048)
    max: int | None = Field(None, description='The maximum number of results to return. Between 1 and 15 (inclusive).', ge=1, le=15, strict=True)

class GetInternationalAddressMetadataConfig(_Input):
    """International Address Metadata API: /{country}/address/v2/metadata."""
    operation: Literal['get_international_address_metadata'] = Field('get_international_address_metadata', title='Get International Address Metadata', json_schema_extra={"ui:hidden": True})
    country: str = Field(..., description='ISO 3166 alpha-2 country code.', min_length=1, max_length=2048, pattern=r'^[a-z]{2}$')
    id: str = Field(..., description='Unique address identifier obtained from the Address Autocomplete API.', min_length=1, max_length=2048)
    gps: Literal[0, 1] | None = Field(None, description='Include GPS coordinates in the results if available (0 or 1).')
    domain: str | None = Field(None, description='Used to identify in the Addressfinder Portal which of your services is calling the API for activity monitoring purposes. The domain needs to be registered in the Portal.', min_length=1, max_length=2048)


AddressfinderOperation = Annotated[Union[SearchAuAddressesConfig, GetAuAddressMetadataConfig, VerifyAuAddressConfig, SearchAuLocationsConfig, GetAuLocationMetadataConfig, SearchNzAddressesConfig, GetNzAddressMetadataConfig, VerifyNzAddressConfig, SearchNzLocationsConfig, GetNzLocationMetadataConfig, SearchNzPointsOfInterestConfig, GetNzPointOfInterestMetadataConfig, GetNzReverseGeocodeConfig, VerifyEmailConfig, VerifyPhoneConfig, SearchInternationalAddressesConfig, GetInternationalAddressMetadataConfig], Field(discriminator="operation")]


class AddressfinderFullConfig(NodeConfig[AddressfinderOperation, AddressfinderAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'search_au_addresses': '/au/address/autocomplete', 'get_au_address_metadata': '/au/address/metadata', 'verify_au_address': '/au/address/v2/verification', 'search_au_locations': '/au/location/autocomplete', 'get_au_location_metadata': '/au/location/metadata', 'search_nz_addresses': '/nz/address/autocomplete', 'get_nz_address_metadata': '/nz/address/metadata', 'verify_nz_address': '/nz/address/verification', 'search_nz_locations': '/nz/location/autocomplete', 'get_nz_location_metadata': '/nz/location/metadata', 'search_nz_points_of_interest': '/nz/points_of_interest/autocomplete', 'get_nz_point_of_interest_metadata': '/nz/points_of_interest/metadata', 'get_nz_reverse_geocode': '/nz/address/reverse_geocode', 'verify_email': '/email/v1/verification', 'verify_phone': '/phone/v1/verification', 'search_international_addresses': '/{country}/address/v2/autocomplete', 'get_international_address_metadata': '/{country}/address/v2/metadata'}


def _redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.api_key, credential.api_secret):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, dict):
        return {_redact(k, credential): _redact(v, credential) for k, v in value.items()}
    return value


class AddressfinderNode(WorkflowNode):
    integration_type = "automation-addressfinder"
    connection_evidence = ConnectionEvidence(noun="Australian address search", operation="search_au_addresses", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return AddressfinderFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Addressfinder API key and secret")
        credential, config = self.config.credentials, self.config.config
        route = ROUTES[config.operation]
        params = config.model_dump(exclude_none=True, exclude={"operation", "country"})
        if "{country}" in route:
            route = route.replace("{country}", config.country)
        params.update(key=credential.api_key, format="json")
        params = {k: ("true" if v else "false") if isinstance(v, bool) else v for k, v in params.items()}
        output = {"operation": config.operation, "identity_verified": False}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                async with client.stream("GET", BASE + route, params=params,
                        headers={"Authorization": credential.api_secret, "Accept": "application/json"}) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 2_000_000:
                            raise ValueError("Addressfinder response exceeds the supported size")
                    media = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if media != "application/json":
                        raise ValueError("Expected JSON from Addressfinder")
                    body = json.loads(raw)
                    if not isinstance(body, dict):
                        raise ValueError("Expected an Addressfinder response object")
                    if response.status_code != 200 or body.get("success") is False or body.get("error") or body.get("errors"):
                        message = body.get("message") or body.get("error") or "Addressfinder did not complete this request"
                        if not isinstance(message, str):
                            message = "Addressfinder did not complete this request"
                        result = {**output, "status": "error", "http_status": response.status_code, "error": message[:2000]}
                    elif body.get("success") is not True:
                        raise ValueError("Addressfinder did not confirm request success")
                    elif "autocomplete" in route or "reverse_geocode" in route:
                        if not isinstance(body.get("completions"), list) or any(not isinstance(row, dict) for row in body["completions"]):
                            raise ValueError("Expected Addressfinder completions")
                        result = {**output, "status": "success", "data": body}
                    else:
                        result = {**output, "status": "success", "data": body}
        except (ValueError, UnicodeError, httpx.HTTPError, SSRFError):
            result = {**output, "status": "error", "error": "Addressfinder request or response could not be verified"}
        result = _redact(result, credential)
        await self.emit(result)
        return result
