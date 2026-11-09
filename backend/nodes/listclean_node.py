"""Listclean API v0.1.0: verification, uploads, lists, downloads and credits.

Contract: https://api.listclean.xyz/v1/spec.json
Each operation makes one request; no implicit retries, polling or pagination.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class ListcleanAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Listclean API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.listclean.xyz",
            "x-credential-instructions": "Paste an API token from your Listclean account's API access page. NoClick sends it in the X-Auth-Token header to api.listclean.xyz. Connecting reads your email lists."})
    credential_type: Literal["listclean_api_key"] = Field("listclean_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without whitespace or a header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class VerifyEmail(Input):
    """Verify single email address at a time."""
    operation: Literal['verify_email'] = Field('verify_email', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., description='', json_schema_extra={'examples': ['test@example.com']}, min_length=1)


class VerifyBatch(Input):
    """Verify batch of emails (max 3000 emails)."""
    operation: Literal['verify_batch'] = Field('verify_batch', json_schema_extra={"ui:hidden": True})
    filename: str | None = Field(None, description='Optional source filename. If omitted, the API generates a UTC filename in the format batch_upload-DD-MM-YYYY-HHMMSS-utc.csv (for example, batch_upload-05-10-2026-143025-utc.csv). A .csv extension is added when a supplied filename has no extension.', json_schema_extra={'examples': ['october-leads.csv']})
    emails: list[str] = Field(..., description='Email addresses to verify. The default limit is 3,000 addresses per request.', json_schema_extra={'examples': [['user1@example.com', 'user2@example.com']]}, min_length=1, max_length=3000)


class ListLogs(Input):
    """Get logs for all the single email verified."""
    operation: Literal['list_logs'] = Field('list_logs', json_schema_extra={"ui:hidden": True})
    start_date: str = Field(..., description='Start date of the report range. The maximum date range is 30 days.', json_schema_extra={'examples': ['2026-11-01'], 'format': 'date'}, min_length=1)
    end_date: str = Field(..., description='End date of the report range. It cannot be in the future.', json_schema_extra={'examples': ['2026-11-05'], 'format': 'date'}, min_length=1)
    email: str | None = Field(None, description='Optional email-address filter.')
    source: Literal['api', 'file_upload', 'single_email'] | None = Field(None, description='Optional verification-source filter.')
    status: Literal['clean', 'dirty', 'unknown', 'error'] | None = Field(None, description='Optional verification-status filter.')
    start: int = Field(0, description='Zero-based pagination offset.', ge=0)
    limit: int = Field(10, description='Maximum number of log records to return.', ge=1, le=100)


class ListUploads(Input):
    """Get the list of uploads (csv upload)."""
    operation: Literal['list_uploads'] = Field('list_uploads', json_schema_extra={"ui:hidden": True})


class StartUpload(Input):
    """Start the Upload (csv upload)."""
    operation: Literal['start_upload'] = Field('start_upload', json_schema_extra={"ui:hidden": True})
    filename: str = Field(..., description='', json_schema_extra={'examples': ['My file.csv']}, min_length=1)
    file_type: str = Field(..., description='', json_schema_extra={'examples': ['csv']}, min_length=1)
    total_chunk_count: int = Field(..., description='', json_schema_extra={'examples': [24]}, ge=1)
    max_chunk_size: int = Field(..., description='max size of a chunk in bytes', json_schema_extra={'examples': [64000]}, ge=1)
    separator_char: str | None = Field(None, description='character separator for csv file format', json_schema_extra={'examples': [',']})
    enclosure_char: str | None = Field(None, description='The optional enclosure parameter sets the field enclosure character (one single-byte character only).', json_schema_extra={'examples': ['"']})
    escape_char: str | None = Field(None, description='The optional escape parameter sets the escape character (at most one single-byte character). An empty value disables the escape mechanism.', json_schema_extra={'examples': ['']})
    fast_process: Literal[0, 1] | None = Field(None, description='Use 1 for fast processing without slow checks such as SMTP; 0 for full processing.')


class UploadChunk(Input):
    """Upload a Chunk [CHUNKS] (csv upload)."""
    operation: Literal['upload_chunk'] = Field('upload_chunk', json_schema_extra={"ui:hidden": True})
    chunk_sequence_number: int = Field(..., description='', json_schema_extra={'examples': [24]}, ge=1)
    content: str = Field(..., description='The base64-encoded contents of the file', json_schema_extra={'examples': ['====DYscs...==']}, min_length=1)
    md5_checksum: str | None = Field(None, description='md5 hash of file to check the integrity of the file', json_schema_extra={'examples': ['0a52067b38f4485d42eb5f7040d476b3']})
    upload_id: int = Field(..., description='', ge=1)


class GetUpload(Input):
    """Get status of a Upload."""
    operation: Literal['get_upload'] = Field('get_upload', json_schema_extra={"ui:hidden": True})
    upload_id: int = Field(..., description='', ge=1)


class ListLists(Input):
    """Get the all list info."""
    operation: Literal['list_lists'] = Field('list_lists', json_schema_extra={"ui:hidden": True})


class GetList(Input):
    """Get the single list info."""
    operation: Literal['get_list'] = Field('get_list', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., description='', ge=1)


class DeleteList(Input):
    """Delete the single list."""
    operation: Literal['delete_list'] = Field('delete_list', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., description='', ge=1)


class DownloadCsv(Input):
    """Download lists results as a csv file."""
    operation: Literal['download_csv'] = Field('download_csv', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., description='', ge=1)
    type: Literal['clean', 'dirty', 'unknown'] = Field(..., description='A type can be clean, dirty, unknown', min_length=1)


class DownloadJson(Input):
    """Download lists results as a json."""
    operation: Literal['download_json'] = Field('download_json', json_schema_extra={"ui:hidden": True})
    list_id: int = Field(..., description='', ge=1)
    type: Literal['clean', 'dirty', 'unknown'] = Field(..., description='A type can be clean, dirty, unknown', min_length=1)


class GetCredits(Input):
    """Get credits."""
    operation: Literal['get_credits'] = Field('get_credits', json_schema_extra={"ui:hidden": True})


ListcleanOperation = Annotated[Union[VerifyEmail, VerifyBatch, ListLogs, ListUploads, StartUpload, UploadChunk, GetUpload, ListLists, GetList, DeleteList, DownloadCsv, DownloadJson, GetCredits], Field(discriminator="operation")]


ROUTES = {'verify_email': ('GET', '/verify/email/{email}', ['email'], [], False), 'verify_batch': ('POST', '/verify/email/batch', [], [], True), 'list_logs': ('GET', '/logs', [], ['start_date', 'end_date', 'email', 'source', 'status', 'start', 'limit'], False), 'list_uploads': ('GET', '/uploads/', [], [], False), 'start_upload': ('POST', '/uploads/', [], [], True), 'upload_chunk': ('POST', '/uploads/{upload_id}', ['upload_id'], [], True), 'get_upload': ('GET', '/uploads/{upload_id}', ['upload_id'], [], False), 'list_lists': ('GET', '/lists/', [], [], False), 'get_list': ('GET', '/lists/{list_id}', ['list_id'], [], False), 'delete_list': ('DELETE', '/lists/{list_id}', ['list_id'], [], False), 'download_csv': ('GET', '/downloads/{list_id}/{type}', ['list_id', 'type'], [], False), 'download_json': ('GET', '/downloads/json/{list_id}/{type}', ['list_id', 'type'], [], False), 'get_credits': ('GET', '/credits', [], [], False)}


class ListcleanNodeConfig(NodeConfig[ListcleanOperation, ListcleanAPIKeyCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class ListcleanNode(WorkflowNode):
    integration_type = "automation-listclean"
    connection_evidence = ConnectionEvidence(noun="email lists", operation="list_lists", label_keys=("filename", "list_id"))

    @classmethod
    def get_config_model(cls):
        return ListcleanNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        parsed = super().parse_config(config_data)
        # An explicit empty escape character disables CSV escaping in Listclean.
        raw = config_data.get("config", {})
        if isinstance(parsed.config, StartUpload) and raw.get("escape_char") == "":
            parsed.config = parsed.config.model_copy(update={"escape_char": ""})
        return parsed

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Listclean API token")
        config = self.config.config
        method, path, path_fields, query_fields, has_body = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for name in path_fields:
            value = str(values.pop(name))
            if not value or value in {".", ".."} or any(c in value for c in "/\\?#\r\n"):
                raise ValueError("Use one email address or resource ID")
            path = path.replace("{" + name + "}", quote(value, safe=""))
        params = {name: values.pop(name) for name in query_fields if name in values}
        token = self.config.credentials.api_key
        download = config.operation in {"download_csv", "download_json"}
        try:
            async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, "https://api.listclean.xyz/v1" + path,
                    headers={"X-Auth-Token": token, "Accept": "application/octet-stream, application/json, text/csv" if download else "application/json"},
                    params=params, **({"json": values} if has_body else {}))
        except httpx.HTTPError:
            raise ValueError("Listclean request could not be confirmed; inspect writes before retrying") from None
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        data = None
        if mime == "application/json" and response.content:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Listclean returned invalid JSON") from None
        if response.status_code != 200 or isinstance(data, dict) and data.get("success") == 0:
            message = data.get("message") if isinstance(data, dict) else None
            output = {"status": "error", "http_status": response.status_code,
                "message": _redact(message, token) if isinstance(message, str) else f"Listclean returned HTTP {response.status_code}"}
        elif download:
            if mime not in {"", "application/octet-stream", "application/json", "text/csv", "text/plain"}:
                raise ValueError("Listclean did not return a results file")
            extension = "csv" if config.operation == "download_csv" else "json"
            output = {"status": "success", "file": BinaryOutput(response.content,
                "text/csv" if extension == "csv" else "application/json",
                f"listclean-{config.list_id}-{config.type}.{extension}")}
        else:
            if not isinstance(data, dict) or type(data.get("success")) is not int or data["success"] != 1:
                raise ValueError("Listclean did not confirm success")
            if config.operation == "get_credits":
                account = data.get("data")
                if not isinstance(account, dict) or type(account.get("credits")) is not int or account["credits"] < 0:
                    raise ValueError("Listclean omitted the account credit balance")
            if config.operation == "list_lists":
                account = data.get("data")
                if not isinstance(account, dict) or not isinstance(account.get("lists"), list):
                    raise ValueError("Listclean omitted the account's email lists")
                if any(not isinstance(row, dict) or not isinstance(row.get("filename"), str) for row in account["lists"]):
                    raise ValueError("Listclean returned invalid email list details")
            output = {"status": "success", "data": _redact(data, token), "http_status": response.status_code}
        await self.emit(output)
        return output
