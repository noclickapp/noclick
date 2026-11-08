"""eTermin REST API 1.0.0: account scheduling, contacts and service operations.

Contract: https://api.swaggerhub.com/apis/etermin.net/eTermin-API/1.0.0
Authentication and production origin: https://www.etermin.net/online-terminplaner-api
All operation parameters are query parameters, including POST and PUT.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://www.etermin.net"


class EterminAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Etermin API Keys", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.etermin.net/online-terminplaner-api",
            "x-credential-instructions": "Copy the public API key and private secret key from your eTermin account settings under Configuration → Integration – API → API. NoClick signs each request with a fresh salt and HMAC-SHA256. Both keys are required. Connecting reads your account's calendars.",
        })
    credential_type: Literal["etermin_api_key"] = Field("etermin_api_key", json_schema_extra={"ui:hidden": True})
    public_key: str = Field(..., min_length=1, max_length=4096, title="Public API key", repr=False,
        json_schema_extra={"ui:widget": "password"})
    private_key: str = Field(..., min_length=1, max_length=4096, title="Private secret key", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("public_key", "private_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the key, without spaces or a header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def selected_changes(self):
        values = self.model_dump(exclude_none=True)
        if values.get("operation", "").startswith("update_") and not (set(values) - {"operation", "id"}):
            raise ValueError("Provide at least one field to update")
        return self


class ListAppointments(Input):
    """Get appointment details."""
    operation: Literal["list_appointments"] = Field("list_appointments", json_schema_extra={"ui:hidden": True})
    appid: Optional[float] = Field(None, description='ID of an appointment. (relates to the ID)')
    id: Optional[str] = Field(None, description='ID of an appointment. (relates to the ExternalID)', min_length=1, max_length=10000)
    start: Optional[str] = Field(None, description='Start date of the appointments. Format yyyy-mm-dd. It will return a list with all appointments that are between "start" and "end".', min_length=1, max_length=10000)
    end: Optional[str] = Field(None, description='End date of the appointments. Format yyyy-mm-dd. It will return a list with all appointments that are between "start" and "end".', min_length=1, max_length=10000)
    bycreationdate: Optional[bool] = Field(None, description='Changes the start and end parameters to look for the creation date instead of the date, the appointment takes place')
    calendarid: Optional[str] = Field(None, description='IDs of the calendars that you want to get appointments from, you can separate multiple calendars with a ","', min_length=1, max_length=10000)
    cid: Optional[int] = Field(None, description='Use a customer ID to see all appointments that are related to this customer. (start and end parameters not required)')
    email: Optional[str] = Field(None, description='Use an email address to see all appointments that are related to this email. (start and end parameters required)', min_length=1, max_length=10000)
    limited: Optional[bool] = Field(None, description='Reduces the amount of information that the response have. Set to 1 if you want basic information about a lot of appointments.')
    manualconfirmed: Optional[bool] = Field(None, description='If set to 0 shows all appointments in the specified timeframe (start and end) that are not confirmed yet')


class CreateAppointment(Input):
    """Create appointment."""
    operation: Literal["create_appointment"] = Field("create_appointment", json_schema_extra={"ui:hidden": True})
    start: str = Field(..., description='Start date and time of the appointment. Format: yyyy-mm-dd HH:MM e.g. 2017-10-24 18:00', min_length=1, max_length=10000)
    end: str = Field(..., description='End date and time of the appointment. Format: yyyy-mm-dd HH:MM e.g. 2017-10-24 19:00', min_length=1, max_length=10000)
    calendarid: int = Field(..., description="ID of the calendar. Use the 'Calendar - Get calendar details' function to get a list with all available calendars")
    services: Optional[str] = Field(None, description="ID of the service. Use the 'Service - Get service details' function to get a list with all available services. To use multiple services use a comma (,) to seperate the IDs", min_length=1, max_length=10000)
    capacity: Optional[int] = Field(None, description='Defines the capacity of the appointment')
    location: Optional[str] = Field(None, description='Location of the appointment', min_length=1, max_length=10000)
    checkexist: Optional[bool] = Field(None, description='Checks if the appointment start/end time is available (1 = yes, 0 = no). May not work with multiple capacity')
    manualconfirmed: Optional[int] = Field(None, description='Set to 0 to have the appointment manually confirmed by the appoinment provider')
    sendemail: Optional[bool] = Field(None, description='Send a confirmation email to the adress that was specified in the email parameter (1 = yes, 0 = no)')
    sms: Optional[bool] = Field(None, description='Send a confirmation sms to the phone number that was specified in the phone field (1 = yes, 0 = no).')
    notificationmsg: Optional[bool] = Field(None, description='Send an information email to the appointment provider (1 = yes, 0 = no).')
    sync: Optional[bool] = Field(None, description='True if the appointment should be synchronized with external calendars (1 = yes, 0 = no).')
    lastname: Optional[str] = Field(None, description='Lastname of the person', min_length=1, max_length=10000)
    firstname: Optional[str] = Field(None, description='Firstname of the person', min_length=1, max_length=10000)
    email: Optional[str] = Field(None, description='E-Mail of the person', min_length=1, max_length=10000)
    phone: Optional[str] = Field(None, description='Phone of the person', min_length=1, max_length=10000)
    notes: Optional[str] = Field(None, description='Appointment notes', min_length=1, max_length=10000)
    customernumber: Optional[str] = Field(None, description='ID of the person that booked appointment', min_length=1, max_length=10000)


class UpdateAppointment(Input):
    """Update appointment."""
    operation: Literal["update_appointment"] = Field("update_appointment", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='ID of the appointment that you want to modify.', min_length=1, max_length=10000)
    start: Optional[str] = Field(None, description='Start date and time of the appointment. Format: yyyy-mm-dd HH:MM e.g. 2017-10-24 18:00', min_length=1, max_length=10000)
    end: Optional[str] = Field(None, description='End date and time of the appointment. Format: yyyy-mm-dd HH:MM e.g. 2017-10-24 19:00', min_length=1, max_length=10000)
    calendarid: Optional[int] = Field(None, description='ID of the calendar.')
    services: Optional[str] = Field(None, description="ID of the service. Use the 'Service - Get service details' function to get a list with all available services. To use multiple services use a comma (,) to seperate the IDs", min_length=1, max_length=10000)
    capacity: Optional[int] = Field(None, description='Defines the capacity of the appointment')
    location: Optional[str] = Field(None, description='Location of the appointment', min_length=1, max_length=10000)
    manualconfirmed: Optional[int] = Field(None, description='Set to 0 to have the appointment manually confirmed by the appoinment provider, set to 1 if the appointment got confirmed')
    sendemail: Optional[bool] = Field(None, description='Send a confirmation email to the adress that was specified in the email parameter (1 = yes, 0 = no).')
    msgtype: Optional[int] = Field(None, description='ID of the template that is sent to the customer with the API call')
    sendsms: Optional[bool] = Field(None, description='Send a confirmation SMS to the phone number that was specified in the phone parameter (1 = yes, 0 = no).')
    msgtypesms: Optional[int] = Field(None, description='ID of the template that is sent to the customer via SMS with the API call (required to send a SMS)')
    notificationmsg: Optional[bool] = Field(None, description='Send an information email to the appointment provider (1 = yes, 0 = no).')
    sync: Optional[bool] = Field(None, description='True if the appointment should be synchronized with external calendars (1 = yes, 0 = no).')
    lastname: Optional[str] = Field(None, description='Lastname of the person.', min_length=1, max_length=10000)
    firstname: Optional[str] = Field(None, description='Firstname of the person.', min_length=1, max_length=10000)
    email: Optional[str] = Field(None, description='E-Mail of the person.', min_length=1, max_length=10000)
    phone: Optional[str] = Field(None, description='Phone of the person.', min_length=1, max_length=10000)
    notes: Optional[str] = Field(None, description='Appointment notes.', min_length=1, max_length=10000)
    customernumber: Optional[str] = Field(None, description='ID of the person that booked appointment.', min_length=1, max_length=10000)


class DeleteAppointment(Input):
    """Delete appointment."""
    operation: Literal["delete_appointment"] = Field("delete_appointment", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='ID of the appointment,  use externalid instead, if you use the parameter sync=1 or sendemail=1  (relates to the ExternalID)', min_length=1, max_length=10000)


class ListDeletedAppointments(Input):
    """Get Deleted Appointments."""
    operation: Literal["list_deleted_appointments"] = Field("list_deleted_appointments", json_schema_extra={"ui:hidden": True})
    start: Optional[str] = Field(None, description='Start day when appointment(s) got deleted. Format: yyyy-mm-dd. It will return a list with all appointments that are between start and end', min_length=1, max_length=10000)
    end: Optional[str] = Field(None, description='End day when appointment(s) got deleted. Format: yyyy-mm-dd. It will return a list with all appointments there are between start and end', min_length=1, max_length=10000)


class ListContacts(Input):
    """Get contact details."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    email: Optional[str] = Field(None, description='E-Mail of the contact', min_length=1, max_length=10000)
    id: Optional[str] = Field(None, description='ExternalID of the contact', min_length=1, max_length=10000)
    cid: Optional[str] = Field(None, description='CID of the contact', min_length=1, max_length=10000)
    creationdate: Optional[str] = Field(None, description='Displays all contacts that were created on this date', min_length=1, max_length=10000)
    creationdateall: Optional[str] = Field(None, description='Displays all contacts that were created since this date', min_length=1, max_length=10000)


