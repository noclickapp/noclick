"""obono RKSV API 1.4.0.0.

Contract: https://app.obono.at/api/docs/api.yml
Bearer prefix: https://app.obono.at/api/docs/ (Swagger authorization setup).
No automatic retries: receipt UUIDs are chosen by the caller for reconciliation.
"""
import base64
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin


class ObonoTokenCredential(BaseModel):
    credential_type: Literal["obono_token"] = Field("obono_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access Token", json_schema_extra={"ui:widget": "password"})
    register_uuid: str = Field(..., min_length=1, title="Cash Register UUID")
    model_config = ConfigDict(json_schema_extra={
        "title": "obono Access Token",
        "x-credential-url": "https://app.obono.at/api/docs/",
        "x-credential-instructions": "Paste the accessToken and registrierkasseUuid returned by obono's GET /api/v1/auth with your username and password. Paste the token without Bearer. Tokens are not refreshed automatically; replace an expired token here.",
    })

    @field_validator("access_token")
    @classmethod
    def clean_token(cls, value):
        value = value.strip()
        if value.lower().startswith("bearer "):
            value = value[7:].strip()
        if not value or any(c.isspace() for c in value):
            raise ValueError("Paste a token without whitespace")
        return value

    @field_validator("register_uuid")
    @classmethod
    def clean_register(cls, value):
        value = value.strip()
        if not value or any(c in value for c in "/?#\\"):
            raise ValueError("Paste the cash register UUID, not a URL")
        return value


@dataclass(frozen=True)
class Operation:
    label: str
    method: str
    path: str
    query: tuple[str, ...] = ()
    media: str = "application/json"


REGISTER = "/registrierkassen/{register_uuid}"
RECEIPT = REGISTER + "/belege/{receipt_uuid}"
DATES = ("before", "after")
OPERATIONS = {
    "get_register": Operation("Get Cash Register", "GET", REGISTER),
    "list_receipts": Operation("List Receipts", "GET", REGISTER + "/belege",
        ("format", "order", "limit", "offset", *DATES, "gte", "lte")),
    "create_receipt": Operation("Sign and Store Receipt", "PUT", RECEIPT),
    "get_receipt": Operation("Get Receipt", "GET", RECEIPT),
    "create_closing_receipt": Operation("Create Closing Receipt", "POST", REGISTER + "/abschluss"),
    "list_monthly_receipts": Operation("List Monthly Receipts", "GET", REGISTER + "/monatsbelege", ("year", "month")),
    "get_dep": Operation("Get Data Collection Protocol", "GET", REGISTER + "/dep"),
    "export_receipt_pdf": Operation("Export Receipt PDF", "GET", "/export/pdf/belege/{receipt_uuid}", media="application/pdf"),
    "export_receipt_qr": Operation("Export Receipt QR Code", "GET", "/export/qr/belege/{receipt_uuid}", media="image/png"),
    "export_receipt_html": Operation("Export Receipt HTML", "GET", "/export/html/belege/{receipt_uuid}", media="text/html"),
    "export_thermal_print": Operation("Export Thermal Print", "GET", "/export/thermal-print/belege/{receipt_uuid}",
        ("qr", "width", "dialect", "encoding"), "application/octet-stream"),
    "export_gobd": Operation("Export GoBD Archive", "GET", "/export/gobd" + REGISTER, DATES, "application/zip"),
    "export_excel": Operation("Export Receipts as Excel", "GET", "/export/xls" + REGISTER + "/belege", DATES, "application/vnd.ms-excel"),
    "export_csv": Operation("Export Receipts as CSV", "GET", "/export/csv" + REGISTER + "/belege", (*DATES, "posten"), "text/csv"),
    "export_dep7": Operation("Export DEP7", "GET", "/export/dep7" + REGISTER + "/belege", DATES),
    "export_dep131": Operation("Export DEP131", "GET", "/export/dep131" + REGISTER + "/belege", DATES, "text/csv"),
}


class ReceiptItem(BaseModel):
    description: str = Field(..., alias="Bezeichnung")
    tax_rate: Literal["NORMAL", "ERMAESSIGT1", "ERMAESSIGT2", "ERMAESSIGT3", "BESONDERS", "NULL"] = Field(..., alias="Satz")
    quantity: int = Field(..., alias="Menge")
    net_cents: int = Field(..., alias="NettoBetrag")
    gross_cents: int = Field(..., alias="BruttoBetrag")
    external_series: Optional[str] = Field(None, alias="Externer-Beleg-Belegkreis")
    external_label: Optional[str] = Field(None, alias="Externer-Beleg-Bezeichnung")
    external_reference: Optional[str] = Field(None, alias="Externer-Beleg-Referenz")


