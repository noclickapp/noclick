"""US Global Mail mailbox actions and scheduled mail/scan notifications.

Requests follow the provider's OpenAPI 1.0.0 contract published at
https://docs.usglobalmail.com/openapi.json. Dashboard-only webhooks have no
registration API, so triggers use the documented time-filtered list endpoints.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class USGlobalMailCredential(BaseModel):
    model_config = ConfigDict(title="US Global Mail API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://inbox.usglobalmail.com/",
            "x-credential-instructions": "Create a dedicated API key in your US Global Mail dashboard. Paste the key without the Bearer prefix. Live keys use production; test keys use the sandbox. NoClick reads your account profile to check the connection.",
        })
    credential_type: Literal["us_global_mail_api_key"] = Field("us_global_mail_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class USGlobalMailGetAccountInput(_Input):
    """Your account profile, including name, email, status, and PMB number."""
    pass


class USGlobalMailGetMailingAddressInput(_Input):
    """Your current USGM address, including PMB number."""
    pass


class USGlobalMailListMailsInput(_Input):
    """List your mail items with filtering, search, sorting and cursor pagination."""
    limit: int | None = Field(25, title='Limit', gt=0, le=100)
    cursor: str | None = Field(None, title='Cursor', min_length=1)
    status: list[Literal['inbox', 'archived', 'quarantine', 'discard_request']] | None = Field(None, title='Status')
    mail_type: list[Literal['letter', 'large_letter', 'magazine', 'package', 'softpak', 'catalog', 'distribution', 'fulfillment', 'inventory']] | None = Field(None, title='Mail type')
    folder_id: int | None = Field(None, title='Folder id', le=9007199254740991, gt=0)
    search: str | None = Field(None, title='Search', min_length=1, max_length=100)
    scan_status: list[Literal['in_process', 'cancelled', 'rejected', 'completed', 'deleted', 'restoring', 'none']] | None = Field(None, title='Scan status')
    sort: Literal['newest', 'oldest'] | None = Field(None, title='Sort')
    arrived: Literal['week', 'month', 'half_year', 'year'] | None = Field(None, title='Arrived')
    is_read: Literal['true', 'false'] | None = Field(None, title='Is read')


class USGlobalMailGetMailInput(_Input):
    """Retrieve full detail for one mail item, including dimensions, weight and folder."""
    mail_id: str = Field(..., title='Mail id', min_length=1, max_length=512)


class USGlobalMailUpdateMailInput(_Input):
    """Mark the item read/unread and/or move it into a folder."""
    mail_id: str = Field(..., title='Mail id', min_length=1, max_length=512)
    is_read: bool | None = Field(None, title='Is read')
    destination_folder_id: str | None = Field(None, title='Destination folder ID', description='Move the item to this folder. Pass null to remove it from its folder; omit to leave it unchanged.', pattern='^\\d+$')

    @model_validator(mode="after")
    def changes(self):
        if self.is_read is None and "destination_folder_id" not in self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self


class USGlobalMailArchiveMailInput(_Input):
    """Move the item out of your active inbox into the archive."""
    mail_id: str = Field(..., title='Mail id', min_length=1, max_length=512)


class USGlobalMailUnarchiveMailInput(_Input):
    """Restore an archived item back to its previous inbox status."""
    mail_id: str = Field(..., title='Mail id', min_length=1, max_length=512)


class USGlobalMailDiscardMailInput(_Input):
    """Request the mailroom to discard the physical item; destructive, reverse with undiscard within 7 days after the discard request. After 7 days the mail item will be permanently and securely shredded and discarded."""
    mail_id: str = Field(..., title='Mail id', min_length=1, max_length=512)


class USGlobalMailUndiscardMailInput(_Input):
    """Cancel a pending discard request and keep the item."""
    mail_id: str = Field(..., title='Mail id', min_length=1, max_length=512)


class USGlobalMailListScansInput(_Input):
    """List your scan and open-and-scan requests, with filtering, search and pagination."""
    limit: int | None = Field(25, title='Limit', gt=0, le=100)
    cursor: str | None = Field(None, title='Cursor', min_length=1)
    status: list[Literal['in_process', 'cancelled', 'rejected', 'completed', 'deleted', 'restoring']] | None = Field(None, title='Status')
    type: list[Literal['scan', 'open']] | None = Field(None, title='Type')
    mail_id: str | None = Field(None, title='Mail id', pattern='^\\d+$')
    search: str | None = Field(None, title='Search', min_length=1, max_length=100)
    sort: Literal['newest', 'oldest'] | None = Field(None, title='Sort')
    scanned: Literal['week', 'month', 'half_year', 'year'] | None = Field(None, title='Scanned')


class USGlobalMailCreateScanInput(_Input):
    """Request a scan or open-and-scan of a mail item; this is a billable action."""
    mail_id: str = Field(..., title='Mail id', pattern='^\\d+$')
    type: Literal['scan', 'open'] = Field(..., title='Type', description='`scan` scans the item as-is; `open` opens it and scans the contents.')
    instruction: str | None = Field(None, title='Instruction', min_length=1, max_length=500)
    is_expedited: bool | None = Field(False, title='Is expedited', description='Expedited handling — may incur an extra charge.')


class USGlobalMailGetScanInput(_Input):
    """Retrieve one scan request by its id, including status and AI label."""
    scan_id: UUID = Field(..., title='Scan id')


class USGlobalMailGetScanFileInput(_Input):
    """Return a short-lived signed URL to download the scanned document; fetch it promptly."""
    scan_id: UUID = Field(..., title='Scan id')


class USGlobalMailGetScanSummaryInput(_Input):
    """Return the AI-generated label and bullet summary of the scanned document."""
    scan_id: UUID = Field(..., title='Scan id')


class USGlobalMailCancelScanInput(_Input):
    """Cancel a scan request you no longer need. Valid only for scan requests in in_process status."""
    scan_id: UUID = Field(..., title='Scan id')


class USGlobalMailListShipmentsInput(_Input):
    """Read-only list of your shipment requests, filterable by type and status."""
    limit: int | None = Field(25, title='Limit', gt=0, le=100)
    cursor: str | None = Field(None, title='Cursor', min_length=1)
    type: list[Literal['shipment', 'return_to_sender', 'check_deposit', 'pickup']] | None = Field(None, title='Type')
    status: list[Literal['shipped', 'in_progress', 'payment_failed', 'rejected']] | None = Field(None, title='Status')


class USGlobalMailGetShipmentInput(_Input):
    """Read-only details of one shipment, including its packed mail items."""
    shipment_id: str = Field(..., title='Shipment id', min_length=1, max_length=512)


class USGlobalMailListFoldersInput(_Input):
    """All your mail folders, returned unpaginated."""
    pass


class USGlobalMailGetFolderInput(_Input):
    """Retrieve one mail folder by its id."""
    folder_id: str = Field(..., title='Folder id', min_length=1, max_length=512)


class USGlobalMailCreateFolderInput(_Input):
    """Create a new mail folder with a name and optional color."""
    name: str = Field(..., title='Name', min_length=1, max_length=255)
    color: str | None = Field(None, title='Color', pattern='^#[0-9a-fA-F]{6}$')


class USGlobalMailUpdateFolderInput(_Input):
    """Rename a folder or change its color."""
    folder_id: str = Field(..., title='Folder id', min_length=1, max_length=512)
    name: str | None = Field(None, title='Name', min_length=1, max_length=255)
    color: str | None = Field(None, title='Color', pattern='^#[0-9a-fA-F]{6}$')

    @model_validator(mode="after")
    def changes(self):
        if self.name is None and self.color is None:
            raise ValueError("Provide at least one field to update")
        return self


class USGlobalMailDeleteFolderInput(_Input):
    """Delete a folder and unfile its mail, which is not deleted."""
    folder_id: str = Field(..., title='Folder id', min_length=1, max_length=512)


class USGlobalMailListAddressesInput(_Input):
    """List your shipping and deposit addresses, optionally filtered by type."""
    limit: int | None = Field(25, title='Limit', gt=0, le=100)
    cursor: str | None = Field(None, title='Cursor', min_length=1)
    type: Literal['shipping', 'deposit'] | None = Field(None, title='Type')


# One action maps to one provider operation; no hidden follow-up writes.
OPERATIONS = {
    'get_account': (USGlobalMailGetAccountInput, 'GET', '/v1/account', (), (), None, 'account_get', 200),
    'get_mailing_address': (USGlobalMailGetMailingAddressInput, 'GET', '/v1/account/mailing-address', (), (), None, 'account_mailingaddress', 200),
    'list_mails': (USGlobalMailListMailsInput, 'GET', '/v1/mails', ('limit', 'cursor', 'status', 'mail_type', 'folder_id', 'search', 'scan_status', 'sort', 'arrived', 'is_read'), (), None, 'mails_list', 200),
    'get_mail': (USGlobalMailGetMailInput, 'GET', '/v1/mails/{id}', (), (), 'mail_id', 'mails_get', 200),
    'update_mail': (USGlobalMailUpdateMailInput, 'PATCH', '/v1/mails/{id}', (), ('is_read', 'destination_folder_id'), 'mail_id', 'mails_update', 200),
    'archive_mail': (USGlobalMailArchiveMailInput, 'POST', '/v1/mails/{id}/archive', (), (), 'mail_id', 'mails_archive', 200),
    'unarchive_mail': (USGlobalMailUnarchiveMailInput, 'POST', '/v1/mails/{id}/unarchive', (), (), 'mail_id', 'mails_unarchive', 200),
    'discard_mail': (USGlobalMailDiscardMailInput, 'POST', '/v1/mails/{id}/discard', (), (), 'mail_id', 'mails_discard', 200),
    'undiscard_mail': (USGlobalMailUndiscardMailInput, 'POST', '/v1/mails/{id}/undiscard', (), (), 'mail_id', 'mails_undiscard', 200),
    'list_scans': (USGlobalMailListScansInput, 'GET', '/v1/scans', ('limit', 'cursor', 'status', 'type', 'mail_id', 'search', 'sort', 'scanned'), (), None, 'scans_list', 200),
    'create_scan': (USGlobalMailCreateScanInput, 'POST', '/v1/scans', (), ('mail_id', 'type', 'instruction', 'is_expedited'), None, 'scans_create', 201),
    'get_scan': (USGlobalMailGetScanInput, 'GET', '/v1/scans/{id}', (), (), 'scan_id', 'scans_get', 200),
    'get_scan_file': (USGlobalMailGetScanFileInput, 'GET', '/v1/scans/{id}/file', (), (), 'scan_id', 'scans_file', 200),
    'get_scan_summary': (USGlobalMailGetScanSummaryInput, 'GET', '/v1/scans/{id}/summary', (), (), 'scan_id', 'scans_summary', 200),
    'cancel_scan': (USGlobalMailCancelScanInput, 'POST', '/v1/scans/{id}/cancel', (), (), 'scan_id', 'scans_cancel', 200),
    'list_shipments': (USGlobalMailListShipmentsInput, 'GET', '/v1/shipments', ('limit', 'cursor', 'type', 'status'), (), None, 'shipments_list', 200),
    'get_shipment': (USGlobalMailGetShipmentInput, 'GET', '/v1/shipments/{id}', (), (), 'shipment_id', 'shipments_get', 200),
    'list_folders': (USGlobalMailListFoldersInput, 'GET', '/v1/folders', (), (), None, 'folders_list', 200),
    'get_folder': (USGlobalMailGetFolderInput, 'GET', '/v1/folders/{id}', (), (), 'folder_id', 'folders_get', 200),
    'create_folder': (USGlobalMailCreateFolderInput, 'POST', '/v1/folders', (), ('name', 'color'), None, 'folders_create', 201),
    'update_folder': (USGlobalMailUpdateFolderInput, 'PATCH', '/v1/folders/{id}', (), ('name', 'color'), 'folder_id', 'folders_update', 200),
    'delete_folder': (USGlobalMailDeleteFolderInput, 'DELETE', '/v1/folders/{id}', (), (), 'folder_id', 'folders_delete', 204),
    'list_addresses': (USGlobalMailListAddressesInput, 'GET', '/v1/addresses', ('limit', 'cursor', 'type'), (), None, 'addresses_list', 200),
}


def _action(name, spec):
    label = name.replace("_", " ").title()
    return create_model("USGlobalMail" + "".join(p.title() for p in name.split("_")) + "Config",
        __base__=spec[0], __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={
            "const": name, "ui:hidden": True, "x-display-name": label,
            "x-category": "Mail" if "mail" in name else "Scans" if "scan" in name else "Account",
            "x-is-trigger": False,
        })))


CONFIG_MODELS = {name: _action(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class USGlobalMailOnNewMailConfig(PollTriggerConfigBase):
    operation: Literal["on_new_mail"] = Field("on_new_mail", title="On New Mail", json_schema_extra={
        "const": "on_new_mail", "ui:hidden": True, "x-is-trigger": True,
        "x-category": "Triggers", "x-display-name": "On New Mail",
    })
    arrived: Literal["week", "month", "half_year", "year"] = Field("week", title="Arrival window",
        description="Poll every page of mail arriving in this window. Existing mail is baselined when armed; only newly seen IDs fire. Resume within the window to avoid missing older arrivals.")
    folder_id: int | None = Field(None, gt=0, le=9007199254740991, title="Folder ID")


class USGlobalMailOnCompletedScanConfig(PollTriggerConfigBase):
    operation: Literal["on_completed_scan"] = Field("on_completed_scan", title="On Completed Scan", json_schema_extra={
        "const": "on_completed_scan", "ui:hidden": True, "x-is-trigger": True,
        "x-category": "Triggers", "x-display-name": "On Completed Scan",
    })
    scanned: Literal["week", "month", "half_year", "year"] = Field("week", title="Scan window",
        description="Poll completed scans in this window, including open-and-scan requests. Existing completions are baselined; each newly seen scan ID fires once. Resume within the window to avoid missing older completions.")


USGlobalMailConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (
    USGlobalMailOnNewMailConfig, USGlobalMailOnCompletedScanConfig)], Field(discriminator="operation")]


class USGlobalMailFullConfig(NodeConfig[USGlobalMailConfig, USGlobalMailCredential]):
    pass


class USGlobalMailNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-us-global-mail"
    connection_evidence = ConnectionEvidence(noun="US Global Mail account",
        identity_operation="get_account", identity_keys=("name", "email", "box_number"))

    @classmethod
    def get_config_model(cls):
        return USGlobalMailFullConfig

    async def _request(self, method, path, *, params=None, body=None, expected=200):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a US Global Mail API key")
        base = ("https://api-sandbox.usglobalmail.com" if credential.api_key.startswith("usgmk_test_")
                else "https://api.usglobalmail.com")
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, base + path, params=params, json=body,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"})
        if response.status_code != expected:
            # Report provider rejection text without disclosing an echoed credential.
            text = "Unexpected response"
            try:
                problem = response.json()
                if isinstance(problem, dict):
                    text = str(problem.get("detail") or problem.get("title") or text)[:1000]
            except ValueError:
                pass
            text = text.replace(credential.api_key, "[redacted]")
            raise ValueError(f"US Global Mail HTTP {response.status_code}: {text}")
        if expected == 204:
            return {"deleted": True}
        if len(response.content) > 5_000_000:
            raise ValueError("US Global Mail response exceeds the size limit")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("US Global Mail returned an unexpected JSON shape")
        if "data" in data and not isinstance(data["data"], list):
            raise ValueError("US Global Mail returned an invalid list")
        return data

    async def _poll(self, config):
        is_mail = config.operation == "on_new_mail"
        path = "/v1/mails" if is_mail else "/v1/scans"
        params = {"limit": 100, "sort": "newest"}
        if is_mail:
            params["arrived"] = config.arrived
            if config.folder_id is not None:
                params["folder_id"] = config.folder_id
        else:
            params.update({"scanned": config.scanned, "status": ["completed"]})
        items, cursors = [], set()
        for _ in range(20):
            page = await self._request("GET", path, params=params)
            rows = page.get("data")
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in rows):
                raise ValueError("US Global Mail poll needs a list of identified items")
            items.extend(rows)
            total = page.get("total_count")
            if type(total) is not int or total < 0:
                raise ValueError("US Global Mail returned an invalid total count")
            cursor = page.get("next_cursor")
            if len(items) >= total:
                break
            if cursor is None:
                raise ValueError("US Global Mail pagination ended before the total count; narrow the poll window")
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("US Global Mail returned a nonadvancing cursor")
            cursors.add(cursor)
            params["cursor"] = cursor
        else:
            raise ValueError("More than 2,000 items in this poll window; choose a shorter window")
        unique = list({item["id"]: item for item in items}.values())
        fresh = await self._filter_unseen(unique, lambda item: item["id"])
        return {"operation": config.operation, "data": fresh, "new_count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") not in {"on_new_mail", "on_completed_scan"}:
            return super().resolve_agent_event(output)
        rows = output.get("data")
        if not rows:
            return None
        is_mail = output["operation"] == "on_new_mail"
        lines = []
        for row in rows[:20]:
            if is_mail:
                lines.append(f"Mail {row['id']}: {row.get('mail_type') or 'mail'} from {row.get('sender_name') or 'unknown sender'} to {row.get('recipient_name') or 'your mailbox'}, arrived {row.get('arrival_date') or 'recently'}.")
            else:
                lines.append(f"Scan {row['id']} completed for mail {row['mail_id']}: {row.get('label') or 'document'}, completed {row.get('status_updated_at') or 'recently'}. Use Get Scan File to retrieve its download URL.")
        title = "New mail in your US Global Mail mailbox" if is_mail else "Completed US Global Mail scans"
        return {"text": title + ":\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if not isinstance(self.config, USGlobalMailFullConfig) or self.config.credentials is None:
            raise ValueError("Connect a US Global Mail API key")
        config = self.config.config
        if isinstance(config, (USGlobalMailOnNewMailConfig, USGlobalMailOnCompletedScanConfig)):
            return await self._poll(config)
        _, method, path, query_fields, body_fields, id_field, _, expected = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if id_field:
            identifier = values.pop(id_field)
            if identifier in {".", ".."}:
                raise ValueError("Use a resource ID")
            path = path.replace("{id}", quote(str(identifier), safe=""))
        params = {name: values[name] for name in query_fields if name in values}
        body = {("folder_id" if name == "destination_folder_id" else name): values[name]
                for name in body_fields if name in values}
        # Explicit null removes a folder; an omitted folder_id leaves it untouched.
        if config.operation == "update_mail" and "destination_folder_id" in config.model_fields_set and config.destination_folder_id is None:
            body["folder_id"] = None
        data = await self._request(method, path, params=params or None,
            body=body if body_fields else None, expected=expected)
        return {"status": "success", "operation": config.operation, "data": data}
