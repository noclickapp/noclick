"""ConvertAPI v2 account reads and fixed document/image conversions.

Contract: https://v2.convertapi.com/info/openapi (v2).
Form encoding follows the provider SDK (the OpenAPI lists only multipart):
https://github.com/ConvertAPI/convertapi-library-python/blob/main/convertapi/client.py
Conversions use temporary storage (up to three hours), returning URL metadata.
"""
from typing import Annotated, Literal, Union
from datetime import date
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://v2.convertapi.com"

class ConvertAPICredential(BaseModel):
    model_config = ConfigDict(title="ConvertAPI API Secret", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://www.convertapi.com/a/secret",
        "x-credential-instructions": "Paste your ConvertAPI API secret from your account. Use the secret, rather than a restricted API token: account information and usage statistics require it. NoClick sends it as a Bearer credential to v2.convertapi.com. Conversions consume your provider balance and store results temporarily for up to three hours."})
    credential_type: Literal["convertapi_api_secret"] = Field("convertapi_api_secret", json_schema_extra={"ui:hidden": True})
    api_secret: str = Field(..., min_length=1, title="API secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API secret")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API secret")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class GetAccount(Input):
    operation: Literal["get_account"] = "get_account"

class GetStatistics(Input):
    operation: Literal["get_statistics"] = "get_statistics"
    start_date: str = Field(..., description="Start date, YYYY-MM-DD")
    end_date: str = Field(..., description="End date, YYYY-MM-DD")

    @model_validator(mode="after")
    def dates(self):
        if date.fromisoformat(self.start_date) > date.fromisoformat(self.end_date):
            raise ValueError("End date must be on or after start date")
        return self

class FileInput(Input):
    file_id: str = Field(..., min_length=32, max_length=32, description="Stored ConvertAPI file ID returned by a conversion")

    @field_validator("file_id")
    @classmethod
    def identifier(cls, value):
        if any(c in value for c in "/?#\\") or value in {".", ".."}:
            raise ValueError("Paste the stored file ID, not a URL")
        return value

class GetFileInfo(FileInput):
    operation: Literal["get_file_info"] = "get_file_info"

class DeleteFile(FileInput):
    operation: Literal["delete_file"] = "delete_file"

class Conversion(Input):
    file: str = Field(..., min_length=1, description="Source file URL or previously uploaded ConvertAPI file ID. The provider fetches URL inputs.")
    file_name: str | None = Field(None, max_length=200, description="Optional output file name")

class ConvertPDFToDOCX(Conversion):
    """Convert PDF to DOCX; consumes conversion credits."""
    operation: Literal["pdf_to_docx"] = "pdf_to_docx"

class ConvertPDFToXLSX(Conversion):
    """Convert PDF to XLSX; consumes conversion credits."""
    operation: Literal["pdf_to_xlsx"] = "pdf_to_xlsx"

class ConvertPDFToJPG(Conversion):
    """Convert PDF to JPG; consumes conversion credits."""
    operation: Literal["pdf_to_jpg"] = "pdf_to_jpg"

class ConvertPDFToPNG(Conversion):
    """Convert PDF to PNG; consumes conversion credits."""
    operation: Literal["pdf_to_png"] = "pdf_to_png"

class ConvertPDFToTXT(Conversion):
    """Convert PDF to TXT; consumes conversion credits."""
    operation: Literal["pdf_to_txt"] = "pdf_to_txt"

class ConvertDOCXToPDF(Conversion):
    """Convert DOCX to PDF; consumes conversion credits."""
    operation: Literal["docx_to_pdf"] = "docx_to_pdf"

class ConvertXLSXToPDF(Conversion):
    """Convert XLSX to PDF; consumes conversion credits."""
    operation: Literal["xlsx_to_pdf"] = "xlsx_to_pdf"

class ConvertPPTXToPDF(Conversion):
    """Convert PPTX to PDF; consumes conversion credits."""
    operation: Literal["pptx_to_pdf"] = "pptx_to_pdf"

class ConvertJPGToPDF(Conversion):
    """Convert JPG to PDF; consumes conversion credits."""
    operation: Literal["jpg_to_pdf"] = "jpg_to_pdf"

