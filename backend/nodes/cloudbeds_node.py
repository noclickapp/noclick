"""Cloudbeds PMS v1.3 operations, using a manually supplied property API key.

Contract: https://github.com/cloudbeds/openapi-specs/blob/main/src/pms-v1.3-openapi.yaml
Lists return one provider page, including its count/total metadata.
"""
from datetime import date, datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.cloudbeds.com/api/v1.3"


class CloudbedsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Cloudbeds API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.cloudbeds.com/docs/quickstart-guide-api-authentication-for-property-level-users",
            "x-credential-instructions": "Create an API key in Cloudbeds with permissions for the operations you use, including read:hotel for the connection check. Paste only the key. NoClick sends it in the x-api-key header to api.cloudbeds.com.",
        })
    credential_type: Literal["cloudbeds_api_key"] = Field("cloudbeds_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CloudbedsListPropertiesConfig(_Input):
    operation: Literal["list_properties"] = Field("list_properties", json_schema_extra={"ui:hidden": True})
    propertyIDs: str | None = Field(None, description='List of property IDs, comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    propertyName: str | None = Field(None, description='Property name, or part of it', min_length=1, max_length=1000)
    propertyCity: str | None = Field(None, description='Property city, or part of it', min_length=1, max_length=1000)
    pageNumber: int = Field(1, description='Page number', ge=1)
    pageSize: int = Field(20, description='Page size', ge=1, le=100)


class CloudbedsGetPropertyConfig(_Input):
    operation: Literal["get_property"] = Field("get_property", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='Property ID', min_length=1, max_length=1000)


class CloudbedsGetGuestConfig(_Input):
    operation: Literal["get_guest"] = Field("get_guest", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='Property ID', min_length=1, max_length=1000)
    guestID: str = Field(..., description='Guest ID. Required if no reservationID is provided.', min_length=1, max_length=1000)
    includeGuestRequirements: bool = Field(False, description='Includes guest requirements data in the response')


class CloudbedsListGuestsConfig(_Input):
    operation: Literal["list_guests"] = Field("list_guests", json_schema_extra={"ui:hidden": True})
    propertyIDs: str | None = Field(None, description='List of property IDs, comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    resultsFrom: datetime | None = Field(None, description='Inferior limit datetime, used to filter guests result, based on latest creation/modification date')
    resultsTo: datetime | None = Field(None, description='Superior limit datetime, used to filter guests result, based on latest creation/modification date')
    checkInFrom: date | None = Field(None, description='Filters guests result to return only guests with check-in date range starting on this date')
    checkInTo: date | None = Field(None, description='Filters guests result to return only guests with check-in date range ending on this date')
    checkOutFrom: date | None = Field(None, description='Filters guests result to return only guests with check-out date range starting on this date')
    checkOutTo: date | None = Field(None, description='Filters guests result to return only guests with check-out date range ending on this date')
    guestFirstName: str | None = Field(None, description='Filters guests result based on Guest First Name', min_length=1, max_length=1000)
    guestLastName: str | None = Field(None, description='Filters guests result based on Guest Last Name', min_length=1, max_length=1000)
    guestEmail: str | None = Field(None, description='Filters guests result based on Guest Email', min_length=1, max_length=1000)
    status: Literal['in_progress', 'confirmed', 'not_confirmed', 'canceled', 'checked_in', 'checked_out', 'no_show'] | None = Field(None, description='Reservation status <br /> If more than one, send as comma-separated values. i.e. in_progress,confirmed')
    includeGuestInfo: bool = Field(False, description="If API response should return with more of Guest's information")
    pageNumber: int = Field(1, description='Results page number', ge=1)
    pageSize: int = Field(100, description='Results page size. Max = 100', ge=1, le=100)


class CloudbedsListGuestNotesConfig(_Input):
    operation: Literal["list_guest_notes"] = Field("list_guest_notes", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='Property ID', min_length=1, max_length=1000)
    guestID: str = Field(..., description='Guest ID', min_length=1, max_length=1000)


class CloudbedsCreateGuestNoteConfig(_Input):
    operation: Literal["create_guest_note"] = Field("create_guest_note", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='Property ID', min_length=1, max_length=1000)
    guestID: str = Field(..., description='Guest ID', min_length=1, max_length=1000)
    guestNote: str = Field(..., description="Note to be added to guest profile. It's strictly forbidden to send unencrypted payment data through the API. Numeric values longer than 12 characters and considered valid by Luhn's algorithm will be rejected.", min_length=1, max_length=10000)
    userID: str | None = Field(None, description='User ID Identify the actual user that is posting the note', min_length=1, max_length=1000)


class CloudbedsListReservationsConfig(_Input):
    operation: Literal["list_reservations"] = Field("list_reservations", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='ID for the properties to be queried (comma-separated, i.e. 37,345,89).<br /> It can be omitted if the API key is single-property, or to get results from all properties on an association.', min_length=1, max_length=1000)
    status: Literal['not_confirmed', 'confirmed', 'canceled', 'checked_in', 'checked_out', 'no_show'] | None = Field(None, description='Filter by current reservation status')
    resultsFrom: datetime | None = Field(None, description='Inferior limit datetime, used to filter reservations, based on booking date')
    resultsTo: datetime | None = Field(None, description='Superior limit datetime, used to filter reservations, based on booking date')
    modifiedFrom: datetime | None = Field(None, description='Inferior limit datetime, used to filter reservations, based on booking modification date')
    modifiedTo: datetime | None = Field(None, description='Superior limit datetime, used to filter reservations, based on booking modification date')
    checkInFrom: date | None = Field(None, description='Filters reservations result to return only reservations with check-in date range starting on this date')
    checkInTo: date | None = Field(None, description='Filters reservations result to return only reservations with check-in date range ending on this date')
    checkOutFrom: date | None = Field(None, description='Filters reservations result to return only reservations with check-out date range starting on this date')
    checkOutTo: date | None = Field(None, description='Filters reservations result to return only reservations with check-out date range ending on this date')
    roomTypeID: str | None = Field(None, description='Filters reservation with the supplied Room Type ID.', min_length=1, max_length=1000)
    guestID: str | None = Field(None, description='Filters reservation with the supplied Guest ID (Including additional guests).', min_length=1, max_length=1000)
    firstName: str | None = Field(None, description='Filters reservation with the supplied primary guest first name.', min_length=1, max_length=1000)
    lastName: str | None = Field(None, description='Filters reservation with the supplied primary guest last name.', min_length=1, max_length=1000)
    includeGuestsDetails: bool = Field(False, description='If guests details should be included or not')
    includeCustomFields: bool = Field(False, description='If reservation custom fields should be included or not')
    includeAllRooms: bool = Field(False, description='When specified, the response will include an additional rooms field that combines both unassigned and assigned rooms.')
    pageNumber: int = Field(1, description='Results page number', ge=1)
    pageSize: int = Field(100, description='Results page size. Max = 100', ge=1, le=100)


class CloudbedsGetReservationConfig(_Input):
    operation: Literal["get_reservation"] = Field("get_reservation", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='Property ID', min_length=1, max_length=1000)
    reservationID: str = Field(..., description='Reservation Unique Identifier. Obtained from one of the "Reservations" group methods', min_length=1, max_length=1000)
    includeGuestRequirements: bool = Field(False, description='Includes guest requirements data in the response.')


class CloudbedsListReservationNotesConfig(_Input):
    operation: Literal["list_reservation_notes"] = Field("list_reservation_notes", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='Property ID', min_length=1, max_length=1000)
    reservationID: str = Field(..., description='Reservation Unique Identifier', min_length=1, max_length=1000)


class CloudbedsCreateReservationNoteConfig(_Input):
    operation: Literal["create_reservation_note"] = Field("create_reservation_note", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='Property ID', min_length=1, max_length=1000)
    reservationID: str = Field(..., description='Reservation Unique Identifier', min_length=1, max_length=1000)
    reservationNote: str = Field(..., description='Note to be added to reservation', min_length=1, max_length=10000)
    userID: str | None = Field(None, description='User ID Identify the actual user that is posting the note', min_length=1, max_length=1000)


class CloudbedsUpdateReservationStatusConfig(_Input):
    operation: Literal["update_reservation_status"] = Field("update_reservation_status", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='Property ID', min_length=1, max_length=1000)
    reservationID: str = Field(..., description='Reservation Unique Identifier, one reservation ID per call.', min_length=1, max_length=1000)
    status: Literal['confirmed', 'not_confirmed', 'canceled', 'checked_in', 'checked_out', 'no_show'] = Field(..., description="Reservation status<br /> 'confirmed' - Reservation is confirmed<br /> 'not_confirmed' - Reservation not passed confirmation<br /> 'canceled' - Reservation is canceled<br /> 'checked_in' - Guest is in hotel<br /> 'checked_out' - Guest already left hotel<br /> 'no_show' - Guest didn't showed up on check-in date")
    sendStatusChangeEmail: bool = Field(False, description='Send email on reservation status change to property and guest.')


class CloudbedsListRoomTypesConfig(_Input):
    operation: Literal["list_room_types"] = Field("list_room_types", json_schema_extra={"ui:hidden": True})
    propertyIDs: str | None = Field(None, description='Property ID list, comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    roomTypeIDs: str | None = Field(None, description='Room Type ID list, If more than one, send as comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    roomTypeName: str | None = Field(None, description='Room type name, used to filter', min_length=1, max_length=1000)
    propertyCity: str | None = Field(None, description='Hotel city, used to filter', min_length=1, max_length=1000)
    propertyName: str | None = Field(None, description='Hotel name, used to filter', min_length=1, max_length=1000)
    pageNumber: int = Field(1, description='Page number', ge=1)
    pageSize: int = Field(20, description='Page size', ge=1, le=100)


class CloudbedsListRoomsConfig(_Input):
    operation: Literal["list_rooms"] = Field("list_rooms", json_schema_extra={"ui:hidden": True})
    propertyIDs: str | None = Field(None, description='Property ID list, comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    roomTypeID: str | None = Field(None, description='Room type ID, comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    roomTypeNameShort: str | None = Field(None, description='Room Type (short-version)', min_length=1, max_length=1000)
    pageNumber: int = Field(1, description='Page number', ge=1)
    pageSize: int = Field(20, description='Page size', ge=1, le=100)
    includeArchived: bool | None = Field(None, description='Include archived units unless startDate/endDate are sent; live rows get archivedAt=null')


class CloudbedsListAvailableRoomTypesConfig(_Input):
    operation: Literal["list_available_room_types"] = Field("list_available_room_types", json_schema_extra={"ui:hidden": True})
    propertyIDs: str | None = Field(None, description='Property ID list, comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    startDate: date = Field(..., description='Check-In date.')
    endDate: date = Field(..., description='Check-Out date.')
    rooms: int = Field(..., description='Number of rooms.', ge=1)
    adults: int = Field(..., description='Number of adults.', ge=1)
    children: int = Field(..., description='Number of children.', ge=0)
    promoCode: str | None = Field(None, description='Promotional code', min_length=1, max_length=1000)
    pageNumber: int = Field(1, description='Page number', ge=1)
    pageSize: int = Field(20, description='Page size', ge=1, le=100)


class CloudbedsListHousekeepingStatusConfig(_Input):
    operation: Literal["list_housekeeping_status"] = Field("list_housekeeping_status", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='Property ID', min_length=1, max_length=1000)
    roomIDs: str | None = Field(None, description='Filter by room ID. If more than one, send as a comma-separated list, i.e. 101-0,101-3. A room ID has the form {roomTypeID}-{index} and is the same value this endpoint returns as data.roomID. Combined with the other filters using AND. A value that is not of that form is rejected with a 400 response. A well-formed ID that matches no room of this property is not an error - it simply contributes no result. An empty value applies no room filter, so every room of the property is returned.', min_length=1, max_length=1000)
    roomTypeIDs: str | None = Field(None, description='Filter by room type ID. If more than one, send as comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    housekeeperIDs: str | None = Field(None, description='Use this parameter to filter by housekeeper. If you need to specify multiple housekeepers, send their IDs as a comma-separated list (e.g., 37, 345, 89). To retrieve unassigned housekeepers, use the value 0.', min_length=1, max_length=1000)
    roomCondition: Literal['clean', 'dirty'] | None = Field(None, description='Condition of room')
    roomOccupied: bool | None = Field(None, description='Flag for current room occupation status')
    pageNumber: int = Field(1, description='Results page number', ge=1)
    pageSize: int = Field(100, description='Results page size. Max = 5000', ge=1, le=100)


class CloudbedsUpdateHousekeepingStatusConfig(_Input):
    operation: Literal["update_housekeeping_status"] = Field("update_housekeeping_status", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='Property ID', min_length=1, max_length=1000)
    roomID: str = Field(..., description='Room ID', min_length=1, max_length=1000)
    roomCondition: Literal['dirty', 'clean', 'inspected'] = Field(..., description='New room condition. If no optional parameters are sent, will switch from current room condition. "inspected" status is available only if the property has the feature enabled.')
    doNotDisturb: bool | None = Field(None, description='New "do not disturb" status')
    roomComments: str | None = Field(None, description='New room comments.', min_length=1, max_length=10000)
    refusedService: bool | None = Field(None, description='New "refused service" status')
    vacantPickup: bool | None = Field(None, description='New "vacant_pickup" status')


class CloudbedsListPaymentMethodsConfig(_Input):
    operation: Literal["list_payment_methods"] = Field("list_payment_methods", json_schema_extra={"ui:hidden": True})
    propertyID: str | None = Field(None, description='ID for the property to be queried', min_length=1, max_length=1000)
    lang: Literal['en', 'pt-br', 'es'] = Field('en', description='Language that payment methods name should return (if available).')


class CloudbedsListReservationSourcesConfig(_Input):
    operation: Literal["list_reservation_sources"] = Field("list_reservation_sources", json_schema_extra={"ui:hidden": True})
    propertyIDs: str | None = Field(None, description='ID for the properties to be queried (comma-separated, i.e. 37,345,89).<br />', min_length=1, max_length=1000)


class CloudbedsListRatePlansConfig(_Input):
    operation: Literal["list_rate_plans"] = Field("list_rate_plans", json_schema_extra={"ui:hidden": True})
    propertyIDs: str | None = Field(None, description='List of property IDs, comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    rateIDs: str | None = Field(None, description='List of Rate IDs, comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    roomTypeID: str | None = Field(None, description='List of Room Type IDs, comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    promoCode: str | None = Field(None, description='List of Promo Codes, comma-separated, i.e. 37,345,89', min_length=1, max_length=1000)
    includePromoCode: bool = Field(True, description='Include rate plans with promo code')
    startDate: date = Field(..., description='Check-in date')
    endDate: date = Field(..., description='Check-out date')
    adults: int | None = Field(None, description='Number of adults', ge=1)
    children: int | None = Field(None, description='Number of children', ge=0)
    detailedRates: bool = Field(False, description='If the rates need detailed information')


class CloudbedsListUsersConfig(_Input):
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    property_ids: str | None = Field(None, description='Property numeric identifiers (comma-separated, i.e. 37,345,89)', min_length=1, max_length=1000)


CloudbedsConfig = Annotated[Union[
    CloudbedsListPropertiesConfig,
    CloudbedsGetPropertyConfig,
    CloudbedsGetGuestConfig,
    CloudbedsListGuestsConfig,
    CloudbedsListGuestNotesConfig,
    CloudbedsCreateGuestNoteConfig,
    CloudbedsListReservationsConfig,
    CloudbedsGetReservationConfig,
    CloudbedsListReservationNotesConfig,
    CloudbedsCreateReservationNoteConfig,
    CloudbedsUpdateReservationStatusConfig,
    CloudbedsListRoomTypesConfig,
    CloudbedsListRoomsConfig,
    CloudbedsListAvailableRoomTypesConfig,
    CloudbedsListHousekeepingStatusConfig,
    CloudbedsUpdateHousekeepingStatusConfig,
    CloudbedsListPaymentMethodsConfig,
    CloudbedsListReservationSourcesConfig,
    CloudbedsListRatePlansConfig,
    CloudbedsListUsersConfig
], Field(discriminator="operation")]


class CloudbedsFullConfig(NodeConfig[CloudbedsConfig, CloudbedsAPIKeyCredential]):
    pass


ROUTES = {'list_properties': ('GET', '/getHotels'), 'get_property': ('GET', '/getHotelDetails'), 'get_guest': ('GET', '/getGuest'), 'list_guests': ('GET', '/getGuestList'), 'list_guest_notes': ('GET', '/getGuestNotes'), 'create_guest_note': ('POST', '/postGuestNote'), 'list_reservations': ('GET', '/getReservations'), 'get_reservation': ('GET', '/getReservation'), 'list_reservation_notes': ('GET', '/getReservationNotes'), 'create_reservation_note': ('POST', '/postReservationNote'), 'update_reservation_status': ('PUT', '/putReservation'), 'list_room_types': ('GET', '/getRoomTypes'), 'list_rooms': ('GET', '/getRooms'), 'list_available_room_types': ('GET', '/getAvailableRoomTypes'), 'list_housekeeping_status': ('GET', '/getHousekeepingStatus'), 'update_housekeeping_status': ('POST', '/postHousekeepingStatus'), 'list_payment_methods': ('GET', '/getPaymentMethods'), 'list_reservation_sources': ('GET', '/getSources'), 'list_rate_plans': ('GET', '/getRatePlans'), 'list_users': ('GET', '/getUsers')}


class CloudbedsNode(WorkflowNode):
    integration_type = "automation-cloudbeds"
    connection_evidence = ConnectionEvidence(noun="Cloudbeds properties", operation="list_properties")

    @classmethod
    def get_config_model(cls):
        return CloudbedsFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Cloudbeds API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        values = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in values.items()}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"x-api-key": self.config.credentials.api_key, "Accept": "application/json"},
                **({"params": values} if method == "GET" else {"data": values}))
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("success"), bool):
            raise ValueError("Cloudbeds returned an invalid response envelope")
        if not body["success"]:
            return {"status": "error", "error": body.get("message") or "Cloudbeds rejected the request", "response": body}
        return {**body, "status": "success"}
