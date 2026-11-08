"""Trestle identity-data lookups and live-call feedback using a pasted API key.

Each operation targets one published API version. Partial results and response IDs
remain available to workflows; rejected feedback is never reported as accepted.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.trestleiq.com"


class TrestleAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Trestle API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://portal.trestleiq.com/",
        "x-credential-instructions": "Paste your Trestle API key from the Trestle portal. Enable the products you will use. Connecting performs a Phone Validation lookup of the documentation's sample number (2069735100); this may consume quota. This proves key acceptance for that product, not account identity.",
    })
    credential_type: Literal["trestle_api_key"] = Field("trestle_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(char.isspace() or ord(char) < 33 or ord(char) > 126 for char in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


class CheckConnection(_Input):
    """Check key acceptance with the documented sample Phone Validation lookup."""
    operation: Literal["check_connection"] = "check_connection"


class GetAddressValidation(_Input):
    """Validate and normalize a US street address."""
    operation: Literal['get_address_validation'] = 'get_address_validation'
    street_line_1: str = Field(..., title='Street line 1', min_length=1, max_length=2000, description='The first line of the street part of the address. If it is missing, the response has `is_valid: false` and the `Missing Input` warning. Example `800 Bellevue Way NE`')
    street_line_2: Optional[str] = Field(None, title='Street line 2', min_length=1, max_length=2000, description='The second line of the street part of the address, for example an apartment or suite number. Example `Ste 100`')
    city: Optional[str] = Field(None, title='City', min_length=1, max_length=2000, description='The name of the city. Example `Bellevue`')
    state_code: Optional[str] = Field(None, title='State code', min_length=1, max_length=2000, description='Two-letter state code, any case. Example `WA`')
    postal_code: Optional[str] = Field(None, title='Postal code', min_length=1, max_length=2000, description='The postal code: a 5-digit ZIP (`98004`) or a ZIP+4, with or without the dash (`98004-4286` or `980044286`). The response always returns the 5-digit ZIP in `postal_code` and the 4-digit extension in `zip4`. Example `98004`')


class GetCallerIdentification(_Input):
    """Identify the top owner of a phone number."""
    operation: Literal['get_caller_identification'] = 'get_caller_identification'
    phone: str = Field(..., title='Phone', min_length=1, max_length=2000, description='Phone number in E.164 or local format. The default country calling code is +1 (USA). Example `2069735100`')
    phone_country_hint: Optional[str] = Field(None, title='Phone country hint', alias='phone.country_hint', min_length=1, max_length=2000, description='ISO-3166 alpha-2 country code of the phone number, any case. Example `US`')
    phone_name_hint: Optional[str] = Field(None, title='Phone name hint', alias='phone.name_hint', min_length=1, max_length=2000, description='Person or business name associated with the phone number. If multiple names are associated with the phone in the Trestle database, this name is ranked higher. Example `Waidong Syrws`')
    phone_postal_code_hint: Optional[str] = Field(None, title='Phone postal code hint', alias='phone.postal_code_hint', min_length=1, max_length=2000, description='Postal code of the subscriber address associated with the phone number. If multiple names or addresses are associated with the phone in the Trestle database, this postal code is used to rank the matching name and address higher. Example `98264`')
    add_ons: Optional[list[Literal['litigator_checks', 'spam_checks']]] = Field(None, title='Add ons', max_length=2, description='Comma-separated add-ons to enable. Options: `litigator_checks` (TCPA litigator detection, returned under `add_ons.litigator_checks`) and `spam_checks` (spam and scam detection, returned under `add_ons.spam_checks`). Additional charges apply. Example `litigator_checks,spam_checks`')
    source_id: Optional[str] = Field(None, title='Source id', min_length=1, max_length=255, description='Optional identifier used to group queries by source, campaign, channel, or cohort. Maximum length is 255 characters. Use only letters, numbers, spaces, and `. _ - : / | #`; the value cannot begin with `-`. An invalid value does not fail the request: it is dropped and a warning is added.')


class GetDecisionSignals(_Input):
    """Cross-check identity signals for a transaction."""
    operation: Literal['get_decision_signals'] = 'get_decision_signals'
    transaction_id: str = Field(..., title='Transaction id', min_length=1, max_length=2000, description='Caller-supplied correlation ID for the transaction. Example `txn_123`')
    transaction_time: str = Field(..., title='Transaction time', min_length=1, max_length=2000, description='UTC timestamp for the transaction, in `YYYY-MM-DD HH:MM` or ISO 8601 format. Positive UTC offsets and compact formats such as `YYYYMMDDTHHMM` are rejected. Example `2026-06-15T10:00`')
    primary_name: Optional[str] = Field(None, title='Primary name', alias='primary.name', min_length=1, max_length=2000, description='Full legal name of the primary person. Either `primary.name` or `primary.business_name` is required. Example `Robin Cooke`')
    primary_business_name: Optional[str] = Field(None, title='Primary business name', alias='primary.business_name', min_length=1, max_length=2000, description='Full legal name of the primary business. Either `primary.name` or `primary.business_name` is required. Example `The Golden Company`')
    secondary_name: Optional[str] = Field(None, title='Secondary name', alias='secondary.name', min_length=1, max_length=2000, description='Full legal name of the secondary person. Example `Vicky Kunal`')
    secondary_business_name: Optional[str] = Field(None, title='Secondary business name', alias='secondary.business_name', min_length=1, max_length=2000, description='Full legal name of the secondary business. Example `The Silver Company`')
    primary_phone: Optional[str] = Field(None, title='Primary phone', alias='primary.phone', min_length=1, max_length=2000, description='Primary phone number. Accepted formats: `+12065551234`, `12065551234`, `2065551234`, `(206) 555-1234`, `206-555-1234`. E.164 is recommended.')
    primary_phone_country_hint: Optional[str] = Field(None, title='Primary phone country hint', alias='primary.phone.country_hint', min_length=1, max_length=2000, description='ISO-3166 alpha-2 country code for the primary phone. Defaults to `US`.')
    secondary_phone: Optional[str] = Field(None, title='Secondary phone', alias='secondary.phone', min_length=1, max_length=2000, description='Secondary phone number. Same accepted formats as `primary.phone`.')
    secondary_phone_country_hint: Optional[str] = Field(None, title='Secondary phone country hint', alias='secondary.phone.country_hint', min_length=1, max_length=2000, description='ISO-3166 alpha-2 country code for the secondary phone.')
    primary_address_street_line_1: Optional[str] = Field(None, title='Primary address street line 1', alias='primary.address.street_line_1', min_length=1, max_length=2000, description='First line of the primary street address. Example `12843 NE 91st St`')
    primary_address_street_line_2: Optional[str] = Field(None, title='Primary address street line 2', alias='primary.address.street_line_2', min_length=1, max_length=2000, description='Second line of the primary street address. Example `Apt 4B`')
    primary_address_city: Optional[str] = Field(None, title='Primary address city', alias='primary.address.city', min_length=1, max_length=2000, description='City of the primary address. Example `Bellingham`')
    primary_address_state_code: Optional[str] = Field(None, title='Primary address state code', alias='primary.address.state_code', min_length=1, max_length=2000, description='Two-letter state or province code of the primary address. Example `WA`')
    primary_address_postal_code: Optional[str] = Field(None, title='Primary address postal code', alias='primary.address.postal_code', min_length=1, max_length=2000, description='Postal or ZIP code of the primary address. Example `98033`')
    primary_address_country_code: Optional[str] = Field(None, title='Primary address country code', alias='primary.address.country_code', min_length=1, max_length=2000, description='ISO-3166 alpha-2 country code of the primary address. Example `US`')
    secondary_address_street_line_1: Optional[str] = Field(None, title='Secondary address street line 1', alias='secondary.address.street_line_1', min_length=1, max_length=2000, description='First line of the secondary street address. Example `4492 163rd Pl SE`')
    secondary_address_street_line_2: Optional[str] = Field(None, title='Secondary address street line 2', alias='secondary.address.street_line_2', min_length=1, max_length=2000, description='Second line of the secondary street address. Example `Suite 200`')
    secondary_address_city: Optional[str] = Field(None, title='Secondary address city', alias='secondary.address.city', min_length=1, max_length=2000, description='City of the secondary address. Example `Bellevue`')
    secondary_address_state_code: Optional[str] = Field(None, title='Secondary address state code', alias='secondary.address.state_code', min_length=1, max_length=2000, description='Two-letter state or province code of the secondary address. Example `WA`')
    secondary_address_postal_code: Optional[str] = Field(None, title='Secondary address postal code', alias='secondary.address.postal_code', min_length=1, max_length=2000, description='Postal or ZIP code of the secondary address. Example `98006`')
    secondary_address_country_code: Optional[str] = Field(None, title='Secondary address country code', alias='secondary.address.country_code', min_length=1, max_length=2000, description='ISO-3166 alpha-2 country code of the secondary address. Example `US`')
    primary_email_address: Optional[str] = Field(None, title='Primary email address', alias='primary.email_address', min_length=1, max_length=2000, description='Primary email address. Example `john.doe@example.com`')
    secondary_email_address: Optional[str] = Field(None, title='Secondary email address', alias='secondary.email_address', min_length=1, max_length=2000, description='Secondary email address. Example `jane.doe@example.com`')
    ip_address: Optional[str] = Field(None, title='Ip address', min_length=1, max_length=2000, description='IPv4 or IPv6 address associated with the transaction. Private and loopback ranges return `is_valid: false`. Example `73.25.97.8`')
    is_sandbox: Optional[StrictBool] = Field(None, title='Is sandbox', description='When `true`, returns a pre-stored response for a sandbox scenario without live enrichment. See the Sandbox section of the API reference for the inputs that select each scenario.')

    @model_validator(mode="after")
    def primary_identity(self):
        if not (self.primary_name or self.primary_business_name):
            raise ValueError("Provide the primary person's name or business name")
        return self


class SubmitPhoneFeedback(_Input):
    """Submit real live-call outcomes; accepted feedback changes Trestle models.

    Use the Response-ID of a prior lookup when available. Never submit synthetic
    outcomes or use this write as a connection test.
    """
    operation: Literal['submit_phone_feedback'] = 'submit_phone_feedback'
    response_id: Optional[str] = Field(None, title='Response id', min_length=1, max_length=2000, description='The value of the `Response-ID` header (format `T_<uuid>`) returned by the prior Trestle API call this feedback is about. Returned by Address Validation, Reverse Address, Phone Validation, Real Contact 1.1 and 2.0, and Decision Signals. Smart CNAM, Caller Identification, and Reverse Phone do not return it. Optional, but send it whenever you have it so the feedback is linked to that lookup. Example `T_b5d031b8-e8a3-4eef-8fa8-d87d3b7e386f`')
    phone: str = Field(..., title='Phone', min_length=1, max_length=2000, description='The phone number in E.164 or local format. The default country calling code is +1 (USA). Example `2069735100`')
    name: Optional[str] = Field(None, title='Name', min_length=1, max_length=2000, description='Person or business name associated with the phone number. Optional. Example `Waidong Syrws`')
    phone_status: Optional[Literal['Connected', 'Disconnected']] = Field(None, title='Phone status', min_length=1, max_length=2000, description='Live-call status for the phone number: `Connected` or `Disconnected` (case-insensitive). Optional. Any other value is rejected with `status: failed`.')
    phone_right_party_contact: Optional[StrictBool] = Field(None, title='Phone right party contact', description='True if the call confirmed the number belongs to the right party. Optional. Any value other than true or false is rejected with `status: failed`.')


class GetPhoneValidation(_Input):
    """Validate a phone number and get metadata."""
    operation: Literal['get_phone_validation'] = 'get_phone_validation'
    phone: str = Field(..., title='Phone', min_length=1, max_length=2000, description='Phone number in E.164 or local format. Example `2069735100`')
    phone_country_hint: Optional[str] = Field(None, title='Phone country hint', alias='phone.country_hint', min_length=1, max_length=2000, description='ISO-3166 alpha-2 country code of the phone number, any case, used to read a number given in local format. Example `US`')
    add_ons: Optional[list[Literal['litigator_checks']]] = Field(None, title='Add ons', max_length=1, description='Comma-separated add-ons to enable. Options: `litigator_checks` (TCPA litigator detection, returned under `add_ons.litigator_checks`). Additional charges apply. Example `litigator_checks`')
    source_id: Optional[str] = Field(None, title='Source id', min_length=1, max_length=255, description='Optional identifier used to group queries by source, campaign, channel, or cohort. Maximum length is 255 characters. Use only letters, numbers, spaces, and `. _ - : / | #`; the value cannot begin with `-`. An invalid value does not fail the request: it is dropped and a warning is added.')


class GetRealContactV11(_Input):
    """Verify and grade a lead's contact information."""
    operation: Literal['get_real_contact_v1_1'] = 'get_real_contact_v1_1'
    name: str = Field(..., title='Name', min_length=1, max_length=2000, description='The name of the person to search. Example `John Doe`')
    first_name: Optional[str] = Field(None, title='First name', min_length=1, max_length=2000, description='The first name of the person to search. Example `John`')
    last_name: Optional[str] = Field(None, title='Last name', min_length=1, max_length=2000, description='The last name of the person to search. Example `Doe`')
    business_name: Optional[str] = Field(None, title='Business name', alias='business.name', min_length=1, max_length=2000, description='The business name to search. Example `The Golden Company`')
    phone: str = Field(..., title='Phone', min_length=1, max_length=2000, description='The phone number provided by the lead on the web form. Example `4259853735`')
    email: Optional[str] = Field(None, title='Email', min_length=1, max_length=2000, description='The email provided by the lead on the web form. Example `john.doe@example.com`')
    address_street_line_1: Optional[str] = Field(None, title='Address street line 1', alias='address.street_line_1', min_length=1, max_length=2000, description='The first line of the street part of the address. Example `100 Syrws St`')
    address_street_line_2: Optional[str] = Field(None, title='Address street line 2', alias='address.street_line_2', min_length=1, max_length=2000, description='The second line of the street part of the address. Example `Apt 4B`')
    address_city: Optional[str] = Field(None, title='Address city', alias='address.city', min_length=1, max_length=2000, description='The name of the city. Example `Lynden`')
    address_state_code: Optional[str] = Field(None, title='Address state code', alias='address.state_code', min_length=1, max_length=2000, description='Two-letter state code, any case, or the full state name (for example `Washington`). Example `WA`')
    address_postal_code: Optional[str] = Field(None, title='Address postal code', alias='address.postal_code', min_length=1, max_length=2000, description='The postal code: a 5-digit ZIP (`98229`) or a ZIP+4, with or without the dash (`98229-1234` or `982291234`). Example `98229`')
    address_country_code: Optional[str] = Field(None, title='Address country code', alias='address.country_code', min_length=1, max_length=2000, description='ISO-3166 alpha-2 country code of the address. Example `US`')
    ip_address: Optional[str] = Field(None, title='Ip address', min_length=1, max_length=2000, description='The IP address from which the lead signed up on the web form. Version 1.1 returns no IP results; use version 2.0 for IP trust signals. Example `192.0.0.1`')
    add_ons: Optional[list[Literal['email_checks_deliverability', 'email_checks_age', 'litigator_checks']]] = Field(None, title='Add ons', max_length=3, description='Comma-separated add-ons to enable. Options: `email_checks_deliverability` (email deliverability), `email_checks_age` (email age score), and `litigator_checks` (TCPA litigator detection). Additional charges apply. Example `litigator_checks,email_checks_deliverability`')