class ConvertPNGToPDF(Conversion):
    """Convert PNG to PDF; consumes conversion credits."""
    operation: Literal["png_to_pdf"] = "png_to_pdf"

class ConvertHTMLToPDF(Conversion):
    """Convert HTML to PDF; consumes conversion credits."""
    operation: Literal["html_to_pdf"] = "html_to_pdf"

class ConvertCSVToXLSX(Conversion):
    """Convert CSV to XLSX; consumes conversion credits."""
    operation: Literal["csv_to_xlsx"] = "csv_to_xlsx"

Operation = Annotated[Union[GetAccount, GetStatistics, GetFileInfo, DeleteFile, ConvertPDFToDOCX, ConvertPDFToXLSX, ConvertPDFToJPG, ConvertPDFToPNG, ConvertPDFToTXT, ConvertDOCXToPDF, ConvertXLSXToPDF, ConvertPPTXToPDF, ConvertJPGToPDF, ConvertPNGToPDF, ConvertHTMLToPDF, ConvertCSVToXLSX], Field(discriminator="operation")]

class ConvertAPINodeConfig(NodeConfig[Operation, ConvertAPICredential]):
    pass

ROUTES = {'pdf_to_docx': '/convert/pdf/to/docx', 'pdf_to_xlsx': '/convert/pdf/to/xlsx', 'pdf_to_jpg': '/convert/pdf/to/jpg', 'pdf_to_png': '/convert/pdf/to/png', 'pdf_to_txt': '/convert/pdf/to/txt', 'docx_to_pdf': '/convert/docx/to/pdf', 'xlsx_to_pdf': '/convert/xlsx/to/pdf', 'pptx_to_pdf': '/convert/pptx/to/pdf', 'jpg_to_pdf': '/convert/jpg/to/pdf', 'png_to_pdf': '/convert/png/to/pdf', 'html_to_pdf': '/convert/html/to/pdf', 'csv_to_xlsx': '/convert/csv/to/xlsx'}

class ConvertAPINode(WorkflowNode):
    integration_type = "automation-convertapi"
    connection_evidence = ConnectionEvidence(operation="get_account", noun="ConvertAPI account")

    @classmethod
    def get_config_model(cls):
        return ConvertAPINodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a ConvertAPI API secret")
        secret = self.config.credentials.api_secret
        op = self.config.config
        headers = {"Authorization": "Bearer " + secret, "Accept": "application/json"}
        params = None
        body = None
        if op.operation == "get_account":
            method, path = "GET", "/user"
        elif op.operation == "get_statistics":
            method, path = "GET", "/user/statistic"
            params = {"startDate": op.start_date, "endDate": op.end_date}
        elif op.operation in {"get_file_info", "delete_file"}:
            method = "HEAD" if op.operation == "get_file_info" else "DELETE"
            path = "/d/" + quote(op.file_id, safe="")
        else:
            method, path = "POST", ROUTES[op.operation]
            body = {"File": op.file, "StoreFile": "true"}
            if op.file_name is not None:
                body["FileName"] = op.file_name
            # The official Python SDK posts this mapping as form-urlencoded data.
        # Fixed provider origin; no redirects or automatic write retries.
        async with httpx.AsyncClient(timeout=1200, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params, data=body)
        if response.status_code >= 300:
            message = response.text.replace(secret, "[redacted]")[:1000]
            raise ValueError(f"ConvertAPI HTTP {response.status_code}: {message}")
        if method == "HEAD":
            data = {k: response.headers[k] for k in ("file-name", "file-ext", "file-size", "content-disposition") if k in response.headers}
        elif method == "DELETE":
            data = {"file_id": op.file_id, "deleted": True}
        else:
            data = response.json()
            if op.operation == "get_account":
                data = {k: v for k, v in data.items() if k in {"Active", "Email", "FullName", "ConversionsTotal", "ConversionsConsumed", "SecondsLeft"}}
            elif op.operation in ROUTES:
                # Never propagate inline Base64 content even if the provider ignores StoreFile.
                data = {"ConversionCost": data.get("ConversionCost"), "Files": [
                    {k: v for k, v in f.items() if k in {"FileName", "FileExt", "FileSize", "FileId", "Url"}}
                    for f in data.get("Files", [])]}
        output = {"status": "success", "data": data}
        await self.emit(output)
        return output