class CreateContact(Input):
    """Create contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    updatewhenexistsgdt: Optional[int] = Field(None, description='Set to 1 to check if the contact is already existing. If so the existing contact gets updated. Needs email or firstname, lastname, birthday.')
    salutation: Optional[str] = Field(None, description='Salutation of the person.', min_length=1, max_length=10000)
    title: Optional[str] = Field(None, description='Title of the person.', min_length=1, max_length=10000)
    lastname: Optional[str] = Field(None, description='Lastname of the person.', min_length=1, max_length=10000)
    firstname: Optional[str] = Field(None, description='Firstname of the person.', min_length=1, max_length=10000)
    birthday: Optional[str] = Field(None, description='Birthday of the person.', min_length=1, max_length=10000)
    email: str = Field(..., description='E-Mail of the person.', min_length=1, max_length=10000)
    phone: Optional[str] = Field(None, description='Phone of the person.', min_length=1, max_length=10000)
    company: Optional[str] = Field(None, description='Company of the person (make sure this field exists in your account)', min_length=1, max_length=10000)
    street: Optional[str] = Field(None, description='Street of the person.', min_length=1, max_length=10000)
    zip: Optional[str] = Field(None, description='Zip of the person.', min_length=1, max_length=10000)
    city: Optional[str] = Field(None, description='City of the person.', min_length=1, max_length=10000)
    state: Optional[str] = Field(None, description='State of the person.', min_length=1, max_length=10000)
    country: Optional[str] = Field(None, description='Country of the person.', min_length=1, max_length=10000)
    customernumber: Optional[str] = Field(None, description='ID of the person.', min_length=1, max_length=10000)
    newsletter: Optional[bool] = Field(None, description='Opts the contact into the newsletter.')


class DeleteContact(Input):
    """Delete contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    cid: str = Field(..., description='CID of the contact', min_length=1, max_length=10000)