class GetRealContact(_Input):
    """Verify and grade a lead's contact information."""
    operation: Literal['get_real_contact'] = 'get_real_contact'
    name: str = Field(..., title='Name', min_length=1, max_length=2000, description='The name of the person to search. Example `John Doe`')
    first_name: Optional[str] = Field(None, title='First name', min_length=1, max_length=2000, description='The first name of the person to search. Example `John`')
    last_name: Optional[str] = Field(None, title='Last name', min_length=1, max_length=2000, description='The last name of the person to search. Example `Doe`')
    business_name: Optional[str] = Field(None, title='Business name', alias='business.name', min_length=1, max_length=2000, description='The business name to search. Example `The Golden Company`')
    phone: str = Field(..., title='Phone', min_length=1, max_length=2000, description='The phone number provided by the lead on the web form. Example `4259853735`')
    email: Optional[str] = Field(None, title='Email', min_length=1, max_length=2000, description='The email provided by the lead on the web form. Example `john.doe@example.com`')
    address_street_line_1: Optional[str] = Field(None, title='Address street line 1', alias='address.street_line_1', min_length=1, max_length=2000, description='The first line of the street part of the address. Example `100 Syrws St`')
    address_street_line_2: Optional[str] = Field(None, title='Address street line 2', alias='address.street_line_2', min_length=1, max_length=2000, description='The second line of the street part of the address. Example `Apt 4B`')
    address_city: Optional[str] = Field(None, title='Address city', alias='address.city', min_length=1, max_length=2000, description='The name of the city. Example `Lynden`')
    address_state_code: Optional[str] = Field(None, title='Address state code', alias='address.state_code', min_length=1, max_length=2000, description='Two-letter state code, any case, or the full state name (for example `Washington`). Example `WA`')
    address_postal_code: Optional[str] = Field(None, title='Address postal code', alias='address.postal_code', min_length=1, max_length=2000, description='The postal code: a 5-digit ZIP (`98229`) or a ZIP+4, with or without the dash (`98229-1234` or `982291234`). Example `98229`')
    address_country_code: Optional[str] = Field(None, title='Address country code', alias='address.country_code', min_length=1, max_length=2000, description='ISO-3166 alpha-2 country code of the address. Example `US`')
    ip_address: Optional[str] = Field(None, title='Ip address', min_length=1, max_length=2000, description='The IPv4 or IPv6 address captured at the time of interaction (web form, sign up, etc.). Example `192.0.0.1`')
    add_ons: Optional[list[Literal['email_checks_deliverability', 'email_checks_age', 'litigator_checks']]] = Field(None, title='Add ons', max_length=3, description='Comma-separated add-ons to enable. Options: `email_checks_deliverability` (email deliverability), `email_checks_age` (email age score), and `litigator_checks` (TCPA litigator detection). Additional charges apply. Example `litigator_checks,email_checks_deliverability`')
    source_id: Optional[str] = Field(None, title='Source id', min_length=1, max_length=255, description='Optional identifier used to group queries by source, campaign, channel, or cohort. Maximum length is 255 characters. Use only letters, numbers, spaces, and `. _ - : / | #`; the value cannot begin with `-`. An invalid value does not fail the request: it is dropped and a warning is added.')


