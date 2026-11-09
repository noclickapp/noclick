"""ME-QR API v1.0.0: token-authenticated QR codes, folders and scan analytics.

Contract: https://me-qr.com/api/doc.json. Each operation makes one request.
QR writes request JSON metadata rather than binary images; deletes are soft.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MEQRCredential(BaseModel):
    model_config = ConfigDict(title="ME-QR API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://me-qr.com/api", "x-credential-instructions":
            "Copy your API token from ME-QR's API page and paste it here. NoClick sends it in the X-AUTH-TOKEN header and checks your account's folders."})
    credential_type: Literal["me_qr_qr_code_api_token"] = Field("me_qr_qr_code_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the API token without a header prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Entry(Input):
    entry_uid: str = Field(..., min_length=1, description="Numeric ID or unique entry key from ME-QR.")

    @field_validator("entry_uid")
    @classmethod
    def identifier(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Use a numeric ID or a single unique entry key")
        return value


class FolderOptions(Input):
    folderName: str | None = None
    subfolderName: str | None = None


class ListQRCodes(Input):
    """List one page of the account's QR codes, including scan counts."""
    operation: Literal["list_qr_codes"] = "list_qr_codes"
    page: int = Field(1, ge=1)
    limit: int = Field(50, ge=1)


class ListScanEvents(Input):
    """List one page of geographic and device scan events, optionally filtered."""
    operation: Literal["list_scan_events"] = "list_scan_events"
    page: int = Field(1, ge=1)
    limit: int = Field(50, ge=1, le=1000)
    qr_uid: str | None = None
    date_from: str | None = Field(None, description="ISO 8601 start date, such as 2026-01-01.")
    date_to: str | None = Field(None, description="ISO 8601 end date, such as 2027-01-01.")
    return_shared_qrs: bool = True


class ListFolders(Input):
    """Get the authenticated account's root folders and direct subfolders."""
    operation: Literal["list_folders"] = "list_folders"


class CreateFolder(Input):
    """Create a folder or a named subfolder."""
    operation: Literal["create_folder"] = "create_folder"
    folder_name: str = Field(..., min_length=1)
    subfolder_name: str | None = None


class GetAnalytics(Entry):
    """Get analytics for one QR code."""
    operation: Literal["get_analytics"] = "get_analytics"


class DeleteEntries(Input):
    """Soft delete the specified owned QR codes or short links."""
    operation: Literal["delete_entries"] = "delete_entries"
    ids: list[str] = Field(..., min_length=1, description="Numeric IDs or unique entry keys; this is a soft deletion.")


class QRWrite(Input):
    title: str = "Qr Code"
    folder_options: FolderOptions | None = None


class LinkData(Input):
    link: str = Field(..., description="Destination URL, such as https://example.com.")


class TextData(Input):
    text: str = Field(..., description="Text with optional HTML tags.")


class EmailData(Input):
    emailTo: str = Field(..., json_schema_extra={"format": "email"})
    subject: str
    body: str = Field(..., min_length=1, max_length=500)


class WifiData(Input):
    ssid: str
    encryption: Literal["wpa/wpa2", "wpa3", "wep", "none", "raw"]
    password: str | None = Field(None, json_schema_extra={"ui:widget": "password"})


class CreateLinkQR(QRWrite):
    """Create a link QR code; return JSON metadata."""
    operation: Literal["create_link_qr"] = "create_link_qr"
    qr_fields_data: LinkData


class UpdateLinkQR(QRWrite, Entry):
    """Update a link QR code; return JSON metadata."""
    operation: Literal["update_link_qr"] = "update_link_qr"
    qr_fields_data: LinkData


class GetLinkQR(Entry):
    """Get a link QR code; return JSON metadata."""
    operation: Literal["get_link_qr"] = "get_link_qr"


class CreateTextQR(QRWrite):
    """Create a text QR code; return JSON metadata."""
    operation: Literal["create_text_qr"] = "create_text_qr"
    qr_fields_data: TextData


class UpdateTextQR(QRWrite, Entry):
    """Update a text QR code; return JSON metadata."""
    operation: Literal["update_text_qr"] = "update_text_qr"
    qr_fields_data: TextData


class GetTextQR(Entry):
    """Get a text QR code; return JSON metadata."""
    operation: Literal["get_text_qr"] = "get_text_qr"


class CreateEmailQR(QRWrite):
    """Create a email QR code; return JSON metadata."""
    operation: Literal["create_email_qr"] = "create_email_qr"
    qr_fields_data: EmailData


class UpdateEmailQR(QRWrite, Entry):
    """Update a email QR code; return JSON metadata."""
    operation: Literal["update_email_qr"] = "update_email_qr"
    qr_fields_data: EmailData


class GetEmailQR(Entry):
    """Get a email QR code; return JSON metadata."""
    operation: Literal["get_email_qr"] = "get_email_qr"


class CreateWifiQR(QRWrite):
    """Create a wifi QR code; return JSON metadata."""
    operation: Literal["create_wifi_qr"] = "create_wifi_qr"
    qr_fields_data: WifiData


class UpdateWifiQR(QRWrite, Entry):
    """Update a wifi QR code; return JSON metadata."""
    operation: Literal["update_wifi_qr"] = "update_wifi_qr"
    qr_fields_data: WifiData


class GetWifiQR(Entry):
    """Get a wifi QR code; return JSON metadata."""
    operation: Literal["get_wifi_qr"] = "get_wifi_qr"