class ListCalendars(Input):
    """Get calendar details."""
    operation: Literal["list_calendars"] = Field("list_calendars", json_schema_extra={"ui:hidden": True})
    calendarid: Optional[int] = Field(None, description='ID of the calendar, if you only need to get the details of a single calendar')


class ListServices(Input):
    """Get service details."""
    operation: Literal["list_services"] = Field("list_services", json_schema_extra={"ui:hidden": True})
    languageid: Optional[str] = Field(None, description='Use the language code in which you want the name and description of the service (e.g., DE, EN, etc.)', min_length=1, max_length=10000)
    id: Optional[int] = Field(None, description='ID of the service to get the information of a specific service')
    ServiceGroupID: Optional[int] = Field(None, description='Use if you want only services of a specific service group')
    addimage: Optional[int] = Field(None, description='true if you want to also get the image-data in your response')


class CreateService(Input):
    """Create service."""
    operation: Literal["create_service"] = Field("create_service", json_schema_extra={"ui:hidden": True})
    servicegroupid: int = Field(..., description='ID of the service group')
    servicede: str = Field(..., description='Name of the service in german. For other languages use serviceLANGUAGECODE e.g. serviceen', min_length=1, max_length=10000)
    timeslotminutes: int = Field(..., description='Duration of the service in minutes')
    infode: Optional[str] = Field(None, description='Additional description of the service in german. For other languages use serviceLANGUAGECODE e.g. infoen', min_length=1, max_length=10000)
    price: Optional[float] = Field(None, description='Price of the service')
    abbreviation: Optional[str] = Field(None, description='abbreviation of the service', min_length=1, max_length=10000)
    enablecapacity: Optional[bool] = Field(None, description='True to enable the capacity of the service')
    maxcapacity: Optional[float] = Field(None, description='Sets the maximum capacity of the service')
    currency: Optional[str] = Field(None, description='Defines the currency of the service', min_length=1, max_length=10000)
    showinternal: Optional[bool] = Field(None, description='Defines if the service is shown in the backend')
    enabled: Optional[bool] = Field(None, description='Defines if the service is shown in the frontend')