class GetReverseAddress(_Input):
    """Look up residents at a street address."""
    operation: Literal['get_reverse_address'] = 'get_reverse_address'
    street_line_1: Optional[str] = Field(None, title='Street line 1', min_length=1, max_length=1000, description='The first line of the street part of the address. Needed, together with `postal_code` or `state_code`, for a lookup. Example `100 Syrws St`')
    street_line_2: Optional[str] = Field(None, title='Street line 2', min_length=1, max_length=1000, description='The second line of the street part of the address, for example a suite or apartment number. Example `Ste 1`')
    city: Optional[str] = Field(None, title='City', min_length=1, max_length=500, description='The name of the city. Example `Seattle`')
    state_code: Optional[str] = Field(None, title='State code', min_length=1, max_length=100, description='Two-letter state code, any case. Either `state_code` or `postal_code` is needed for a lookup. Example `WA`')
    postal_code: Optional[str] = Field(None, title='Postal code', min_length=1, max_length=100, description='The postal code: a 5-digit ZIP (`98101`) or a ZIP+4, with or without the dash (`98101-1234` or `981011234`). The response always returns the 5-digit ZIP in `postal_code` and the 4-digit extension in `zip4`. Either `postal_code` or `state_code` is needed for a lookup. Example `98101`')
    country_code: Optional[str] = Field(None, title='Country code', min_length=1, max_length=100, description='ISO-3166 alpha-2 country code of the address. Example `US`')

    @model_validator(mode="after")
    def useful_address(self):
        if not self.street_line_1 or not (self.postal_code or self.state_code):
            raise ValueError("Provide street line 1 and either postal code or state code")
        return self


