"""Melo (Stream Estate) real-estate data and saved-search automation.

Pinned contract: https://docs.stream.estate/api-reference/openapi.json, 1.0.0.
Each operation issues one request; collection operations return one page.
"""
from __future__ import annotations
from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MeloAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Melo API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://stream.estate/console",
            "x-credential-instructions": "In your Melo (Stream Estate) console, open API Keys and create an API key. Paste the key here. NoClick checks the connection by listing your saved searches.",
        })
    credential_type: Literal["melo_api_key"] = Field("melo_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(ch.isspace() for ch in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class MeloListPropertiesConfig(_Input):
    """List properties."""
    operation: Literal['list_properties'] = Field('list_properties', json_schema_extra={"ui:hidden": True})
    bedroomMin: int | None = Field(None, description='Minimum number of bedrooms in the property.')
    bedroomMax: int | None = Field(None, description='Maximum number of bedrooms in the property.')
    budgetMin: float | None = Field(None, description='Minimum budget for the property.')
    budgetMax: float | None = Field(None, description='Maximum budget for the property.')
    fromDate: datetime | None = Field(None, description='Date from which the property is created — inclusive.')
    toDate: datetime | None = Field(None, description='Date until which the property is created — inclusive. Example: `toDate=2021-05-07 12:42:42`')
    fromUpdatedAt: datetime | None = Field(None, description='Date from which the property is updated — inclusive.')
    toUpdatedAt: datetime | None = Field(None, description='Date until which the property is updated — inclusive.')
    furnished: bool | None = Field(None, description='Filter for furnished properties.')
    includedCities: list[str] | None = Field(None, description='Located in given cities. Example: `includedCities[]=/cities/30953`. Use the location autocomplete endpoint to get the desired city IRIs.')
    includedDepartments: list[str] | None = Field(None, description='Located in given departments. Example: `includedDepartments[]=/departments/77`. Use the location autocomplete endpoint to get the desired department IRIs.')
    includedZipcodes: list[str] | None = Field(None, description='Located in given zipcodes. Example: `includedZipcodes[]=75017&includedZipcodes[]=75018`')
    lat: float | None = Field(None, description='Latitude. Will work if latitude exists in the property. Example: `lat=48.864716`', ge=-90, le=90)
    lon: float | None = Field(None, description='Longitude. Will work if longitude exists in the property. Example: `lon=2.349014`', ge=-180, le=180)
    radius: float | None = Field(None, description='Distance expressed in kilometers. Will work if latitude & longitude parameters are also set. Example: `radius=20`, `radius=0.5`', gt=0)
    propertyTypes: list[Literal[0, 1, 2, 3, 4, 5, 6]] | None = Field(None, description='Type of property. Apartment `0`, House `1`, Building `2`, Parking `3`, Office `4`, Land `5`, Shop `6`. Example: `propertyTypes[]=0&propertyTypes[]=1`')
    publisherTypes: list[Literal[0, 1]] | None = Field(None, description='Type of publisher. Individual `0`, Professional `1`.')
    roomMin: int | None = Field(None, description='Minimum rooms of the property.')
    roomMax: int | None = Field(None, description='Maximum rooms of the property.')
    surfaceMin: float | None = Field(None, description='Greater than or equal to given surface.')
    surfaceMax: float | None = Field(None, description='Lower than or equal to given surface.')
    transactionType: Literal[0, 1] | None = Field(None, description='Type of transaction. Sell `0`, Rent `1`.')
    withCoherentPrice: bool | None = Field(None, description='Price coherence filter. `true` returns properties whose price passes our coherence checks; `false` returns properties flagged as incoherent — both also include properties whose price has not been assessed. Set to `null` (or send an empty value) to disable filtering. If omitted, defaults to `true`.')
    withVirtualTour: bool | None = Field(None, description='Having a virtual tour video link.')
    expired: bool | None = Field(None, description="Whether to show properties that are expired. A property is considered expired when all its adverts are expired. Default is `null` which returns all properties no matter if they're expired or not.")
    page: int | None = Field(None, description='The collection page number.', ge=1)
    itemsPerPage: int | None = Field(None, description='The number of items per page. Max is `30`.', ge=1, le=30)

class MeloGetPropertyConfig(_Input):
    """Get a property."""
    operation: Literal['get_property'] = Field('get_property', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='UUID of the selected property')

class MeloListSimilarPropertiesConfig(_Input):
    """List similar properties."""
    operation: Literal['list_similar_properties'] = Field('list_similar_properties', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='UUID of the selected property')
    fromDate: datetime | None = Field(None, description='Date from which the property is created — inclusive.')
    order_createdAt: Literal['asc', 'desc'] | None = Field(None, description='Order properties by creation date.', alias='order[createdAt]', max_length=4096)
    order_updatedAt: Literal['asc', 'desc'] | None = Field(None, description='Order properties by update date.', alias='order[updatedAt]', max_length=4096)
    order_pricePerMeter: Literal['asc', 'desc'] | None = Field(None, description='Order properties by price per meter.', alias='order[pricePerMeter]', max_length=4096)
    order_price: Literal['asc', 'desc'] | None = Field(None, description='Order properties by price.', alias='order[price]', max_length=4096)
    order_surface: Literal['asc', 'desc'] | None = Field(None, description='Order properties by surface.', alias='order[surface]', max_length=4096)
    page: int | None = Field(None, description='The collection page number.', ge=1)
    itemsPerPage: int | None = Field(None, description='The number of items per page. Max is `30`.', ge=1, le=30)

class MeloGetPricePerMeterConfig(_Input):
    """Price per meter evolution."""
    operation: Literal['get_price_per_meter'] = Field('get_price_per_meter', json_schema_extra={"ui:hidden": True})
    aggregationInterval: Literal['month', 'year'] | None = Field(None, description='Date histogram granularity for time series.', max_length=4096)
    bedroomMin: int | None = Field(None, description='Minimum number of bedrooms in the property.')
    bedroomMax: int | None = Field(None, description='Maximum number of bedrooms in the property.')
    budgetMin: float | None = Field(None, description='Minimum budget for the property.')
    budgetMax: float | None = Field(None, description='Maximum budget for the property.')
    fromDate: datetime | None = Field(None, description='Date from which the property is created — inclusive.')
    toDate: datetime | None = Field(None, description='Date until which the property is created — inclusive. Example: `toDate=2021-05-07 12:42:42`')
    fromUpdatedAt: datetime | None = Field(None, description='Date from which the property is updated — inclusive.')
    toUpdatedAt: datetime | None = Field(None, description='Date until which the property is updated — inclusive.')
    furnished: bool | None = Field(None, description='Filter for furnished properties.')
    includedCities: list[str] | None = Field(None, description='Located in given cities. Example: `includedCities[]=/cities/30953`. Use the location autocomplete endpoint to get the desired city IRIs.')
    includedDepartments: list[str] | None = Field(None, description='Located in given departments. Example: `includedDepartments[]=/departments/77`. Use the location autocomplete endpoint to get the desired department IRIs.')
    includedZipcodes: list[str] | None = Field(None, description='Located in given zipcodes. Example: `includedZipcodes[]=75017&includedZipcodes[]=75018`')
    lat: float | None = Field(None, description='Latitude. Will work if latitude exists in the property. Example: `lat=48.864716`', ge=-90, le=90)
    lon: float | None = Field(None, description='Longitude. Will work if longitude exists in the property. Example: `lon=2.349014`', ge=-180, le=180)
    radius: float | None = Field(None, description='Distance expressed in kilometers. Will work if latitude & longitude parameters are also set. Example: `radius=20`, `radius=0.5`', gt=0)
    propertyTypes: list[Literal[0, 1, 2, 3, 4, 5, 6]] | None = Field(None, description='Type of property. Apartment `0`, House `1`, Building `2`, Parking `3`, Office `4`, Land `5`, Shop `6`. Example: `propertyTypes[]=0&propertyTypes[]=1`')
    publisherTypes: list[Literal[0, 1]] | None = Field(None, description='Type of publisher. Individual `0`, Professional `1`.')
    roomMin: int | None = Field(None, description='Minimum rooms of the property.')
    roomMax: int | None = Field(None, description='Maximum rooms of the property.')
    surfaceMin: float | None = Field(None, description='Greater than or equal to given surface.')
    surfaceMax: float | None = Field(None, description='Lower than or equal to given surface.')
    transactionType: Literal[0, 1] | None = Field(None, description='Type of transaction. Sell `0`, Rent `1`.')
    withCoherentPrice: bool | None = Field(None, description='Price coherence filter. `true` returns properties whose price passes our coherence checks; `false` returns properties flagged as incoherent — both also include properties whose price has not been assessed. Set to `null` (or send an empty value) to disable filtering. If omitted, defaults to `true`.')
    withVirtualTour: bool | None = Field(None, description='Having a virtual tour video link.')
    expired: bool | None = Field(None, description='Filter for expired properties.')
    page: int | None = Field(None, description='The collection page number.', ge=1)
    itemsPerPage: int | None = Field(None, description='The number of items per page. Max is `30`.', ge=1, le=30)

class MeloListPointsOfInterestConfig(_Input):
    """Points of interest."""
    operation: Literal['list_points_of_interest'] = Field('list_points_of_interest', json_schema_extra={"ui:hidden": True})
    facilities: list[Literal['kindergarten', 'school', 'restaurant', 'hospital', 'parking']] = Field(..., description='Category of points of interest. Current available categories are `kindergarten`, `school`, `restaurant`, `hospital`, `parking`. Example: `facilities[]=kindergarten&facilities[]=school`', min_length=1)
    lat: float = Field(..., description='Latitude.', ge=-90, le=90)
    lon: float = Field(..., description='Longitude.', ge=-180, le=180)
    radius: float = Field(..., description='Distance expressed in kilometers.', gt=0)

class MeloListLocationsConfig(_Input):
    """Location autocomplete."""
    operation: Literal['list_locations'] = Field('list_locations', json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description='Query term to perform search.', max_length=4096)
    excludedCitiesIds: list[str] | None = Field(None, description='Exclude cities using their IRI.')
    excludedDepartmentsIds: list[str] | None = Field(None, description='Exclude departments using their IRI.')

class MeloListCitiesConfig(_Input):
    """List cities."""
    operation: Literal['list_cities'] = Field('list_cities', json_schema_extra={"ui:hidden": True})
    excludeGroupedCities: bool | None = Field(None, description='Set to true to exclude cities that have grouped cities under them.')
    insee: str | None = Field(None, description='Filter by INSEE code.', max_length=4096)
    libelle: str | None = Field(None, description='Filter by city label/display name.', max_length=4096)
    name: str | None = Field(None, description='Filter by city name.', max_length=4096)
    order_name: Literal['asc', 'desc'] | None = Field(None, description='Sort by name.', alias='order[name]', max_length=4096)
    page: int | None = Field(None, description='The collection page number.', ge=1)
    zipcode: str | None = Field(None, description='Filter by zipcode.', max_length=4096)

class MeloListSearchesConfig(_Input):
    """List searches."""
    operation: Literal['list_searches'] = Field('list_searches', json_schema_extra={"ui:hidden": True})
    notificationEnabled: bool | None = Field(None, description='Filter searches which have notifications enabled or not.')
    order_title: Literal['asc', 'desc'] | None = Field(None, description='Order searches by title.', alias='order[title]', max_length=4096)
    page: int | None = Field(None, description='The collection page number.', ge=1)
    title: str | None = Field(None, description='Title of the created search.', max_length=4096)

class MeloGetSearchConfig(_Input):
    """Get a search."""
    operation: Literal['get_search'] = Field('get_search', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='UUID of the selected search')

class MeloCreateSearchConfig(_Input):
    """Create a search."""
    operation: Literal['create_search'] = Field('create_search', json_schema_extra={"ui:hidden": True})
    bedroomMin: int | None = Field(None, description='Minimum number of bedrooms in the property.')
    bedroomMax: int | None = Field(None, description='Maximum number of bedrooms in the property.')
    budgetMax: float | None = Field(None, description='Maximum budget for the property.')
    budgetMin: float | None = Field(None, description='Minimum budget for the property.')
    endpointRecipient: str | None = Field(None, description='HTTPS webhook that receives `match` payloads whenever a property satisfies the search. Requires `notificationEnabled=true`.', max_length=4096)
    eventEndpoint: str | None = Field(None, description='HTTPS webhook that receives advert `event` payloads (price changes, expirations, etc.). Requires `notificationEnabled=true` and at least one entry in `subscribedEvents`.', max_length=4096)
    furnished: bool | None = Field(None, description='Whether the property is furnished or not.')
    includedCities: list[str] | None = Field(None, description='Included cities. Use the location autocomplete endpoint to get the desired city IRIs.')
    includedDepartments: list[str] | None = Field(None, description='Included departments. Use the location autocomplete endpoint to get the desired department IRIs.')
    includedZipcodes: list[str] | None = Field(None, description='Included zipcodes.')
    lat: float | None = Field(None, description='Latitude of the center point used for radial filtering. Provide together with `lon`.', ge=-90, le=90)
    lon: float | None = Field(None, description='Longitude of the center point used for radial filtering. Provide together with `lat`.', ge=-180, le=180)
    notificationEnabled: bool | None = Field(None, description='Enables delivery of matches and events either by webhook (`endpointRecipient`, `eventEndpoint`) or by email (`notificationRecipient`).')
    notificationRecipient: str | None = Field(None, description='Email address that receives alert summaries when `notificationEnabled=true`.', max_length=4096)
    propertyTypes: list[Literal[0, 1, 2, 3, 4, 5, 6]] = Field(..., description='Type of property. Apartment `0`, House `1`, Building `2`, Parking `3`, Office `4`, Land `5`, Shop `6`.', min_length=1)
    publisherTypes: list[Literal[0, 1]] | None = Field(None, description='Type of publisher. Individual `0`, Professional `1`.')
    radius: float | None = Field(None, description='Distance in kilometers around the provided `lat`/`lon`.', gt=0)
    roomMin: int | None = Field(None, description='Minimum number of rooms.')
    roomMax: int | None = Field(None, description='Maximum number of rooms.')
    subscribedEvents: list[Literal['ad.update.price', 'ad.update.surface', 'ad.update.pictures', 'ad.update.expired', 'property.ad.create', 'property.ad.update']] | None = Field(None, description='Event codes you want to receive on the `eventEndpoint`.')
    surfaceMax: float | None = Field(None, description='Maximum property surface area.')
    surfaceMin: float | None = Field(None, description='Minimum property surface area.')
    title: str = Field(..., description='Title of the created search.', max_length=4096, min_length=1)
    transactionType: Literal[0, 1] = Field(..., description='Type of transaction. Sell `0`, Rent `1`.')
    withCoherentPrice: bool | None = Field(None, description='Price coherence filter. `true` returns adverts whose price passes our coherence checks; `false` returns adverts flagged as incoherent — both also include adverts whose price has not been assessed. Set to `null` (or send an empty value) to disable filtering. If omitted, defaults to `true`.')
    withVirtualTour: bool | None = Field(None, description='Whether the property includes a virtual tour.')

class MeloUpdateSearchConfig(_Input):
    """Update a search."""
    operation: Literal['update_search'] = Field('update_search', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='UUID of the existing search')
    bedroomMin: int | None = Field(None, description='Minimum number of bedrooms in the property.')
    bedroomMax: int | None = Field(None, description='Maximum number of bedrooms in the property.')
    budgetMax: float | None = Field(None, description='Maximum budget for the property.')
    budgetMin: float | None = Field(None, description='Minimum budget for the property.')
    endpointRecipient: str | None = Field(None, description='HTTPS webhook that receives `match` payloads whenever a property satisfies the search. Requires `notificationEnabled=true`.', max_length=4096)
    eventEndpoint: str | None = Field(None, description='HTTPS webhook that receives advert `event` payloads (price changes, expirations, etc.). Requires `notificationEnabled=true` and at least one entry in `subscribedEvents`.', max_length=4096)
    furnished: bool | None = Field(None, description='Whether the property is furnished or not.')
    includedCities: list[str] | None = Field(None, description='Included cities. Use the location autocomplete endpoint to get the desired city IRIs.')
    includedDepartments: list[str] | None = Field(None, description='Included departments. Use the location autocomplete endpoint to get the desired department IRIs.')
    includedZipcodes: list[str] | None = Field(None, description='Included zipcodes.')
    lat: float | None = Field(None, description='Latitude of the center point used for radial filtering. Provide together with `lon`.', ge=-90, le=90)
    lon: float | None = Field(None, description='Longitude of the center point used for radial filtering. Provide together with `lat`.', ge=-180, le=180)
    notificationEnabled: bool | None = Field(None, description='Enables delivery of matches and events either by webhook (`endpointRecipient`, `eventEndpoint`) or by email (`notificationRecipient`).')
    notificationRecipient: str | None = Field(None, description='Email address that receives alert summaries when `notificationEnabled=true`.', max_length=4096)
    propertyTypes: list[Literal[0, 1, 2, 3, 4, 5, 6]] = Field(..., description='Type of property. Apartment `0`, House `1`, Building `2`, Parking `3`, Office `4`, Land `5`, Shop `6`.', min_length=1)
    publisherTypes: list[Literal[0, 1]] | None = Field(None, description='Type of publisher. Individual `0`, Professional `1`.')
    radius: float | None = Field(None, description='Distance in kilometers around the provided `lat`/`lon`.', gt=0)
    roomMin: int | None = Field(None, description='Minimum number of rooms.')
    roomMax: int | None = Field(None, description='Maximum number of rooms.')
    subscribedEvents: list[Literal['ad.update.price', 'ad.update.surface', 'ad.update.pictures', 'ad.update.expired', 'property.ad.create', 'property.ad.update']] | None = Field(None, description='Event codes you want to receive on the `eventEndpoint`.')
    surfaceMax: float | None = Field(None, description='Maximum property surface area.')
    surfaceMin: float | None = Field(None, description='Minimum property surface area.')
    title: str = Field(..., description='Title of the created search.', max_length=4096, min_length=1)
    transactionType: Literal[0, 1] = Field(..., description='Type of transaction. Sell `0`, Rent `1`.')
    withCoherentPrice: bool | None = Field(None, description='Price coherence filter. `true` returns adverts whose price passes our coherence checks; `false` returns adverts flagged as incoherent — both also include adverts whose price has not been assessed. Set to `null` (or send an empty value) to disable filtering. If omitted, defaults to `true`.')
    withVirtualTour: bool | None = Field(None, description='Whether the property includes a virtual tour.')

class MeloDeleteSearchConfig(_Input):
    """Delete a search."""
    operation: Literal['delete_search'] = Field('delete_search', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='UUID of the selected search')


MeloOperation = Annotated[Union[MeloListPropertiesConfig, MeloGetPropertyConfig, MeloListSimilarPropertiesConfig, MeloGetPricePerMeterConfig, MeloListPointsOfInterestConfig, MeloListLocationsConfig, MeloListCitiesConfig, MeloListSearchesConfig, MeloGetSearchConfig, MeloCreateSearchConfig, MeloUpdateSearchConfig, MeloDeleteSearchConfig], Field(discriminator="operation")]


class MeloFullConfig(NodeConfig[MeloOperation, MeloAPIKeyCredential]):
    pass


ROUTES = {'list_properties': ('GET', '/documents/properties'), 'get_property': ('GET', '/documents/properties/{id}'), 'list_similar_properties': ('GET', '/documents/properties/{id}/similar-properties'), 'get_price_per_meter': ('GET', '/indicators/price_per_meter'), 'list_points_of_interest': ('GET', '/indicators/points_of_interest'), 'list_locations': ('GET', '/public/location-autocomplete'), 'list_cities': ('GET', '/cities'), 'list_searches': ('GET', '/searches'), 'get_search': ('GET', '/searches/{id}'), 'create_search': ('POST', '/searches'), 'update_search': ('PUT', '/searches/{id}'), 'delete_search': ('DELETE', '/searches/{id}')}
COLLECTIONS = frozenset(['list_properties', 'list_similar_properties', 'get_price_per_meter', 'list_points_of_interest', 'list_locations', 'list_cities', 'list_searches'])


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


class MeloNode(WorkflowNode):
    integration_type = "automation-melo"
    connection_evidence = ConnectionEvidence(noun="saved searches", operation="list_searches",
        label_keys=("title", "@id"))

    @classmethod
    def get_config_model(cls):
        return MeloFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Melo API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", by_alias=True, exclude_none=True)
        values.pop("operation")
        if "{id}" in path:
            path = path.replace("{id}", values.pop("id"))
        kwargs = {}
        if method in {"POST", "PUT"}:
            kwargs["json"] = values
        else:
            # Stream Estate documents PHP-style bracketed array query keys.
            # https://docs.stream.estate/api-reference/endpoint/indicators/points_of_interest.md
            params = []
            for key, value in values.items():
                if isinstance(value, list):
                    params.extend((key + "[]", str(item)) for item in value)
                else:
                    params.append((key, str(value).lower() if isinstance(value, bool) else str(value)))
            kwargs["params"] = params
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.stream.estate" + path,
                    headers={"X-API-KEY": secret, "Accept": "application/json"}, **kwargs)
        except httpx.RequestError:
            raise ValueError("Melo request could not be completed; inspect the saved search before retrying a write") from None
        expected = 201 if method == "POST" else 204 if method == "DELETE" else 200
        if response.status_code != expected:
            message = "Melo did not confirm the request"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = error.get("hydra:description") or error.get("detail") or error.get("message") or message
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(str(message), secret)}
        if method == "DELETE":
            return {"status": "success", "http_status": 204, "deleted_id": str(config.id)}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Melo returned an unreadable JSON response") from None
        if not isinstance(payload, dict) or any(k in payload for k in ("error", "errors", "hydra:description")):
            raise ValueError("Melo returned an unexpected response")
        result = {"status": "success", "http_status": response.status_code, "data": payload}
        if config.operation in COLLECTIONS:
            items = payload.get("hydra:member")
            if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
                raise ValueError("Melo returned an unexpected collection")
            result["items"] = items
            # Return the provider's continuation as metadata; never follow URLs.
            result["next_page"] = payload.get("hydra:view", {}).get("hydra:next")
        return _redact(result, secret)