class UpdateService(Input):
    """Update service."""
    operation: Literal["update_service"] = Field("update_service", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='ID of the service')
    servicegroupid: Optional[int] = Field(None, description='ID of the service group')
    servicede: Optional[str] = Field(None, description='Name of the service in german. For other languages use serviceLANGUAGECODE e.g. serviceen', min_length=1, max_length=10000)
    timeslotminutes: Optional[int] = Field(None, description='Duration of the service in minutes')
    infode: Optional[str] = Field(None, description='Additional description of the service in german. For other languages use serviceLANGUAGECODE e.g. infoen', min_length=1, max_length=10000)
    price: Optional[float] = Field(None, description='Price of the service')
    abbreviation: Optional[str] = Field(None, description='abbreviation of the service', min_length=1, max_length=10000)
    enablecapacity: Optional[bool] = Field(None, description='True to enable the capacity of the service')
    maxcapacity: Optional[float] = Field(None, description='Sets the maximum capacity of the service')
    currency: Optional[str] = Field(None, description='Defines the currency of the service', min_length=1, max_length=10000)
    showinternal: Optional[bool] = Field(None, description='Defines if the service is shown in the backend')
    enabled: Optional[bool] = Field(None, description='Defines if the service is shown in the frontend')


class DeleteService(Input):
    """Delete service."""
    operation: Literal["delete_service"] = Field("delete_service", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='ID of the service', min_length=1, max_length=10000)


class ListServiceGroups(Input):
    """Get service groups details."""
    operation: Literal["list_service_groups"] = Field("list_service_groups", json_schema_extra={"ui:hidden": True})
    servicegroupid: Optional[int] = Field(None, description='ID of the servicegroup that you want information on')
    languageid: Optional[str] = Field(None, description='Language code if you only want the information for a specific language e.g. DE, EN, etc.', min_length=1, max_length=10000)


class ListTimeslots(Input):
    """Get available time slots."""
    operation: Literal["list_timeslots"] = Field("list_timeslots", json_schema_extra={"ui:hidden": True})
    date: str = Field(..., description='Day that you want to check if there are available slots. Format: yyyy-mm-dd', min_length=1, max_length=10000)
    rangesearch: Optional[int] = Field(None, description='0 - All slots of a specific day will be displayed   1 - Searches until it found a date when slots are available. Returns the number of slots that are available on a specific day (according to the account settings, the available slots may differ)')
    end: Optional[str] = Field(None, description='End date of the time range. Only works if rangesearch=1. Format: yyyy-mm-dd', min_length=1, max_length=10000)
    serviceid: Optional[str] = Field(None, description="ID(s) of the selected service(s). This parameter is required if you restrict the calendar or working times to specific services. Several service ID's can be separated with a comma (,). e.g. 45345,45346 etc.", min_length=1, max_length=10000)
    calendarid: Optional[str] = Field(None, description='ID of the calendar. Use this parameter if you want to get available time slots for a specific calendar. If this parameter is empty, available time slots for all calendars will be returned.', min_length=1, max_length=10000)
    capacity: Optional[int] = Field(None, description='Defines the capacity that is searched for, if you have capacity enabled')
    duration: Optional[int] = Field(None, description='Appointment duration in minutes. Use this parameter if you want to use a different duration than specified for the service')
    cluster: Optional[int] = Field(None, description='Appointment cluster on (1) or off (0)')