class GetReversePhone(_Input):
    """Find all owners of a phone number."""
    operation: Literal['get_reverse_phone'] = 'get_reverse_phone'
    phone: str = Field(..., title='Phone', min_length=1, max_length=2000, description='Phone number in E.164 or local format. The default country calling code is +1 (USA). Example `2069735100`')
    phone_country_hint: Optional[str] = Field(None, title='Phone country hint', alias='phone.country_hint', min_length=1, max_length=2000, description='ISO-3166 alpha-2 country code of the phone number, any case. Example `US`')
    phone_name_hint: Optional[str] = Field(None, title='Phone name hint', alias='phone.name_hint', min_length=1, max_length=2000, description="Person or business name associated with the phone number. If multiple names are associated with the phone in Trestle's database, this name is ranked higher. Example `John Doe`")
    phone_postal_code_hint: Optional[str] = Field(None, title='Phone postal code hint', alias='phone.postal_code_hint', min_length=1, max_length=2000, description="Postal code of the subscriber address associated with the phone number. If multiple names or addresses are associated with the phone in Trestle's database, this postal code is used to rank the matching name and address higher. Example `98264`")


class GetSmartCnam(_Input):
    """Get the name associated with a phone number."""
    operation: Literal['get_smart_cnam'] = 'get_smart_cnam'
    phone: str = Field(..., title='Phone', min_length=1, max_length=2000, description='Phone number in E.164 or local format. Example `2069735100`')
    phone_name_hint: Optional[str] = Field(None, title='Phone name hint', alias='phone.name_hint', min_length=1, max_length=2000, description='Person or business name associated with the phone number. If multiple names are associated with the phone in the Trestle database, this name is ranked higher. Example `Waidong Syrws`')
    phone_postal_code_hint: Optional[str] = Field(None, title='Phone postal code hint', alias='phone.postal_code_hint', min_length=1, max_length=2000, description='Postal code of the subscriber address associated with the phone number. If multiple names or addresses are associated with the phone in the Trestle database, this postal code is used to rank the matching name higher. Example `98264`')
    add_ons: Optional[list[Literal['spam_checks']]] = Field(None, title='Add ons', max_length=1, description='Comma-separated add-ons to enable. Options: `spam_checks` (spam and scam detection, returned under `add_ons.spam_checks`). Additional charges apply. Example `spam_checks`')