class CreateShortLink(QRWrite):
    """Create a short link and return its metadata."""
    operation: Literal["create_short_link"] = "create_short_link"
    link: str = Field(..., description="Destination URL, such as https://example.com.")


class UpdateShortLink(QRWrite, Entry):
    """Update a short link and return its metadata."""
    operation: Literal["update_short_link"] = "update_short_link"
    link: str = Field(..., description="Destination URL, such as https://example.com.")


class GetShortLink(Entry):
    """Get a short link and return its metadata."""
    operation: Literal["get_short_link"] = "get_short_link"


MEQRConfig = Annotated[Union[
    ListQRCodes, ListScanEvents, ListFolders, CreateFolder, GetAnalytics, DeleteEntries,
    CreateLinkQR, UpdateLinkQR, GetLinkQR, CreateTextQR, UpdateTextQR, GetTextQR,
    CreateEmailQR, UpdateEmailQR, GetEmailQR, CreateWifiQR, UpdateWifiQR, GetWifiQR,
    CreateShortLink, UpdateShortLink, GetShortLink,
], Field(discriminator="operation")]


class MEQRFullConfig(NodeConfig[MEQRConfig, MEQRCredential]):
    pass


ROUTES = {
    "list_qr_codes": ("GET", "/api/qr/list/"),
    "list_scan_events": ("GET", "/api/v2/qr/statistic"),
    "list_folders": ("GET", "/api/v2/user/folders"),
    "create_folder": ("POST", "/api/v2/user/folder/create"),
    "get_analytics": ("GET", "/api/v2/qr/{entryUID}/analytics"),
    "delete_entries": ("POST", "/api/v2/qr/delete"),
    "create_link_qr": ("POST", "/api/v2/qr/link/create"),
    "update_link_qr": ("PUT", "/api/v2/qr/link/update/{entryUID}"),
    "get_link_qr": ("GET", "/api/v2/qr/link/{entryUID}"),
    "create_text_qr": ("POST", "/api/v2/qr/text/create"),
    "update_text_qr": ("PUT", "/api/v2/qr/text/update/{entryUID}"),
    "get_text_qr": ("GET", "/api/v2/qr/text/{entryUID}"),
    "create_email_qr": ("POST", "/api/v2/qr/email/create"),
    "update_email_qr": ("PUT", "/api/v2/qr/email/update/{entryUID}"),
    "get_email_qr": ("GET", "/api/v2/qr/email/{entryUID}"),
    "create_wifi_qr": ("POST", "/api/v2/qr/wifi/create"),
    "update_wifi_qr": ("PUT", "/api/v2/qr/wifi/update/{entryUID}"),
    "get_wifi_qr": ("GET", "/api/v2/qr/wifi/{entryUID}"),
    "create_short_link": ("POST", "/api/v2/short-link/create"),
    "update_short_link": ("PUT", "/api/v2/short-link/update/{entryUID}"),
    "get_short_link": ("GET", "/api/v2/short-link/{entryUID}"),
}


class MEQRQRCodeNode(WorkflowNode):
    integration_type = "automation-me-qr-qr-code"
    connection_evidence = ConnectionEvidence(noun="ME-QR folders", operation="list_folders")

    @classmethod
    def get_config_model(cls):
        return MEQRFullConfig

    async def execute(self, inputs):
        op = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a ME-QR API token")
        method, path = ROUTES[op.operation]
        if isinstance(op, Entry):
            path = path.replace("{entryUID}", quote(op.entry_uid, safe=""))
        params, body = {}, None
        if isinstance(op, ListQRCodes):
            params = {"page": op.page, "limit": op.limit}
        elif isinstance(op, ListScanEvents):
            params = {"page": op.page, "limit": op.limit, "qrUID": op.qr_uid,
                "dateFrom": op.date_from, "dateTo": op.date_to,
                "returnSharedQrs": str(op.return_shared_qrs).lower()}
            params = {k: v for k, v in params.items() if v is not None}
        elif isinstance(op, CreateFolder):
            body = {"folderName": op.folder_name}
            if op.subfolder_name is not None:
                body["subfolderName"] = op.subfolder_name
        elif isinstance(op, DeleteEntries):
            body = {"ids": op.ids}
        elif isinstance(op, QRWrite):
            body = {"title": op.title}
            if hasattr(op, "qr_fields_data"):
                body.update(qrFieldsData=op.qr_fields_data.model_dump(exclude_none=True), format="json")
            else:
                body["link"] = op.link
            if op.folder_options is not None:
                body["qrFolderOptions" if hasattr(op, "qr_fields_data") else "folderOptions"] = op.folder_options.model_dump(exclude_none=True)
        # No format on GET: the documented default is the editable QR data.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://me-qr.com" + path,
                headers={"X-AUTH-TOKEN": credential.api_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            message = response.text.replace(credential.api_token, "[redacted]")[:2000]
            return {"status": "error", "http_status": response.status_code, "error": message or "ME-QR rejected the request"}
        data = response.json() if response.content else None
        if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
            return {"status": "error", "error": str(data).replace(credential.api_token, "[redacted]")[:2000]}
        if isinstance(op, ListFolders):
            if not isinstance(data, list):
                raise ValueError("Expected ME-QR's folder array")
            return {"status": "success", "items": data}
        return {"status": "success", "data": data}