class ListWorkingTimes(Input):
    """Get Working times."""
    operation: Literal["list_working_times"] = Field("list_working_times", json_schema_extra={"ui:hidden": True})
    calendarid: int = Field(..., description='CalendarID of the calendar you need the working times for')
    all: Optional[bool] = Field(None, description='Use this parameter instead of calendarid, if you want the workingtimes of all calendars')
    join: Optional[int] = Field(None, description='Set to 1 for the same information but with names instead of numbers')


class ListAbsences(Input):
    """Get absences."""
    operation: Literal["list_absences"] = Field("list_absences", json_schema_extra={"ui:hidden": True})
    calendarid: int = Field(..., description='ID of the calendar.')


class CreateAbsence(Input):
    """Create an absence."""
    operation: Literal["create_absence"] = Field("create_absence", json_schema_extra={"ui:hidden": True})
    appcalendarid: int = Field(..., description='ID of the calendar. Use the "Calendar - Get calendar details" function to get a list with all available calendars.')
    startdate: str = Field(..., description='Start time of the absence. Format: yyyy-mm-dd HH:MM e.g. 2017-10-24 18:00', min_length=1, max_length=10000)
    enddate: str = Field(..., description='End time of the absence. Format: yyyy-mm-dd HH:MM e.g. 2017-10-24 18:00', min_length=1, max_length=10000)
    reason: Optional[str] = Field(None, description='Reason or note for the absence.', min_length=1, max_length=10000)
    nwtype: Optional[bool] = Field(None, description='Indicates if the absence is dynamic.')
    dynamicdays: Optional[int] = Field(None, description='Number of days for the dynamic absence to begin (nwtype has to be 1).')
    dynamicdaysduration: Optional[int] = Field(None, description='Number of days for the dynamic absence to last (nwtype has to be 1).')


class UpdateAbsence(Input):
    """Update an absence."""
    operation: Literal["update_absence"] = Field("update_absence", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='ID of the absence.')
    appcalendarid: Optional[int] = Field(None, description='ID of the calendar. Use the "Calendar - Get calendar details" function to get a list with all available calendars.')
    startdate: Optional[str] = Field(None, description='Start time of the absence. Format: yyyy-mm-dd HH:MM e.g. 2017-10-24 18:00', min_length=1, max_length=10000)
    enddate: Optional[str] = Field(None, description='End time of the absence. Format: yyyy-mm-dd HH:MM e.g. 2017-10-24 18:00', min_length=1, max_length=10000)
    reason: Optional[str] = Field(None, description='Reason or note for the absence.', min_length=1, max_length=10000)
    nwtype: Optional[bool] = Field(None, description='Indicates if the absence is dynamic.')
    dynamicdays: Optional[int] = Field(None, description='Number of days for the dynamic absence (nwtype has to be 1).')


class DeleteAbsence(Input):
    """Delete an absence."""
    operation: Literal["delete_absence"] = Field("delete_absence", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='ID of the absence.')


EterminConfig = Annotated[
    Union[
        ListAppointments,
        CreateAppointment,
        UpdateAppointment,
        DeleteAppointment,
        ListDeletedAppointments,
        ListContacts,
        CreateContact,
        DeleteContact,
        ListCalendars,
        ListServices,
        CreateService,
        UpdateService,
        DeleteService,
        ListServiceGroups,
        ListTimeslots,
        ListWorkingTimes,
        ListAbsences,
        CreateAbsence,
        UpdateAbsence,
        DeleteAbsence,
    ],
    Field(discriminator="operation"),
]


class EterminFullConfig(NodeConfig[EterminConfig, EterminAPIKeyCredential]):
    pass


