"""Foursquare Places API (2025-06-17), authenticated with a Service API Key.

Each operation makes one request to its published endpoint. Suggested changes
are moderation submissions, not a claim that the canonical place was changed.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://places-api.foursquare.com"
API_VERSION = "2025-06-17"


class FoursquareServiceKey(BaseModel):
    model_config = ConfigDict(
        title="Foursquare Service API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://foursquare.com/developers/",
            "x-credential-instructions": "In your Foursquare Developer project, open Settings and generate a Service API Key. Paste that key here without the Bearer prefix. Use a key with Places API access. NoClick checks the key by reading suggested edits submitted using it; this does not verify a personal Foursquare identity.",
        },
    )
    credential_type: Literal["foursquare_service_key"] = Field("foursquare_service_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=8192, title="Service API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="Service API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Service API Key, without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class AutocompleteConfig(_Input):
    """Autocomplete."""
    operation: Literal['autocomplete'] = Field('autocomplete', json_schema_extra={"ui:hidden": True})
    query: str = Field(..., description='A search term to be applied against titles. Must be at least 3 characters long.', min_length=1, max_length=10000)
    ll: str | None = Field(None, description='The latitude/longitude around which you wish to retrieve place information. Specified as latitude,longitude (e.g., ll=41.8781,-87.6298). If you do not specify ll, the server will attempt to retrieve the IP address from the request, and geolocate that IP address.', min_length=1, max_length=10000)
    radius: int | None = Field(None, description='Defines the distance (in meters) within which to return place results. Setting a radius biases the results to the indicated area, but may not fully restrict results to that specified area. If not provided, default radius is set to 5000 meters.')
    types: str | None = Field(None, description='The types of results to return; any combination of place, search, and/or geo.If no types are specified, all types will be returned.', min_length=1, max_length=10000)
    bias: str | None = Field(None, description='Bias the autocomplete results by a specific type; one of place, search, or geo.', min_length=1, max_length=10000)
    session_token: str | None = Field(None, description="A user-generated token to to group the user's query and the user's selected result into a discrete session for billing purposes. Learn more about [session tokens](https://docs.foursquare.com/reference/session-tokens).  *If the session_token parameter is omitted, the session is charged per keystroke/request.*", min_length=1, max_length=10000)
    limit: int | None = Field(None, description='The number of results to return, up to 50. Defaults to 10.', ge=1, le=50)

class SearchPlacesConfig(_Input):
    """Place Search."""
    operation: Literal['search_places'] = Field('search_places', json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description='A string to be matched against all content for this place, including but not limited to venue name, category, telephone number, taste, and tips.', min_length=1, max_length=10000)
    ll: str | None = Field(None, description='The latitude/longitude around which to retrieve place information. This must be specified as latitude,longitude (e.g., ll=41.8781,-87.6298).', min_length=1, max_length=10000)
    radius: int | None = Field(None, description='Sets a radius distance (in meters) used to define an area to bias search results. The maximum allowed radius is 100,000 meters. Radius can be used in combination with ll or ip biased geolocation only. By using radius, global search results will be omitted. If not provided, default radius applied is 22000 meters.', ge=0, le=100000)
    fsq_category_ids: str | None = Field(None, description='Filters the response and returns FSQ Places matching the specified categories. Supports multiple Category IDs, separated by commas.  For a complete list of Foursquare Category IDs, refer to the Category Taxonomy page.', min_length=1, max_length=10000)
    fsq_chain_ids: str | None = Field(None, description='Filters the response and returns FSQ Places matching the specified chains. Supports multiple chain IDs, separated by commas.  For more information on Foursquare Chain IDs, refer to the Chains page.', min_length=1, max_length=10000)
    exclude_fsq_chain_ids: str | None = Field(None, description='Filters the response and returns FSQ Places not matching any of the specified chains. Supports multiple chain IDs, separated by commas. Cannot be used in conjunction with exclude_all_chains.  For more information on Foursquare Chain IDs, refer to the Chains page.', min_length=1, max_length=10000)
    exclude_all_chains: bool | None = Field(None, description='Filters the response by only returning FSQ Places that are not known to be part of any chain. Cannot be used in conjunction with exclude_chains.')
    fields: str | None = Field(None, description='Indicate which fields to return in the response, separated by commas. If no fields are specified, all Pro Fields are returned by default.   For a complete list of returnable fields, refer to the Places Response Fields page.', min_length=1, max_length=10000)
    min_price: int | None = Field(None, description='Restricts results to only those places within the specified price range. Valid values range between 1 (most affordable) to 4 (most expensive), inclusive.', ge=1, le=4)
    max_price: int | None = Field(None, description='Restricts results to only those places within the specified price range. Valid values range between 1 (most affordable) to 4 (most expensive), inclusive.', ge=1, le=4)
    open_at: str | None = Field(None, description='Support local day and local time requests through this parameter. To be specified as DOWTHHMM (e.g., 1T2130), where DOW is the day number 1-7 (Monday = 1, Sunday = 7) and time is in 24 hour format.  Places that do not have opening hours will not be returned if this parameter is specified. Cannot be specified in conjunction with `open_now`.', min_length=1, max_length=10000)
    open_now: bool | None = Field(None, description='Restricts results to only those places that are open now.  Places that do not have opening hours will not be returned if this parameter is specified. Cannot be specified in conjunction with `open_at`.')
    tel_format: Literal['NATIONAL', 'E164'] | None = Field(None, description='Specifies the format of the returned telephone number.', min_length=1, max_length=10000)
    ne: str | None = Field(None, description='The latitude/longitude representing the north/east points of a rectangle. Must be used with sw parameter to specify a rectangular search box. Global search results will be omitted.', min_length=1, max_length=10000)
    sw: str | None = Field(None, description='The latitude/longitude representing the south/west points of a rectangle. Must be used with ne parameter to specify a rectangular search box. Global search results will be omitted.', min_length=1, max_length=10000)
    near: str | None = Field(None, description='A string naming a locality in the world (e.g., "Chicago, IL"). If the value is not geocodable, returns an error. Global search results will be omitted.', min_length=1, max_length=10000)
    sort: Literal['RELEVANCE', 'RATING', 'DISTANCE', 'POPULARITY'] | None = Field(None, description='Specifies the order in which results are listed.', min_length=1, max_length=10000)
    limit: int | None = Field(None, description='The number of results to return, up to 50. Defaults to 10.', ge=1, le=50)

class GetPlaceConfig(_Input):
    """Get Place Details."""
    operation: Literal['get_place'] = Field('get_place', json_schema_extra={"ui:hidden": True})
    fsq_place_id: str = Field(..., description="A unique string identifier for a FSQ Place (formerly known as Venue ID). E.g., Foursquare HQ's fsq_place_id = 5a187743ccad6b307315e6fe", min_length=1, max_length=10000)
    fields: str | None = Field(None, description='Indicate which fields to return in the response, separated by commas. If no fields are specified, all Pro Fields are returned by default.   For a complete list of returnable fields, refer to the Places Response Fields page.', min_length=1, max_length=10000)

class GetPlaceTipsConfig(_Input):
    """Get Place Tips."""
    operation: Literal['get_place_tips'] = Field('get_place_tips', json_schema_extra={"ui:hidden": True})
    fsq_place_id: str = Field(..., description="A unique string identifier for a FSQ Place (formerly known as Venue ID). E.g., Foursquare HQ's fsq_place_id = 5a187743ccad6b307315e6fe", min_length=1, max_length=10000)
    limit: int | None = Field(None, description='The specified number of tips per page. Returns 10 tips by default, up to a maximum number of 50.', ge=1, le=50)
    fields: str | None = Field(None, description='Indicate which fields to return in the response, separated by commas. Supported fields are: fsq_tip_id - The ID of the tip to be returned. created_at - The timestamp indicating when the tip was created; UNIX timestamp in seconds since Epoch. text - The text of the returned tip. lang - The language of the returned tip. url - The URL associated with the returned tip. agree_count - The count of users who have agreed with the returned tip. disagree_count - The count of users who have disagreed with the returned tip. photo - The ID of the photo asociated with the returned tip.Default fields if this param is omitted are "fsq_tip_id", "created_at...', min_length=1, max_length=10000)
    sort: Literal['POPULAR', 'NEWEST'] | None = Field(None, description='Specifies the order in which results are listed. Possible values are:popular (default) - sorts results based on their popularity among Foursquare usersnewest - sorts results from most recently added to least recently added', min_length=1, max_length=10000)

class GetPlacePhotosConfig(_Input):
    """Get Place Photos."""
    operation: Literal['get_place_photos'] = Field('get_place_photos', json_schema_extra={"ui:hidden": True})
    fsq_place_id: str = Field(..., description="A unique string identifier for a FSQ Place (formerly known as Venue ID). E.g., Foursquare HQ's fsq_place_id = 5a187743ccad6b307315e6fe", min_length=1, max_length=10000)
    limit: int | None = Field(None, description='The specified number of photos per page. Returns 10 photos by default, up to a maximum number of 50.', le=50)
    sort: Literal['POPULAR', 'NEWEST'] | None = Field(None, description='Specifies the order in which results are listed. Possible values are:popular (default) - sorts results based on their popularity among Foursquare usersnewest - sorts results from most recently added to least recently added', min_length=1, max_length=10000)
    classifications: str | None = Field(None, description='Restricts the results to photos matching the specified classifications, separated by a comma. Possible values are:exhibitfacilitiesfood_or_drinkindoor_facilities_and_classroomsindoor_generalindoor_or_ambiencelogosmenumonuments_and_landmark_buildingsoutdooroutdoor_building_and_groundsoutdoor_building_exterioroutdoor_groundsoutdoor_or_storefrontoutdoor_sceneryproduct', min_length=1, max_length=10000)

class SuggestMergeConfig(_Input):
    """Merge Places."""
    operation: Literal['suggest_merge'] = Field('suggest_merge', json_schema_extra={"ui:hidden": True})
    fsq_place_id: str = Field(..., description="A unique string identifier for a FSQ Place (formerly known as Venue ID). E.g., Foursquare HQ's fsq_place_id = 5a187743ccad6b307315e6fe.", min_length=1, max_length=10000)
    dry_run: bool = Field(False, description='Preview only when true; false submits the suggestion for moderation.')
    duplicate_fsq_place_ids: str = Field(..., description='A list of string identifiers that represent the same place as the given fsq_place_id.', min_length=1, max_length=10000)

class SuggestEditConfig(_Input):
    """Edit a Place."""
    operation: Literal['suggest_edit'] = Field('suggest_edit', json_schema_extra={"ui:hidden": True})
    fsq_place_id: str = Field(..., description="A unique string identifier for a FSQ Place (formerly known as Venue ID). E.g., Foursquare HQ's fsq_id = 5a187743ccad6b307315e6fe.", min_length=1, max_length=10000)
    dry_run: bool = Field(False, description='Preview only when true; false submits the suggestion for moderation.')
    latitude: float | None = Field(None, description='The proposed new value for the latitude at which the place should be located (e.g., 41.8781).')
    longitude: float | None = Field(None, description='The proposed new value for the longitude at which the place should be located (e.g., -87.6298).')
    menu: str | None = Field(None, description='The proposed new value for the url where the menu of the place can be found.', min_length=1, max_length=10000)
    facebook_url: str | None = Field(None, description="The proposed new value for the url for this place's Facebook Page.", min_length=1, max_length=10000)
    parent_id: str | None = Field(None, description='The proposed new value if the place is a subvenue of a larger place (such as a coffee shop within a Target), set this attribute to the ID of the parent place. Set to "" to remove parent.', min_length=1, max_length=10000)
    is_private_place: bool | None = Field(None, description='The proposed new value for whether the place is a private place. If true, the place will be marked as private. Otherwise, it will be marked as public.')
    hours: str | None = Field(None, description="The proposed new value for the hours for the venue, as a semi-colon separated list of open segments and named segments (e.g., brunch or happy hour). Open segments are formatted as day,start,end. Named segments additionally have a label, formatted as day,start,end,label. Days are formatted as integers with Monday = 1,...,Sunday = 7. Start and End are formatted as [+]HHMM format. Use 24 hour format (no colon), prefix with 0 for HH or MM less than 10. Use '+' prefix, i.e., +0230 to represent 2:30 am past midnight into the following day. To indicate that a venue is open 24/7, send this value with the hours attribute: 1,0000,2400;2,0000,2400;3,...", min_length=1, max_length=10000)
    name: str | None = Field(None, description='The proposed new value for the name of the place.', min_length=1, max_length=10000)
    description: str | None = Field(None, description='The proposed new value for the freeform description of the place, up to 300 characters.', min_length=1, max_length=10000)
    tel: str | None = Field(None, description='The proposed new value for the phone number of the place.', min_length=1, max_length=10000)
    instagram: str | None = Field(None, description='The proposed new value for the instagram handle of the place.', min_length=1, max_length=10000)
    twitter: str | None = Field(None, description='The proposed new value for the twitter handle of the place.', min_length=1, max_length=10000)
    website: str | None = Field(None, description='The proposed new value for the url of the homepage of the place.', min_length=1, max_length=10000)
    address: str | None = Field(None, description='The proposed new value for the address of the place.', min_length=1, max_length=10000)
    locality: str | None = Field(None, description='The proposed new value for the name of the locality (city) where this place is.', min_length=1, max_length=10000)
    region: str | None = Field(None, description='The proposed new value for the nearest state or province to the place.', min_length=1, max_length=10000)
    postcode: str | None = Field(None, description='The proposed new value for the zip or postal code for the place.', min_length=1, max_length=10000)
    country_code: str | None = Field(None, description='The proposed new 2-digit country code where the place is located (e.g. US).', min_length=1, max_length=10000)
    add_attributes: str | None = Field(None, description='A comma-separated list of attribute keys to add or enable for the venue. Possible values are: {atm, reservations, offers_delivery, parking, outdoor_seating, restroom, credit_cards, wifi}.', min_length=1, max_length=10000)
    remove_attributes: str | None = Field(None, description='A comma-separated list of attribute keys to remove or disable from the venue. Possible values are: {atm, reservations, offers_delivery, parking, outdoor_seating, restroom, credit_cards, wifi}.', min_length=1, max_length=10000)
    add_fsq_category_ids: str | None = Field(None, description='Add category IDs. Supports multiple Category IDs, separated by commas.  For a complete list of Foursquare Category IDs, refer to the Category Taxonomy page. [This endpoint prefers the 5-integer style id, but can accept the BSON style id]', min_length=1, max_length=10000)
    remove_fsq_category_ids: str | None = Field(None, description='Remove category IDs. Supports multiple Category IDs, separated by commas.  For a complete list of Foursquare Category IDs, refer to the Category Taxonomy page. [This endpoint prefers the 5-integer style id, but can accept the BSON style id]', min_length=1, max_length=10000)
    primary_fsq_category_id: str | None = Field(None, description='Change the primary category ID  For a complete list of Foursquare Category IDs, refer to the Category Taxonomy page. [This endpoint prefers the 5-integer style id, but can accept the BSON style id]', min_length=1, max_length=10000)
    add_fsq_chain_ids: str | None = Field(None, description='Add chain IDs.', min_length=1, max_length=10000)
    remove_fsq_chain_ids: str | None = Field(None, description='Remove Foursquare chain IDs.', min_length=1, max_length=10000)
    primary_fsq_chain_id: str | None = Field(None, description='Change the primary chain ID.', min_length=1, max_length=10000)
    unset_fields: str | None = Field(None, description='Fields to unset. Supports multiple fields, separated by commas. Possible values are: menu (default)facebook_urldescriptionaddressteltwitterwebsitefsq_chain_idshours', min_length=1, max_length=10000)

class SuggestRemovalConfig(_Input):
    """Remove a Place."""
    operation: Literal['suggest_removal'] = Field('suggest_removal', json_schema_extra={"ui:hidden": True})
    fsq_place_id: str = Field(..., description="A unique string identifier for a FSQ Place (formerly known as Venue ID). E.g., Foursquare HQ's fsq_place_id = 5a187743ccad6b307315e6fe.", min_length=1, max_length=10000)
    dry_run: bool = Field(False, description='Preview only when true; false submits the suggestion for moderation.')
    reason: Literal['CLOSED', 'DOESNT_EXIST', 'INAPPROPRIATE', 'NOT_CLOSED', 'OTHER', 'PRIVATE'] = Field(..., description='Reason for removal. Possible values are:closeddoesnt_existinappropriatenot_closedprivate', min_length=1, max_length=10000)
    comment: str | None = Field(None, description='A comment describing the removal request.', min_length=1, max_length=10000)

class FlagPlaceFieldsConfig(_Input):
    """Flag a Place."""
    operation: Literal['flag_place_fields'] = Field('flag_place_fields', json_schema_extra={"ui:hidden": True})
    fsq_place_id: str = Field(..., description="A unique string identifier for a FSQ Place (formerly known as Venue ID). E.g., Foursquare HQ's fsq_place_id = 5a187743ccad6b307315e6fe.", min_length=1, max_length=10000)
    dry_run: bool = Field(False, description='Preview only when true; false submits the suggestion for moderation.')
    fields: str = Field(..., description='List of fields being flagged as incorrect. Possible values are:addresslatitudelongitudelocalitynametelpostcoderegionstatewebsiteplaceActions', min_length=1, max_length=10000)
    comment: str | None = Field(None, description='A comment describing the issue being flagged.', min_length=1, max_length=10000)

class SuggestPlaceConfig(_Input):
    """Suggest a New Place."""
    operation: Literal['suggest_place'] = Field('suggest_place', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='The proposed value for the name of the new place.', min_length=1, max_length=10000)
    categories: str | None = Field(None, description='Categories to search for. Supports multiple Category IDs, separated by commas.  For a complete list of Foursquare Category IDs, refer to the Category Taxonomy page.', min_length=1, max_length=10000)
    address: str | None = Field(None, description='The proposed value for the address of the new place.', min_length=1, max_length=10000)
    locality: str | None = Field(None, description='The proposed value for the name of the locality (city) where this new place is.', min_length=1, max_length=10000)
    region: str | None = Field(None, description='The proposed value for the nearest state or province to the new place.', min_length=1, max_length=10000)
    postcode: str | None = Field(None, description='The value for the zip or postal code for the new place.', min_length=1, max_length=10000)
    country_code: str | None = Field(None, description='The 2-digit country code where the place is located (e.g. US).', min_length=1, max_length=10000)
    latitude: float | None = Field(None, description='The proposed value for the latitude at which the new place should be located (e.g., 41.8781).')
    longitude: float | None = Field(None, description='The proposed value for the longitude at which the new place should be located (e.g., -87.6298).')
    chains: str | None = Field(None, description='The proposed chain ids to be assosciated with this new place', min_length=1, max_length=10000)
    parent_id: str | None = Field(None, description='The proposed value if the new place is a subvenue of a larger place (such as a coffee shop within a Target), set this attribute to the ID of the parent place.', min_length=1, max_length=10000)
    is_private_place: bool | None = Field(None, description='If true, the new place will be marked as private.')
    tel: str | None = Field(None, description='The proposed new value for the phone number of the place.', min_length=1, max_length=10000)
    website: str | None = Field(None, description='The proposed value for the url of the homepage of the new place.', min_length=1, max_length=10000)
    email: str | None = Field(None, description='The proposed value for the email address for this new place', min_length=1, max_length=10000)
    facebook_url: str | None = Field(None, description="The proposed value for the url for this new place's Facebook Page.", min_length=1, max_length=10000)
    instagram: str | None = Field(None, description='The proposed value for the instagram handle for this new place', min_length=1, max_length=10000)
    twitter: str | None = Field(None, description='The proposed value for the twitter handle of the new place.', min_length=1, max_length=10000)
    hours: str | None = Field(None, description="The proposed value for the hours for the new venue, as a semi-colon separated list of open segments and named segments (e.g., brunch or happy hour). Open segments are formatted as day,start,end. Named segments additionally have a label, formatted as day,start,end,label. Days are formatted as integers with Monday = 1,...,Sunday = 7. Start and End are formatted as [+]HHMM format. Use 24 hour format (no colon), prefix with 0 for HH or MM less than 10. Use '+' prefix, i.e., +0230 to represent 2:30 am past midnight into the following day. To indicate that a venue is open 24/7, send this value with the hours attribute: 1,0000,2400;2,0000,2400;3,...", min_length=1, max_length=10000)
    attributes: str | None = Field(None, description='Comma seperated list that represents the attributes that the new place has. Possible values are: {atm, reservation, offers_delivery, parking, outdoor_seating, restroom, credit_cards, wifi}.', min_length=1, max_length=10000)
    dry_run: bool = Field(False, description='Preview only when true; false submits the suggestion for moderation.')

class GetSuggestionStatusConfig(_Input):
    """Get Suggestion Status."""
    operation: Literal['get_suggestion_status'] = Field('get_suggestion_status', json_schema_extra={"ui:hidden": True})
    suggested_edit_ids: str | None = Field(None, description='A comma seperated list of suggested edit IDs. If specified, shows only suggested edits with these IDs. If not specified, returns all edits suggested using the calling service token.', min_length=1, max_length=10000)
    limit: int | None = Field(None, description='The specified number of suggested edits per page. Returns 10 suggested edits by default, up to a maximum number of 50.', ge=0, le=50)

class GetPlacesForReviewConfig(_Input):
    """Get Places With Pending Suggested Edits."""
    operation: Literal['get_places_for_review'] = Field('get_places_for_review', json_schema_extra={"ui:hidden": True})
    near: str | None = Field(None, description='The name of the location to search near', min_length=1, max_length=10000)
    ne: str | None = Field(None, description='The north-east corner of the bounding box to search within', min_length=1, max_length=10000)
    sw: str | None = Field(None, description='The south-west corner of the bounding box to search within', min_length=1, max_length=10000)

class GetGeotaggingCandidatesConfig(_Input):
    """Find Geotagging Candidates."""
    operation: Literal['get_geotagging_candidates'] = Field('get_geotagging_candidates', json_schema_extra={"ui:hidden": True})
    fields: str | None = Field(None, description='Indicate which fields to return in the response, separated by commas. If no fields are specified, all Pro Fields are returned by default.   For a complete list of returnable fields, refer to the Places Response Fields page.', min_length=1, max_length=10000)
    ll: str | None = Field(None, description='The latitude/longitude around which to retrieve place information. This must be specified as latitude,longitude (e.g., ll=41.8781,-87.6298). If you do not specify ll, the server will attempt to retrieve the IP address from the request, and geolocate that IP address.', min_length=1, max_length=10000)
    hacc: float | None = Field(None, description='The estimated horizontal accuracy radius in meters of the user?s location at the 68th percentile confidence level as returned by the user?s cell phone OS.')
    altitude: float | None = Field(None, description='The altitude of the user?s location in meters above the World Geodetic System 1984 (WGS84) reference ellipsoid as returned by the user?s cell phone OS.')
    query: str | None = Field(None, description='A string to be matched against place name for candidates.', min_length=1, max_length=10000)
    limit: int | None = Field(None, description='The number of results to return, up to 50. Defaults to 10.', ge=1, le=50)

class ConfirmGeotaggingConfig(_Input):
    """Confirm Geotagging Candidate Selection."""
    operation: Literal['confirm_geotagging'] = Field('confirm_geotagging', json_schema_extra={"ui:hidden": True})
    request_id: str | None = Field(None, description='The request ID pulled from the header of the /geotagging/candidates request that generated the list of candidates shown to the user. The header key is X-Fsq-Request-Id.', min_length=1, max_length=10000)
    fsq_place_id: str | None = Field(None, description='The FSQ Place ID of the place which was selected by the user from the candidates list', min_length=1, max_length=10000)
    confirm_context: Literal['CurrentLocation', 'Nearby', 'Destination', 'Search'] | None = Field(None, description='Specify the use case for specified request. Options are: CurrentLocation, Nearby, Destination, Search', min_length=1, max_length=10000)
    delayed: bool | None = Field(None, description='')

class MatchPlaceConfig(_Input):
    """Place Match."""
    operation: Literal['match_place'] = Field('match_place', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Name of the place to match.', min_length=1, max_length=10000)
    address: str = Field(..., description='Street address of the place to match (e.g. 1060 W Addison St).', min_length=1, max_length=10000)
    city: str = Field(..., description='City, or Locality, where the place is located (e.g. Chicago).', min_length=1, max_length=10000)
    state: str | None = Field(None, description='State, or Region, where the place is located (e.g. Illinois).', min_length=1, max_length=10000)
    postal_code: str | None = Field(None, description='The postal code for the address where the place is located (e.g. 60613).', min_length=1, max_length=10000)
    cc: str = Field(..., description='The 2-digit country code where the place is located (e.g. US). Only English-speaking countries currently supported.', min_length=1, max_length=10000)
    ll: str | None = Field(None, description='The latitude/longitude of the venue location. This must be specified as latitude,longitude (e.g., ll=41.9484,-87.6553).', min_length=1, max_length=10000)
    fields: str | None = Field(None, description='Indicate which fields to return in the response, separated by commas. If no fields are specified, all Pro Fields are returned by default.   For a complete list of returnable fields, refer to the Places Response Fields page.', min_length=1, max_length=10000)

class ResolvePlaceConfig(_Input):
    """Place Resolve."""
    operation: Literal['resolve_place'] = Field('resolve_place', json_schema_extra={"ui:hidden": True})
    foreign_id: str = Field(..., description="The partner's place identifier from submitted source data.", min_length=1, max_length=10000)


FoursquareConfig = Annotated[Union[
    AutocompleteConfig,
    SearchPlacesConfig,
    GetPlaceConfig,
    GetPlaceTipsConfig,
    GetPlacePhotosConfig,
    SuggestMergeConfig,
    SuggestEditConfig,
    SuggestRemovalConfig,
    FlagPlaceFieldsConfig,
    SuggestPlaceConfig,
    GetSuggestionStatusConfig,
    GetPlacesForReviewConfig,
    GetGeotaggingCandidatesConfig,
    ConfirmGeotaggingConfig,
    MatchPlaceConfig,
    ResolvePlaceConfig,
], Field(discriminator="operation")]


class FoursquareNodeConfig(NodeConfig[FoursquareConfig, FoursquareServiceKey]):
    pass


ROUTES = {'autocomplete': ('GET', '/autocomplete'), 'search_places': ('GET', '/places/search'), 'get_place': ('GET', '/places/{fsq_place_id}'), 'get_place_tips': ('GET', '/places/{fsq_place_id}/tips'), 'get_place_photos': ('GET', '/places/{fsq_place_id}/photos'), 'suggest_merge': ('POST', '/places/{fsq_place_id}/suggest/merge'), 'suggest_edit': ('POST', '/places/{fsq_place_id}/suggest/edit'), 'suggest_removal': ('POST', '/places/{fsq_place_id}/suggest/remove'), 'flag_place_fields': ('POST', '/places/{fsq_place_id}/suggest/flag'), 'suggest_place': ('POST', '/places/suggest/place'), 'get_suggestion_status': ('GET', '/places/suggest/status'), 'get_places_for_review': ('GET', '/places/suggest/review'), 'get_geotagging_candidates': ('GET', '/geotagging/candidates'), 'confirm_geotagging': ('POST', '/geotagging/confirm'), 'match_place': ('GET', '/places/match'), 'resolve_place': ('GET', '/places/resolve')}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class FoursquareNode(WorkflowNode):
    integration_type = "automation-foursquare"
    connection_evidence = ConnectionEvidence(
        noun="suggested edits", operation="get_suggestion_status",
        label_keys=("fsq_place_id", "id", "status"),
    )

    @classmethod
    def get_config_model(cls):
        return FoursquareNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Foursquare Service API Key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        params = config.model_dump(exclude={"operation"}, exclude_none=True)
        if "{fsq_place_id}" in path:
            place_id = params.pop("fsq_place_id")
            if place_id in {".", ".."} or "/" in place_id or "\\" in place_id:
                raise ValueError("Use a single Foursquare Place ID")
            path = path.replace("{fsq_place_id}", quote(place_id, safe=""))
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(
                method, BASE_URL + path, params=params,
                headers={"Authorization": "Bearer " + secret,
                         "X-Places-Api-Version": API_VERSION, "Accept": "application/json"},
            )
        if not 200 <= response.status_code < 300:
            raise ValueError("Foursquare HTTP " + str(response.status_code) + ": " + _redact(response.text[:2000], secret))
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json" or len(response.content) > 8_000_000:
            raise ValueError("Expected a bounded JSON response from Foursquare")
        body = response.json()
        expected = list if config.operation in {"get_place_tips", "get_place_photos"} else dict
        if not isinstance(body, expected):
            raise ValueError("Unexpected Foursquare response shape")
        result = {"data": body, "request_id": response.headers.get("X-Fsq-Request-Id")}
        # Preserve provider errors and moderation statuses, including partial submissions.
        # A suggestion acknowledgement never establishes that the place itself changed.
        if isinstance(body, dict) and (body.get("error") or body.get("errors")):
            result.update(status="error", error=body.get("error") or body["errors"])
        if config.operation == "get_suggestion_status":
            result["items"] = body.get("suggested_edits", [])
        return _redact(result, secret)