TrestleConfig = Annotated[Union[CheckConnection, GetAddressValidation, GetCallerIdentification, GetDecisionSignals, SubmitPhoneFeedback, GetPhoneValidation, GetRealContactV11, GetRealContact, GetReverseAddress, GetReversePhone, GetSmartCnam], Field(discriminator="operation")]


class TrestleFullConfig(NodeConfig[TrestleConfig, TrestleAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'get_address_validation': ('GET', '/3.0/location_intel'), 'get_caller_identification': ('GET', '/3.1/caller_id'), 'get_decision_signals': ('GET', '/1.0/decision_signals'), 'submit_phone_feedback': ('POST', '/1.0/phone_feedback'), 'get_phone_validation': ('GET', '/3.0/phone_intel'), 'get_real_contact_v1_1': ('GET', '/1.1/real_contact'), 'get_real_contact': ('GET', '/2.0/real_contact'), 'get_reverse_address': ('GET', '/3.1/location'), 'get_reverse_phone': ('GET', '/3.2/phone'), 'get_smart_cnam': ('GET', '/3.1/cnam')}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    return value


class TrestleNode(WorkflowNode):
    integration_type = "automation-trestle"
    connection_evidence = ConnectionEvidence(
        operation="check_connection", noun="Trestle Phone Validation API", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return TrestleFullConfig

    async def execute(self, inputs):
        config = self.config
        if not config.credentials:
            raise ValueError("Connect a Trestle API key")
        op = config.config
        check = op.operation == "check_connection"
        action = "get_phone_validation" if check else op.operation
        method, path = ROUTES[action]
        values = {"phone": "2069735100"} if check else op.model_dump(by_alias=True, exclude_none=True, exclude={"operation"})
        # OpenAPI form/explode=false query arrays use comma-separated values.
        params = {key: ",".join(value) if isinstance(value, list) else str(value).lower() if isinstance(value, bool) else value for key, value in values.items()}
        secret = config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"x-api-key": secret, "Accept": "application/json"},
                    **({"json": values} if method == "POST" else {"params": params}))
        except httpx.HTTPError:
            # A timed-out feedback write might have been accepted; never retry it automatically.
            return {"status": "error", "error": "Trestle request did not complete", "outcome_unknown": method == "POST"}
        if len(response.content) > 5_000_000:
            return {"status": "error", "error": "Trestle response exceeds the size limit"}
        try:
            data = response.json()
        except ValueError:
            return {"status": "error", "http_status": response.status_code, "error": "Trestle returned a non-JSON response"}
        data = _redact(data, secret)
        if not isinstance(data, dict):
            return {"status": "error", "error": "Trestle returned an unexpected response shape"}
        result = {"data": data, "http_status": response.status_code}
        if response.status_code != 200:
            return {**result, "status": "error", "error": data.get("message") or data.get("error") or "Trestle rejected the request"}
        if method == "POST" and data.get("status") != "success":
            return {**result, "status": "error", "error": data.get("message") or "Trestle did not accept phone feedback", "feedback_accepted": False}
        partial = bool(data.get("error") or data.get("errors") or data.get("warnings"))
        if check and (partial or type(data.get("is_valid")) is not bool):
            return {**result, "status": "error", "error": "Trestle returned an incomplete connection lookup"}
        return {**result, "status": "success", "partial": partial,
            "response_id": response.headers.get("Response-ID"),
            **({"feedback_accepted": True} if method == "POST" else {})}