ROUTES = {
    "list_appointments": ("GET", "/api/appointment"),
    "create_appointment": ("POST", "/api/appointment"),
    "update_appointment": ("PUT", "/api/appointment"),
    "delete_appointment": ("DELETE", "/api/appointment"),
    "list_deleted_appointments": ("GET", "/api/appointmentdeleted"),
    "list_contacts": ("GET", "/api/contact"),
    "create_contact": ("POST", "/api/contact"),
    "delete_contact": ("DELETE", "/api/contact"),
    "list_calendars": ("GET", "/api/calendar"),
    "list_services": ("GET", "/api/service"),
    "create_service": ("POST", "/api/service"),
    "update_service": ("PUT", "/api/service"),
    "delete_service": ("DELETE", "/api/service"),
    "list_service_groups": ("GET", "/api/servicegroup"),
    "list_timeslots": ("GET", "/api/timeslots"),
    "list_working_times": ("GET", "/api/workingtimes"),
    "list_absences": ("GET", "/api/calendarsnonworkingtimes"),
    "create_absence": ("POST", "/api/calendarsnonworkingtimes"),
    "update_absence": ("PUT", "/api/calendarsnonworkingtimes"),
    "delete_absence": ("DELETE", "/api/calendarsnonworkingtimes"),
}

# These contract operations publish a 200 response without a content schema.
ACK_ONLY = frozenset({"update_appointment", "delete_appointment", "create_absence", "update_absence", "delete_absence"})


def _redact(value, keys):
    if isinstance(value, str):
        for key in keys:
            value = value.replace(key, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, keys) for item in value]
    if isinstance(value, dict):
        return {name: _redact(item, keys) for name, item in value.items()}
    return value


class EterminNode(WorkflowNode):
    integration_type = "automation-etermin"
    connection_evidence = ConnectionEvidence(noun="calendars", operation="list_calendars", label_keys=("CalendarName", "CalendarID"))

    @classmethod
    def get_config_model(cls):
        return EterminFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your eTermin API keys")
        config = self.config.config
        method, path = ROUTES[config.operation]
        params = {name: ("true" if value is True else "false" if value is False else value)
            for name, value in config.model_dump(exclude_none=True).items() if name != "operation"}
        salt = secrets.token_hex(16)
        signature = base64.b64encode(hmac.new(credential.private_key.encode(), salt.encode(), hashlib.sha256).digest()).decode()
        headers = {"publickey": credential.public_key, "salt": salt, "signature": signature, "Accept": "application/json"}
        redact = (credential.public_key, credential.private_key, signature)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params, headers=headers)
        if response.status_code != 200:
            detail = _redact(response.text[:2000], redact)
            raise ValueError(f"eTermin HTTP {response.status_code}: {detail}")
        if len(response.content) > 10_000_000:
            raise ValueError("eTermin response exceeds the supported size")
        # Some mutation operations publish only a 200 acknowledgement, without a body schema.
        if not response.content:
            if config.operation in ACK_ONLY:
                return {"acknowledged": True, "http_status": 200}
            raise ValueError("eTermin returned an empty response for this operation")
        try:
            body = response.json()
        except ValueError:
            if config.operation in ACK_ONLY and re.fullmatch(r"[1-9][0-9]* record(?:\(s\)|s)? (?:updated|deleted)!?", response.text.strip(), re.IGNORECASE):
                return {"acknowledged": True, "message": _redact(response.text, redact), "http_status": 200}
            raise ValueError("Expected JSON from eTermin") from None
        body = _redact(body, redact)
        if isinstance(body, dict):
            status = body.get("Status", body.get("status"))
            if status is not None and str(status) != "200":
                raise ValueError(str(body.get("StatusMsg", body.get("statusmsg", "eTermin rejected the request"))))
            if any(body.get(key) for key in ("error", "errors", "Error")):
                raise ValueError(str(body.get("error") or body.get("errors") or body.get("Error")))
        if method == "GET":
            if not isinstance(body, list) or any(not isinstance(item, dict) for item in body):
                raise ValueError("Expected a list of records from eTermin")
            return {"items": body}
        if not isinstance(body, dict):
            raise ValueError("Unexpected eTermin mutation response")
        return {"data": body, "acknowledged": True, "http_status": 200}
