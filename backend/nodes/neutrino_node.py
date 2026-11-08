"""Neutrino API v3: fixed endpoints with pasted user ID and API key.

GET verification endpoints send messages/calls and use explicit send operation names.
Connection evidence checks reachability, since these APIs return generic data.
"""
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.binary_output import BinaryOutput
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class NeutrinoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Neutrino API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.neutrinoapi.com/api/api-basics/",
        "x-credential-instructions": "Copy your user ID and API key from the Neutrino API account dashboard. The key must allow the operations you use. Connection testing consumes an IP Info request and proves API reachability."})
    credential_type: Literal["neutrino_api_key"] = Field("neutrino_api_key", json_schema_extra={"ui:hidden": True})
    user_id: str = Field(..., min_length=1, title="User ID", description="Your Neutrino API account user ID.")
    api_key: str = Field(..., min_length=1, title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("user_id", "api_key", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the account value without whitespace")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

class NeutrinoGetEmailValidationConfig(_Input):
    """Parse, validate and clean an email address"""
    operation: Literal["get_email_validation"] = Field("get_email_validation", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., alias='email', description='An email address')
    fix_typos: bool = Field(False, alias='fix-typos', description='Automatically attempt to fix typos in the address')

class NeutrinoGetEmailVerificationConfig(_Input):
    """Perform in-depth SMTP based email address verification"""
    operation: Literal["get_email_verification"] = Field("get_email_verification", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., alias='email', description='An email address')
    fix_typos: bool = Field(False, alias='fix-typos', description='Automatically attempt to fix typos in the address')

class NeutrinoGetPhoneValidationConfig(_Input):
    """Parse, validate and get location information about a phone number"""
    operation: Literal["get_phone_validation"] = Field("get_phone_validation", json_schema_extra={"ui:hidden": True})
    number: str = Field(..., alias='number', description="A phone number. This can be in international format (E.164) or local format. If passing local format you must also set either the 'country-code' OR 'ip' options as well")
    country_code: str | None = Field(None, alias='country-code', description='ISO 2-letter country code, assume numbers are based in this country. If not set numbers are assumed to be in international format (with or without the leading + sign)')
    ip: str | None = Field(None, alias='ip', description='Pass in a users IP address and we will assume numbers are based in the country of the IP address')

class NeutrinoGetHlrLookupConfig(_Input):
    """Connect to the global mobile cellular network and retrieve the status of a mobile phone number"""
    operation: Literal["get_hlr_lookup"] = Field("get_hlr_lookup", json_schema_extra={"ui:hidden": True})
    number: str = Field(..., alias='number', description="A phone number. This can be in international format (E.164) or local format. If passing local format you must also set either the 'country-code' option as well")
    country_code: str | None = Field(None, alias='country-code', description='ISO 2-letter country code, assume numbers are based in this country. <br> If not set numbers are assumed to be in international format (with or without the leading + sign)')

class NeutrinoGetIpInfoConfig(_Input):
    """Get location information about an IP address and do reverse DNS (PTR) lookups"""
    operation: Literal["get_ip_info"] = Field("get_ip_info", json_schema_extra={"ui:hidden": True})
    ip: str = Field('8.8.8.8', alias='ip', description='An IPv4 or IPv6 address. Accepts standard IP notation and also CIDR notation')
    reverse_lookup: bool = Field(False, alias='reverse-lookup', description='Do a reverse DNS (PTR) lookup. This option can add extra delay to the request so only use it if you need it')

class NeutrinoGetIpProbeConfig(_Input):
    """Execute a realtime network probe against an IP address"""
    operation: Literal["get_ip_probe"] = Field("get_ip_probe", json_schema_extra={"ui:hidden": True})
    ip: str = Field(..., alias='ip', description='An IPv4 or IPv6 address. Accepts standard IP notation and also CIDR notation')

class NeutrinoGetIpBlocklistConfig(_Input):
    """Detect potentially malicious or dangerous IP addresses"""
    operation: Literal["get_ip_blocklist"] = Field("get_ip_blocklist", json_schema_extra={"ui:hidden": True})
    ip: str = Field(..., alias='ip', description='An IPv4 or IPv6 address. Accepts standard IP notation (with or without port number), CIDR notation and IPv6 compressed notation. If multiple IPs are passed using comma-separated values the first non-bogon address on the list will be checked')
    vpn_lookup: bool = Field(False, alias='vpn-lookup', description='Include public VPN provider IP addresses. <br> <b>NOTE</b>: For more advanced VPN detection including the ability to identify private and stealth VPNs use the <a href="https://www.neutrinoapi.com/api/ip-probe/">IP Probe API</a>')

class NeutrinoGetHostReputationConfig(_Input):
    """Check the reputation of an IP address, domain name or URL against a comprehensive list of blocklists"""
    operation: Literal["get_host_reputation"] = Field("get_host_reputation", json_schema_extra={"ui:hidden": True})
    host: str = Field(..., alias='host', description='An IP address, domain name, FQDN or URL. <br> If you supply a domain/URL it will be checked against the URI DNSBL lists')
    list_rating: int = Field(3, alias='list-rating', description='Only check lists with this rating or better')
    zones: str | None = Field(None, alias='zones', description='Only check these DNSBL zones/hosts. Multiple zones can be supplied as comma-separated values')

class NeutrinoGetDomainLookupConfig(_Input):
    """Retrieve domain name details and detect potentially malicious or dangerous domains"""
    operation: Literal["get_domain_lookup"] = Field("get_domain_lookup", json_schema_extra={"ui:hidden": True})
    host: str = Field(..., alias='host', description='A domain name, hostname, FQDN, URL, HTML link or email address to lookup. For internationalized domain names (IDNs) this field will accept either punycode or the raw unicode domain name, the API will always automatically return IDNs encoded into punycode')
    live: bool = Field(True, alias='live', description='For domains that we have never seen before then perform various live checks and realtime reconnaissance. <br> NOTE: this option may add additional non-deterministic delay to the request, if you require consistently fast API response times or just want to check our domain blocklists then you can disable this option')

class NeutrinoGetBinLookupConfig(_Input):
    """Perform a BIN (Bank Identification Number) or IIN (Issuer Identification Number) lookup"""
    operation: Literal["get_bin_lookup"] = Field("get_bin_lookup", json_schema_extra={"ui:hidden": True})
    bin_number: str = Field(..., alias='bin-number', description='The BIN or IIN number. This is the first 6, 8 or 10 digits of a card number, use 8 (or more) digits for the highest level of accuracy')
    customer_ip: str | None = Field(None, alias='customer-ip', description='Pass in the customers IP address and we will return some extra information about them')

class NeutrinoGetUrlInfoConfig(_Input):
    """Parse, analyze and retrieve content from the supplied URL"""
    operation: Literal["get_url_info"] = Field("get_url_info", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., alias='url', description='The URL to probe')
    fetch_content: bool = Field(False, alias='fetch-content', description='If this URL responds with html, text, json or xml then return the response. This option is useful if you want to perform further processing on the URL content (e.g. with the HTML Extract or HTML Clean APIs)')
    ignore_certificate_errors: bool = Field(False, alias='ignore-certificate-errors', description='Ignore any TLS/SSL certificate errors and load the URL anyway')
    timeout: int = Field(60, alias='timeout', description='Timeout in seconds. Give up if still trying to load the URL after this number of seconds')
    retry: int = Field(0, alias='retry', description='If the request fails for any reason try again this many times')

class NeutrinoGetUaLookupConfig(_Input):
    """Parse, validate and get detailed user-agent information from a user agent string or from client hints"""
    operation: Literal["get_ua_lookup"] = Field("get_ua_lookup", json_schema_extra={"ui:hidden": True})
    ua: str = Field(..., alias='ua', description="The user-agent string to lookup. For client hints this corresponds to the 'sec-ch-ua' header or you can also pass the JSON data directly from the 'navigator.userAgentData.getHighEntropyValues()' JavaScript API")
    ua_version: str | None = Field(None, alias='ua-version', description="For client hints this corresponds to the 'sec-ch-ua-full-version' header")
    ua_platform: str | None = Field(None, alias='ua-platform', description="For client hints this corresponds to the 'sec-ch-ua-platform' header")
    ua_platform_version: str | None = Field(None, alias='ua-platform-version', description="For client hints this corresponds to the 'sec-ch-ua-platform-version' header")
    ua_mobile: str | None = Field(None, alias='ua-mobile', description="For client hints this corresponds to the 'sec-ch-ua-mobile' header")
    device_model: str | None = Field(None, alias='device-model', description="For client hints this corresponds to the 'sec-ch-ua-model' header. <br> You can also use this parameter to lookup a device directly by its model name, model code or hardware code, on android you can get the model name from: https://developer.android.com/reference/android/os/Build.html#MODEL")
    device_brand: str | None = Field(None, alias='device-brand', description="This parameter is only used in combination with 'device-model' for direct device lookups without any user-agent data. Set this to the brand or manufacturer name, this is required for accurate device detection with ambiguous model names. On android you can get the device brand from: https://developer.android.com/reference/android/os/Build#MANUFACTURER")
    ua_arch: str | None = Field(None, alias='ua-arch', description="For client hints this corresponds to the 'sec-ch-ua-arch' header")
    ua_bitness: str | None = Field(None, alias='ua-bitness', description="For client hints this corresponds to the 'sec-ch-ua-bitness' header")
    ua_form_factors: str | None = Field(None, alias='ua-form-factors', description="For client hints this corresponds to the 'sec-ch-ua-form-factors' header")

class NeutrinoGetGeocodeAddressConfig(_Input):
    """Geocode an address, partial address or the name of a place"""
    operation: Literal["get_geocode_address"] = Field("get_geocode_address", json_schema_extra={"ui:hidden": True})
    address: str | None = Field(None, alias='address', description='The full address, partial address or name of a place to try and locate. Comma separated address components are preferred.')
    house_number: str | None = Field(None, alias='house-number', description='The house/building number to locate (for structured address searches)')
    street: str | None = Field(None, alias='street', description='The street/road name to locate (for structured address searches)')
    city: str | None = Field(None, alias='city', description='The city/town name to locate (for structured address searches)')
    county: str | None = Field(None, alias='county', description='The county/region name to locate (for structured address searches)')
    state: str | None = Field(None, alias='state', description='The state name to locate (for structured address searches)')
    postal_code: str | None = Field(None, alias='postal-code', description='The postal code to locate (for structured address searches)')
    country_code: str | None = Field(None, alias='country-code', description='Prefer results from this country code (the default is no country bias)')
    country_codes: str | None = Field(None, alias='country-codes', description="Prefer results from this list of country codes (space or comma separated values). Preference is in the order supplied, you can use the 'country-code' parameter to also set a dynamic or user supplied country code which takes precedence")
    language_code: str = Field('en', alias='language-code', description='The language to display results in, available languages are: <ul> <li>ar, de, en, es, fr, it, ja, nl, pt, ru, zh</li> </ul>')
    auto_complete: bool = Field(False, alias='auto-complete', description="Enable auto-complete for search-as-you-type and search suggestions. This option can find addresses based on partial search terms, combine with 'country-code' for country specific searches. Auto-complete works best with 'fuzzy-search' disabled for the fastest response times but can be combined if required")
    fuzzy_search: bool = Field(False, alias='fuzzy-search', description='If no matches are found for the given address, start performing a recursive fuzzy search until a geolocation is found. This option is useful for processing user supplied input that may be incomplete or have typos and where you do not mind some potential loss in precision')
    limit: int = Field(8, alias='limit', description='Limit search results to this many locations (between 1 and a maximum of 32)')

class NeutrinoGetGeocodeReverseConfig(_Input):
    """Convert a geographic coordinate (latitude and longitude) into a real world address"""
    operation: Literal["get_geocode_reverse"] = Field("get_geocode_reverse", json_schema_extra={"ui:hidden": True})
    latitude: str | None = Field(None, alias='latitude', description='The location latitude in decimal degrees format')
    longitude: str | None = Field(None, alias='longitude', description='The location longitude in decimal degrees format')
    language_code: str = Field('en', alias='language-code', description='The language to display results in, available languages are: <ul> <li>ar, de, en, es, fr, it, ja, nl, pt, ru, zh</li> </ul>')
    zoom: str = Field('address', alias='zoom', description='The zoom level to respond with: <br> <ul> <li>address - the most precise address available</li> <li>street - the street level</li> <li>city - the city level</li> <li>state - the state level</li> <li>country - the country level</li> </ul>')
    geohash: str | None = Field(None, alias='geohash', description='Reverse lookup by a geohash instead of using latitude and longitude')

class NeutrinoConvertConfig(_Input):
    """Convert currency and other numerical units between each other"""
    operation: Literal["convert"] = Field("convert", json_schema_extra={"ui:hidden": True})
    from_value: str = Field(..., alias='from-value', description='The value to convert from (e.g. 10.95)')
    from_type: str = Field(..., alias='from-type', description='The type of the value to convert from (e.g. USD)')
    to_type: str = Field(..., alias='to-type', description='The type to convert to (e.g. EUR)')
    historical_date: str | None = Field(None, alias='historical-date', description="Convert using the rate on a historical date, accepted date formats are: YYYY-MM-DD, YYYY-MM, YYYY. Historical rates are stored with daily granularity so the date format YYYY-MM-DD is preferred for the highest precision. The earliest date currently possible is: 2000-01-01. If an invalid date or a date too far into the past is supplied then the API will respond with 'valid' as false and an empty 'historical-date'")

class NeutrinoFilterBadWordsConfig(_Input):
    """Detect bad words, swear words and profanity in a given text"""
    operation: Literal["filter_bad_words"] = Field("filter_bad_words", json_schema_extra={"ui:hidden": True})
    content: str = Field(..., alias='content', description='The content to scan. This can be either a URL to load from, a file upload (multipart/form-data) or an HTML content string')
    censor_character: str | None = Field(None, alias='censor-character', description='The character to use to censor out the bad words found')
    catalog: str = Field('strict', alias='catalog', description="Which catalog of bad words to use, we currently maintain two bad word catalogs: <br> <ul> <li>strict - the largest database of bad words which includes profanity, obscenity, sexual, rude, cuss, dirty, swear and objectionable words and phrases. This catalog is suitable for environments of all ages including educational or children's content</li> <li>obscene - like the strict catalog but does not include any mild profanities, idiomatic phrases or words which are considered formal terminology. This catalog is suitable for adult environments where certain types of bad words are considered OK</li> </ul>")

class NeutrinoCleanHtmlConfig(_Input):
    """Clean and sanitize untrusted HTML"""
    operation: Literal["clean_html"] = Field("clean_html", json_schema_extra={"ui:hidden": True})
    content: str = Field(..., alias='content', description='The HTML content. This can be either a URL to load from, a file upload (multipart/form-data) or an HTML content string')
    output_type: str = Field(..., alias='output-type', description='The level of sanitization, possible values are: <br> <b>plain-text</b>: reduce the content to plain text only (no HTML tags at all) <br> <b>plain-text-markdown</b>: reduce the content to plain text only but also convert HTML links and lists into makrdown style text <br> <b>simple-text</b>: allow only very basic text formatting tags like b, em, i, strong, u <br> <b>basic-html</b>: allow advanced text formatting and hyper links <br> <b>basic-html-with-images</b>: same as basic html but also allows image tags <br> <b>advanced-html</b>: same as basic html with images but also allows many more common HTML tags like table, ul, dl, pre <br>')

class NeutrinoSendSmsVerificationConfig(_Input):
    """Send a unique security code to any mobile device via SMS"""
    operation: Literal["send_sms_verification"] = Field("send_sms_verification", json_schema_extra={"ui:hidden": True})
    number: str = Field(..., alias='number', description='The phone number to send a verification code to')
    code_length: int = Field(5, alias='code-length', description='The number of digits to use in the security code (must be between 4 and 12)')
    security_code: int | None = Field(None, alias='security-code', description='Pass in your own security code. This is useful if you have implemented TOTP or similar 2FA methods. If not set then we will generate a secure random code')
    country_code: str | None = Field(None, alias='country-code', description='ISO 2-letter country code, assume numbers are based in this country. <br> If not set numbers are assumed to be in international format (with or without the leading + sign)')
    language_code: str = Field('en', alias='language-code', description='The language to send the verification code in, available languages are: <ul> <li>de - German</li> <li>en - English</li> <li>es - Spanish</li> <li>fr - French</li> <li>it - Italian</li> <li>pt - Portuguese</li> <li>ru - Russian</li> </ul>')
    limit: int = Field(10, alias='limit', description='Limit the total number of SMS allowed to the supplied phone number, if the limit is reached within the TTL then error code 14 will be returned')
    limit_ttl: int = Field(1, alias='limit-ttl', description="Set the TTL in number of days that the 'limit' option will remember a phone number (the default is 1 day and the maximum is 365 days)")
    brand_name: str | None = Field(None, alias='brand-name', description='Set a custom brand or product name in the verification message')

class NeutrinoSendPhoneVerificationConfig(_Input):
    """Make an automated call to any valid phone number and playback a unique security code"""
    operation: Literal["send_phone_verification"] = Field("send_phone_verification", json_schema_extra={"ui:hidden": True})
    number: str = Field(..., alias='number', description='The phone number to send the verification code to')
    code_length: int = Field(6, alias='code-length', description='The number of digits to use in the security code (between 4 and 12)')
    security_code: int | None = Field(None, alias='security-code', description='Pass in your own security code. This is useful if you have implemented TOTP or similar 2FA methods. If not set then we will generate a secure random code')
    playback_delay: int = Field(800, alias='playback-delay', description='The delay in milliseconds between the playback of each security code')
    country_code: str | None = Field(None, alias='country-code', description='ISO 2-letter country code, assume numbers are based in this country. <br> If not set numbers are assumed to be in international format (with or without the leading + sign)')
    language_code: str = Field('en', alias='language-code', description='The language to playback the verification code in, available languages are: <ul> <li>de - German</li> <li>en - English</li> <li>es - Spanish</li> <li>fr - French</li> <li>it - Italian</li> <li>pt - Portuguese</li> <li>ru - Russian</li> </ul>')
    limit: int = Field(3, alias='limit', description='Limit the total number of calls allowed to the supplied phone number, if the limit is reached within the TTL then error code 14 will be returned')
    limit_ttl: int = Field(1, alias='limit-ttl', description="Set the TTL in number of days that the 'limit' option will remember a phone number (the default is 1 day and the maximum is 365 days)")

class NeutrinoVerifySecurityCodeConfig(_Input):
    """Check if a security code sent via SMS Verify or Phone Verify is valid"""
    operation: Literal["verify_security_code"] = Field("verify_security_code", json_schema_extra={"ui:hidden": True})
    security_code: str = Field(..., alias='security-code', description='The security code to verify')
    limit_by: str | None = Field(None, alias='limit-by', description='If set then enable additional brute-force protection by limiting the number of attempts by the supplied value. This can be set to any unique identifier you would like to limit by, for example a hash of the users email, phone number or IP address. Requests to this API will be ignored after approximately 10 failed verification attempts')

NeutrinoConfig = Annotated[Union[NeutrinoGetEmailValidationConfig, NeutrinoGetEmailVerificationConfig, NeutrinoGetPhoneValidationConfig, NeutrinoGetHlrLookupConfig, NeutrinoGetIpInfoConfig, NeutrinoGetIpProbeConfig, NeutrinoGetIpBlocklistConfig, NeutrinoGetHostReputationConfig, NeutrinoGetDomainLookupConfig, NeutrinoGetBinLookupConfig, NeutrinoGetUrlInfoConfig, NeutrinoGetUaLookupConfig, NeutrinoGetGeocodeAddressConfig, NeutrinoGetGeocodeReverseConfig, NeutrinoConvertConfig, NeutrinoFilterBadWordsConfig, NeutrinoCleanHtmlConfig, NeutrinoSendSmsVerificationConfig, NeutrinoSendPhoneVerificationConfig, NeutrinoVerifySecurityCodeConfig], Field(discriminator="operation")]

class NeutrinoFullConfig(NodeConfig[NeutrinoConfig, NeutrinoAPIKeyCredential]):
    pass

ROUTES = {'get_email_validation': ('GET', '/email-validate'), 'get_email_verification': ('GET', '/email-verify'), 'get_phone_validation': ('GET', '/phone-validate'), 'get_hlr_lookup': ('GET', '/hlr-lookup'), 'get_ip_info': ('GET', '/ip-info'), 'get_ip_probe': ('GET', '/ip-probe'), 'get_ip_blocklist': ('GET', '/ip-blocklist'), 'get_host_reputation': ('GET', '/host-reputation'), 'get_domain_lookup': ('GET', '/domain-lookup'), 'get_bin_lookup': ('GET', '/bin-lookup'), 'get_url_info': ('GET', '/url-info'), 'get_ua_lookup': ('GET', '/ua-lookup'), 'get_geocode_address': ('GET', '/geocode-address'), 'get_geocode_reverse': ('GET', '/geocode-reverse'), 'convert': ('GET', '/convert'), 'filter_bad_words': ('POST', '/bad-word-filter'), 'clean_html': ('POST', '/html-clean'), 'send_sms_verification': ('GET', '/sms-verify'), 'send_phone_verification': ('GET', '/phone-verify'), 'verify_security_code': ('GET', '/verify-security-code')}

class NeutrinoNode(WorkflowNode):
    integration_type = "automation-neutrino"
    connection_evidence = ConnectionEvidence(noun="Neutrino API", operation="get_ip_info", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return NeutrinoFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Neutrino API key")
        credential = self.config.credentials
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(by_alias=True, exclude_none=True, exclude={"operation"})
        values = {k: ("true" if v else "false") if isinstance(v, bool) else v for k, v in values.items()}
        headers = {"user-id": credential.user_id, "api-key": credential.api_key, "Accept": "application/json"}
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://neutrinoapi.net" + path, headers=headers,
                **({"params": values} if method == "GET" else {"data": values}))
        response.raise_for_status()
        if config.operation == "clean_html":
            return {"status": "success", "file": BinaryOutput(data=response.content,
                content_type=response.headers.get("content-type", "text/plain"), filename="html-clean.txt")}
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a Neutrino JSON object")
        if "api-error" in body:
            return {"status": "error", "error": body.get("api-error-msg"), "code": body.get("api-error")}
        return {"status": "success", "data": body}