class Payment(BaseModel):
    description: str = Field(..., alias="Bezeichnung")
    amount_cents: int = Field(..., alias="Betrag")
    reference: Optional[str] = Field(None, alias="Referenz")


class Discount(BaseModel):
    description: str = Field(..., alias="Bezeichnung")
    net_cents: int = Field(..., alias="Betrag-Netto")
    gross_cents: int = Field(..., alias="Betrag-Brutto")
    tax_rate: Optional[Literal["NORMAL", "ERMAESSIGT1", "ERMAESSIGT2", "ERMAESSIGT3", "BESONDERS", "NULL"]] = Field(None, alias="Satz")


class ReceiptData(BaseModel):
    """Provider field names; monetary amounts are integer cents."""
    model_config = ConfigDict(extra="forbid")
    items: Optional[list[ReceiptItem]] = Field(None, alias="Posten")
    payments: Optional[list[Payment]] = Field(None, alias="Zahlungen")
    discounts: Optional[list[Discount]] = Field(None, alias="Rabatte")
    company_name: Optional[str] = Field(None, alias="Unternehmen-Name")
    company_id: Optional[str] = Field(None, alias="Unternehmen-ID")
    company_id_type: Optional[Literal["steuernummer", "uid", "gln"]] = Field(None, alias="Unternehmen-ID-Typ")
    address1: Optional[str] = Field(None, alias="Unternehmen-Adresse1")
    address2: Optional[str] = Field(None, alias="Unternehmen-Adresse2")
    postal_code: Optional[str] = Field(None, alias="Unternehmen-PLZ")
    city: Optional[str] = Field(None, alias="Unternehmen-Ort")
    header: Optional[str] = Field(None, alias="Unternehmen-Kopfzeile")
    footer: Optional[str] = Field(None, alias="Unternehmen-Fusszeile")
    notes: Optional[list[str]] = Field(None, alias="Notizen")
    training: Optional[bool] = Field(None, alias="Training")
    cancellation: Optional[bool] = Field(None, alias="Storno")
    cancelled_receipt_uuid: Optional[UUID] = Field(None, alias="Storno-Beleg-UUID")
    cancellation_text: Optional[str] = Field(None, alias="Storno-Text")
    customer: Optional[str] = Field(None, alias="Kunde")
    external_series: Optional[str] = Field(None, alias="Externer-Beleg-Belegkreis")
    external_label: Optional[str] = Field(None, alias="Externer-Beleg-Bezeichnung")
    external_reference: Optional[str] = Field(None, alias="Externer-Beleg-Referenz")


class ClosingData(BaseModel):
    start: str = Field(..., alias="Abschluss-Beginn-Datum-Uhrzeit")
    end: str = Field(..., alias="Abschluss-Ende-Datum-Uhrzeit")


QUERY_TYPES = {
    "format": (Literal["beleg", "export", "uuidlist"], "beleg"),
    "order": (Literal["asc", "desc"], None), "limit": (int, None), "offset": (int, None),
    "before": (str, None), "after": (str, None), "gte": (int, None), "lte": (int, None),
    "year": (int, None), "month": (int, None), "qr": (bool, None), "width": (int, None),
    "dialect": (Literal["escpos", "escposlite", "star", "text"], None),
    "encoding": (Literal["raw", "base64"], None), "posten": (bool, None),
}


def _make_config(name, op):
    fields: dict[str, Any] = {}
    if "{receipt_uuid}" in op.path:
        fields["receipt_uuid"] = (str, Field(..., min_length=1, title="Receipt UUID",
            description="For a new receipt, choose a new UUID and keep it to reconcile timeouts or conflicts."))
    for key in op.query:
        kind, default = QUERY_TYPES[key]
        fields[key] = (kind if default is not None else Optional[kind], Field(default))
    if name == "create_receipt":
        fields["receipt_data"] = (ReceiptData, Field(..., title="Receipt Data", description="RKSV receipt data using obono's German field names; amounts in cents."))
    elif name == "create_closing_receipt":
        fields["closing_data"] = (ClosingData, Field(..., title="Closing Period"))
    return create_model("Obono" + "".join(p.title() for p in name.split("_")) + "Config", __module__=__name__,
        operation=(Literal[name], Field(name, json_schema_extra={"const": name, "ui:hidden": True,
            "x-display-name": op.label, "x-category": "Exports" if name.startswith("export_") else "Receipts",
            "x-is-trigger": False})), **fields)


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class ObonoOnNewReceiptConfig(PollTriggerConfigBase):
    operation: Literal["on_new_receipt"] = Field("on_new_receipt", json_schema_extra={
        "const": "on_new_receipt", "ui:hidden": True, "x-display-name": "On New Receipt",
        "x-is-trigger": True, "x-category": "Triggers"})
    register_uuid: str = Field(..., min_length=1, title="Cash Register UUID",
        description="The cash register to monitor. Copy the UUID from your obono connection.")
    after: Optional[str] = Field(None, description="Only receipts saved after this date and time. Omit to monitor all receipts in the connected register.")


ObonoConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (ObonoOnNewReceiptConfig,)], Field(discriminator="operation")]


class ObonoNodeConfig(NodeConfig[ObonoConfig, ObonoTokenCredential]):
    pass


class ObonoNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-obono"
    connection_evidence = ConnectionEvidence(identity_operation="get_register", noun="cash register",
        identity_keys=("Kassen-ID", "_uuid"))

    @classmethod
    def get_config_model(cls):
        return ObonoNodeConfig

    @staticmethod
    async def _request(credential, op, *, receipt_uuid=None, params=None, body=None):
        path = op.path.replace("{register_uuid}", quote(credential.register_uuid, safe=""))
        if receipt_uuid is not None:
            path = path.replace("{receipt_uuid}", quote(receipt_uuid, safe=""))
        # Public receipt export routes deliberately carry no Authorization header.
        public = op.path.startswith("/export/") and "/belege/{receipt_uuid}" in op.path
        headers = {"Accept": op.media}
        if not public:
            headers["Authorization"] = "Bearer " + credential.access_token
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(op.method, "https://app.obono.at/api/v1" + path,
                headers=headers, params=params or None, json=body)
        if response.status_code >= 300:
            # Keep provider rejection text while avoiding token reflection.
            detail = response.text.replace(credential.access_token, "[redacted]")[:2000]
            raise ValueError(f"obono API {response.status_code}: {detail}")
        if not response.content:
            return {"http_status": response.status_code, "location": response.headers.get("Location")}
        if op.media == "application/json":
            return response.json()
        if op.media.startswith("text/"):
            return {"content": response.text, "content_type": op.media}
        return {"content_base64": base64.b64encode(response.content).decode(), "content_type": op.media}

    async def _poll_receipts(self, credential, config):
        # The watched resource is declared in config so the shared poll family
        # rotates its baseline when the person selects another cash register.
        credential = credential.model_copy(update={"register_uuid": config.register_uuid})
        items, offset = [], 0
        while True:
            params = {"format": "beleg", "order": "asc", "limit": 100, "offset": offset}
            if config.after is not None:
                params["after"] = config.after
            data = await self._request(credential, OPERATIONS["list_receipts"], params=params)
            if not isinstance(data, dict) or not isinstance(data.get("Belege"), list):
                raise ValueError("obono receipt list must contain Belege")
            page = data["Belege"]
            if any(not isinstance(item, dict) or not isinstance(item.get("_uuid"), str) or not item["_uuid"] for item in page):
                raise ValueError("obono receipt is missing its UUID")
            items.extend(page)
            if len(items) > 10000:
                raise ValueError("More than 10,000 receipts; set the trigger's after filter to a recent date")
            if len(page) < 100:
                break
            offset += 100
        fresh = await self._filter_unseen(items, lambda item: item["_uuid"])
        return {"receipts": fresh, "new_receipt_count": len(fresh), "register_uuid": credential.register_uuid}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_receipt_count")) if config.get("operation") == "on_new_receipt" else True

    @classmethod
    def resolve_agent_event(cls, output):
        receipts = output.get("receipts") if isinstance(output, dict) else None
        if not isinstance(receipts, list):
            return super().resolve_agent_event(output)
        if not receipts:
            return None
        lines = []
        for receipt in receipts[:10]:
            data = receipt.get("Belegdaten") or {}
            lines.append(f"- Receipt {data.get('Belegnummer') or receipt['_uuid']}; customer: {data.get('Kunde') or 'unspecified'}; gross cents: {data.get('Betrag-Brutto')}; date: {data.get('Beleg-Datum-Uhrzeit')}; UUID: {receipt['_uuid']}")
        return {"text": f"obono: {len(receipts)} new receipt(s) in cash register {output.get('register_uuid')}:\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect obono with an access token and cash register UUID")
        config = self.config.config
        if isinstance(config, ObonoOnNewReceiptConfig):
            return await self._poll_receipts(credential, config)
        op = OPERATIONS[config.operation]
        params = {name: getattr(config, name) for name in op.query if getattr(config, name) is not None}
        body = None
        if config.operation == "create_receipt":
            body = config.receipt_data.model_dump(mode="json", by_alias=True, exclude_none=True)
        elif config.operation == "create_closing_receipt":
            body = config.closing_data.model_dump(by_alias=True)
        data = await self._request(credential, op, receipt_uuid=getattr(config, "receipt_uuid", None), params=params, body=body)
        return {"data": data, "operation": config.operation}
