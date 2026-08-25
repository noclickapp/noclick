"""
Voyage AI integration node.

Full REST API coverage (base: https://api.voyageai.com/v1):
  Embeddings:  embed, embed_multimodal, embed_contextualized
  Reranking:   rerank
  Files:       upload_file, list_files, get_file, delete_file,
               get_file_content, bulk_delete_files
  Batch:       create_batch, list_batches, get_batch, cancel_batch
"""

import asyncio
import json
import time
from typing import Any, Annotated, Dict, Literal, Optional, Union

import aiohttp
from pydantic import BaseModel, ConfigDict, Field
from pydantic import Discriminator

from nodes.core.base import NodeConfig, WorkflowNode

VOYAGE_BASE_URL = "https://api.voyageai.com/v1"

EMBED_MODELS = [
    "voyage-4-large", "voyage-4", "voyage-4-lite", "voyage-4-nano",
    "voyage-code-3", "voyage-finance-2", "voyage-law-2",
    "voyage-3-large", "voyage-3.5", "voyage-3.5-lite",
    "voyage-3", "voyage-3-lite", "voyage-multilingual-2",
]
MULTIMODAL_MODELS = ["voyage-multimodal-3.5", "voyage-multimodal-3"]
CONTEXT_MODELS = ["voyage-context-4", "voyage-context-3"]
RERANK_MODELS = ["rerank-2.5", "rerank-2.5-lite", "rerank-2", "rerank-2-lite", "rerank-1", "rerank-lite-1"]
OUTPUT_DTYPES = ["float", "int8", "uint8", "binary", "ubinary"]
INPUT_TYPES = ["query", "document"]
OUTPUT_DIMS = [256, 512, 1024, 2048]
BATCH_ENDPOINTS = ["/v1/embeddings", "/v1/contextualizedembeddings", "/v1/rerank"]


# ── Credential ─────────────────────────────────────────────────────────────────

class VoyageAPIKeyCredential(BaseModel):
    credential_type: Literal["voyage_api_key"] = Field(
        "voyage_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        description="Your Voyage AI API key",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://dash.voyageai.com/api-keys",
        "x-credential-instructions": "Sign up at voyageai.com, then create an API key in the dashboard.",
    })


# ── Embedding configs ──────────────────────────────────────────────────────────

class VoyageEmbedConfig(BaseModel):
    operation: Literal["embed"] = Field(
        "embed",
        json_schema_extra={
            "x-category": "Embeddings",
            "x-display-name": "Generate Text Embeddings",
            "x-keywords": ["embed", "vectorize", "encode", "RAG", "semantic search", "dense"],
        },
    )
    input: str = Field(
        ...,
        description="Text to embed — plain string or JSON array of strings (max 1,000).",
        json_schema_extra={"ui:rows": 3},
    )
    model: str = Field(
        "voyage-4-large",
        description="Embedding model.",
        json_schema_extra={"enum": EMBED_MODELS, "x-enum-searchable": True},
    )
    input_type: Optional[str] = Field(
        None,
        description="Retrieval context: 'query' or 'document'. Leave empty for symmetric similarity.",
        json_schema_extra={"enum": INPUT_TYPES, "x-enum-searchable": True},
    )
    output_dimension: Optional[int] = Field(
        None,
        description="Matryoshka output dimension (256/512/1024/2048). Leave empty for model default.",
        json_schema_extra={"enum": OUTPUT_DIMS},
    )
    output_dtype: str = Field(
        "float",
        description="Output vector data type.",
        json_schema_extra={"enum": OUTPUT_DTYPES, "x-enum-searchable": True},
    )
    truncation: str = Field(
        "true",
        description="Truncate inputs that exceed the context limit.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class VoyageEmbedMultimodalConfig(BaseModel):
    operation: Literal["embed_multimodal"] = Field(
        "embed_multimodal",
        json_schema_extra={
            "x-category": "Embeddings",
            "x-display-name": "Generate Multimodal Embeddings",
            "x-keywords": ["multimodal", "image", "video", "embed", "vectorize"],
        },
    )
    inputs: str = Field(
        ...,
        description=(
            'JSON array of multimodal inputs. '
            'Each item: {"content": [{"type":"text","text":"..."}, '
            '{"type":"image_url","image_url":"https://..."}]}'
        ),
        json_schema_extra={"ui:rows": 5},
    )
    model: str = Field(
        "voyage-multimodal-3.5",
        description="Multimodal model. Only voyage-multimodal-3.5 supports video.",
        json_schema_extra={"enum": MULTIMODAL_MODELS, "x-enum-searchable": True},
    )
    input_type: Optional[str] = Field(
        None,
        description="Retrieval context: 'query' or 'document'.",
        json_schema_extra={"enum": INPUT_TYPES, "x-enum-searchable": True},
    )
    truncation: str = Field(
        "true",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


class VoyageEmbedContextualizedConfig(BaseModel):
    operation: Literal["embed_contextualized"] = Field(
        "embed_contextualized",
        json_schema_extra={
            "x-category": "Embeddings",
            "x-display-name": "Generate Contextualized Chunk Embeddings",
            "x-keywords": ["contextualized", "chunk", "RAG", "long document", "late chunking"],
        },
    )
    inputs: str = Field(
        ...,
        description=(
            "JSON array of documents; each document is an array of chunk strings. "
            'Example: [["chunk 1","chunk 2"],["chunk 3"]]'
        ),
        json_schema_extra={"ui:rows": 4},
    )
    model: str = Field(
        "voyage-context-4",
        description="Contextualized embedding model.",
        json_schema_extra={"enum": CONTEXT_MODELS, "x-enum-searchable": True},
    )
    input_type: Optional[str] = Field(
        None,
        json_schema_extra={"enum": INPUT_TYPES, "x-enum-searchable": True},
    )
    output_dimension: Optional[int] = Field(
        None,
        description="Output dimension (256/512/1024/2048). Leave empty for model default.",
        json_schema_extra={"enum": OUTPUT_DIMS},
    )
    output_dtype: str = Field(
        "float",
        json_schema_extra={"enum": OUTPUT_DTYPES, "x-enum-searchable": True},
    )


# ── Reranking ──────────────────────────────────────────────────────────────────

class VoyageRerankConfig(BaseModel):
    operation: Literal["rerank"] = Field(
        "rerank",
        json_schema_extra={
            "x-category": "Reranking",
            "x-display-name": "Rerank Documents",
            "x-keywords": ["rerank", "relevance", "cross-encoder", "RAG", "search"],
        },
    )
    query: str = Field(..., description="Query text to rank documents against.")
    documents: str = Field(
        ...,
        description="JSON array of document strings to rerank.",
        json_schema_extra={"ui:rows": 4},
    )
    model: str = Field(
        "rerank-2.5",
        description="Reranking model.",
        json_schema_extra={"enum": RERANK_MODELS, "x-enum-searchable": True},
    )
    top_k: Optional[int] = Field(
        None,
        description="Return only the top K results. Leave empty to return all.",
    )
    return_documents: str = Field(
        "true",
        description="Include original document text in results.",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )
    truncation: str = Field(
        "true",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )


# ── File management ────────────────────────────────────────────────────────────

class VoyageUploadFileConfig(BaseModel):
    operation: Literal["upload_file"] = Field(
        "upload_file",
        json_schema_extra={
            "x-category": "Files",
            "x-display-name": "Upload Batch File",
            "x-keywords": ["upload", "batch", "file", "JSONL"],
        },
    )
    file_content: str = Field(
        ...,
        description=(
            'JSONL batch input. Each line: '
            '{"custom_id":"req-1","body":{"input":["text"],"model":"voyage-4-large"}}'
        ),
        json_schema_extra={"ui:rows": 6},
    )
    filename: str = Field("batch_input.jsonl", description="Filename for the uploaded file.")


class VoyageListFilesConfig(BaseModel):
    operation: Literal["list_files"] = Field(
        "list_files",
        json_schema_extra={
            "x-category": "Files",
            "x-display-name": "List Files",
            "x-keywords": ["list", "files", "batch"],
        },
    )
    purpose: Optional[str] = Field(None, description="Filter by purpose (e.g. 'batch').")
    limit: int = Field(1000, description="Max results (1–10,000).", ge=1, le=10000)
    order: str = Field(
        "desc",
        json_schema_extra={"enum": ["desc", "asc"], "enumNames": ["Newest first", "Oldest first"]},
    )
    after: Optional[str] = Field(None, description="Pagination cursor (file ID from last page).")


class VoyageGetFileConfig(BaseModel):
    operation: Literal["get_file"] = Field(
        "get_file",
        json_schema_extra={
            "x-category": "Files",
            "x-display-name": "Get File",
            "x-keywords": ["get", "retrieve", "file", "metadata"],
        },
    )
    file_id: str = Field(..., description="ID of the file to retrieve.")


class VoyageDeleteFileConfig(BaseModel):
    operation: Literal["delete_file"] = Field(
        "delete_file",
        json_schema_extra={
            "x-category": "Files",
            "x-display-name": "Delete File",
            "x-keywords": ["delete", "file", "remove"],
        },
    )
    file_id: str = Field(..., description="ID of the file to delete.")


class VoyageGetFileContentConfig(BaseModel):
    operation: Literal["get_file_content"] = Field(
        "get_file_content",
        json_schema_extra={
            "x-category": "Files",
            "x-display-name": "Get File Content",
            "x-keywords": ["download", "content", "file", "output", "batch results"],
        },
    )
    file_id: str = Field(..., description="ID of the file to download content from.")


class VoyageBulkDeleteFilesConfig(BaseModel):
    operation: Literal["bulk_delete_files"] = Field(
        "bulk_delete_files",
        json_schema_extra={
            "x-category": "Files",
            "x-display-name": "Bulk Delete Files",
            "x-keywords": ["bulk", "delete", "files", "cleanup"],
        },
    )
    file_ids: str = Field(
        ...,
        description="JSON array of file IDs to delete. All-or-nothing — any invalid ID aborts the whole operation.",
        json_schema_extra={"ui:rows": 2},
    )


# ── Batch management ───────────────────────────────────────────────────────────

class VoyageCreateBatchConfig(BaseModel):
    operation: Literal["create_batch"] = Field(
        "create_batch",
        json_schema_extra={
            "x-category": "Batch",
            "x-display-name": "Create Batch Job",
            "x-keywords": ["batch", "async", "bulk", "inference", "create"],
        },
    )
    input_file_id: str = Field(..., description="File ID returned from a previous upload_file call.")
    endpoint: str = Field(
        "/v1/embeddings",
        description="Target inference endpoint for this batch.",
        json_schema_extra={"enum": BATCH_ENDPOINTS},
    )
    request_params: str = Field(
        ...,
        description=(
            'JSON object of inference parameters (model is required). '
            'Example: {"model":"voyage-4-large","input_type":"document"}'
        ),
        json_schema_extra={"ui:rows": 3},
    )
    completion_window: str = Field("12h", description="Processing time limit. Currently only '12h' is supported.")
    metadata: Optional[str] = Field(
        None,
        description="Optional JSON object with up to 16 key-value pairs (keys ≤64 chars, values ≤512 chars).",
    )


class VoyageListBatchesConfig(BaseModel):
    operation: Literal["list_batches"] = Field(
        "list_batches",
        json_schema_extra={
            "x-category": "Batch",
            "x-display-name": "List Batch Jobs",
            "x-keywords": ["list", "batch", "jobs", "status"],
        },
    )
    limit: int = Field(20, description="Max results (1–100).", ge=1, le=100)
    after: Optional[str] = Field(None, description="Pagination cursor (batch ID from last page).")


class VoyageGetBatchConfig(BaseModel):
    operation: Literal["get_batch"] = Field(
        "get_batch",
        json_schema_extra={
            "x-category": "Batch",
            "x-display-name": "Get Batch Job",
            "x-keywords": ["get", "retrieve", "batch", "status", "check"],
        },
    )
    batch_id: str = Field(..., description="ID of the batch job.")


class VoyageCancelBatchConfig(BaseModel):
    operation: Literal["cancel_batch"] = Field(
        "cancel_batch",
        json_schema_extra={
            "x-category": "Batch",
            "x-display-name": "Cancel Batch Job",
            "x-keywords": ["cancel", "batch", "stop", "abort"],
        },
    )
    batch_id: str = Field(
        ...,
        description="Batch job ID to cancel (must be in 'validating' or 'in_progress' status).",
    )


# ── Union / NodeConfig ─────────────────────────────────────────────────────────

VoyageConfig = Annotated[
    Union[
        VoyageEmbedConfig,
        VoyageEmbedMultimodalConfig,
        VoyageEmbedContextualizedConfig,
        VoyageRerankConfig,
        VoyageUploadFileConfig,
        VoyageListFilesConfig,
        VoyageGetFileConfig,
        VoyageDeleteFileConfig,
        VoyageGetFileContentConfig,
        VoyageBulkDeleteFilesConfig,
        VoyageCreateBatchConfig,
        VoyageListBatchesConfig,
        VoyageGetBatchConfig,
        VoyageCancelBatchConfig,
    ],
    Discriminator("operation"),
]


class VoyageNodeConfig(NodeConfig[VoyageConfig, VoyageAPIKeyCredential]):
    pass


# ── HTTP helpers ───────────────────────────────────────────────────────────────

async def _voyage_request(
    api_key: str,
    method: str,
    endpoint: str,
    body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    action_name: str = "",
) -> Dict[str, Any]:
    url = f"{VOYAGE_BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    t0 = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url, headers=headers, json=body, params=params,
                timeout=aiohttp.ClientTimeout(total=120),
                allow_redirects=False,
            ) as resp:
                api_ms = round((time.monotonic() - t0) * 1000, 2)
                text = await resp.text()
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    data = {"raw": text}
                if resp.status >= 400:
                    detail = data.get("detail") or data.get("message") or text
                    return {
                        "status": "error",
                        "action": action_name,
                        "error": f"Voyage AI error ({resp.status}): {detail}",
                        "status_code": resp.status,
                        "timing_ms": {"api": api_ms},
                    }
                return {
                    "status": "success",
                    "action": action_name,
                    "data": data,
                    "status_code": resp.status,
                    "timing_ms": {"api": api_ms},
                }
    except asyncio.TimeoutError:
        return {"status": "error", "action": action_name, "error": "Request timed out (120s)", "status_code": 0, "timing_ms": {}}
    except Exception as exc:
        return {"status": "error", "action": action_name, "error": str(exc), "status_code": 0, "timing_ms": {}}


async def _voyage_upload_file(api_key: str, content: str, filename: str) -> Dict[str, Any]:
    """Upload a JSONL batch file via multipart/form-data."""
    url = f"{VOYAGE_BASE_URL}/files"
    headers = {"Authorization": f"Bearer {api_key}"}
    t0 = time.monotonic()
    try:
        form = aiohttp.FormData()
        form.add_field("purpose", "batch")
        form.add_field("file", content.encode(), filename=filename, content_type="application/jsonl")
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers=headers,
                data=form,
                timeout=aiohttp.ClientTimeout(total=120),
                allow_redirects=False,
            ) as resp:
                api_ms = round((time.monotonic() - t0) * 1000, 2)
                data = await resp.json()
                if resp.status >= 400:
                    return {"status": "error", "action": "upload_file", "error": f"Voyage AI error ({resp.status}): {data}", "status_code": resp.status, "timing_ms": {"api": api_ms}}
                return {"status": "success", "action": "upload_file", "data": data, "status_code": resp.status, "timing_ms": {"api": api_ms}}
    except Exception as exc:
        return {"status": "error", "action": "upload_file", "error": str(exc), "status_code": 0, "timing_ms": {}}


def _parse_json_field(value: str, field_name: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        raise ValueError(f"{field_name} is not valid JSON: {value[:120]}")


# ── Node ───────────────────────────────────────────────────────────────────────

class VoyageNode(WorkflowNode):
    @classmethod
    def get_config_model(cls):
        return VoyageNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        if not self.config or not self.config.credentials:
            raise ValueError("Credentials are required for Voyage AI")
        api_key = self.config.credentials.api_key
        c = self.config.config

        match c.operation:
            case "embed":
                return await self._embed(c, api_key)
            case "embed_multimodal":
                return await self._embed_multimodal(c, api_key)
            case "embed_contextualized":
                return await self._embed_contextualized(c, api_key)
            case "rerank":
                return await self._rerank(c, api_key)
            case "upload_file":
                return await _voyage_upload_file(api_key, c.file_content, c.filename)
            case "list_files":
                return await self._list_files(c, api_key)
            case "get_file":
                return await _voyage_request(api_key, "GET", f"/files/{c.file_id}", action_name="get_file")
            case "delete_file":
                return await _voyage_request(api_key, "DELETE", f"/files/{c.file_id}", action_name="delete_file")
            case "get_file_content":
                return await _voyage_request(api_key, "GET", f"/files/{c.file_id}/content", action_name="get_file_content")
            case "bulk_delete_files":
                return await self._bulk_delete_files(c, api_key)
            case "create_batch":
                return await self._create_batch(c, api_key)
            case "list_batches":
                p: Dict[str, Any] = {"limit": c.limit}
                if c.after:
                    p["after"] = c.after
                return await _voyage_request(api_key, "GET", "/batches", params=p, action_name="list_batches")
            case "get_batch":
                return await _voyage_request(api_key, "GET", f"/batches/{c.batch_id}", action_name="get_batch")
            case "cancel_batch":
                return await _voyage_request(api_key, "POST", f"/batches/{c.batch_id}/cancel", action_name="cancel_batch")
            case _:
                raise ValueError(f"Unknown operation: {c.operation}")

    async def _embed(self, c: VoyageEmbedConfig, api_key: str) -> Dict[str, Any]:
        raw = c.input.strip()
        inp = _parse_json_field(raw, "input") if raw.startswith("[") else raw
        body: Dict[str, Any] = {
            "input": inp, "model": c.model,
            "output_dtype": c.output_dtype, "truncation": c.truncation == "true",
        }
        if c.input_type:
            body["input_type"] = c.input_type
        if c.output_dimension:
            body["output_dimension"] = c.output_dimension
        result = await _voyage_request(api_key, "POST", "/embeddings", body=body, action_name="embed")
        if result["status"] != "success":
            return result
        d = result["data"]
        embeddings = [item["embedding"] for item in d.get("data", [])]
        result["data"] = {
            "embeddings": embeddings,
            "model": d.get("model"),
            "dimensions": len(embeddings[0]) if embeddings else 0,
            "count": len(embeddings),
            "total_tokens": (d.get("usage") or {}).get("total_tokens"),
        }
        return result

    async def _embed_multimodal(self, c: VoyageEmbedMultimodalConfig, api_key: str) -> Dict[str, Any]:
        inputs = _parse_json_field(c.inputs, "inputs")
        body: Dict[str, Any] = {"inputs": inputs, "model": c.model, "truncation": c.truncation == "true"}
        if c.input_type:
            body["input_type"] = c.input_type
        result = await _voyage_request(api_key, "POST", "/multimodalembeddings", body=body, action_name="embed_multimodal")
        if result["status"] != "success":
            return result
        d = result["data"]
        embeddings = [item["embedding"] for item in d.get("data", [])]
        result["data"] = {
            "embeddings": embeddings,
            "model": d.get("model"),
            "dimensions": len(embeddings[0]) if embeddings else 0,
            "count": len(embeddings),
            "usage": d.get("usage"),
        }
        return result

    async def _embed_contextualized(self, c: VoyageEmbedContextualizedConfig, api_key: str) -> Dict[str, Any]:
        inputs = _parse_json_field(c.inputs, "inputs")
        body: Dict[str, Any] = {"inputs": inputs, "model": c.model, "output_dtype": c.output_dtype}
        if c.input_type:
            body["input_type"] = c.input_type
        if c.output_dimension:
            body["output_dimension"] = c.output_dimension
        result = await _voyage_request(api_key, "POST", "/contextualizedembeddings", body=body, action_name="embed_contextualized")
        if result["status"] != "success":
            return result
        d = result["data"]
        result["data"] = {
            "documents": d.get("data", []),
            "model": d.get("model"),
            "total_tokens": (d.get("usage") or {}).get("total_tokens"),
            "chunker_version": d.get("chunker_version"),
        }
        return result

    async def _rerank(self, c: VoyageRerankConfig, api_key: str) -> Dict[str, Any]:
        docs = _parse_json_field(c.documents, "documents")
        body: Dict[str, Any] = {
            "query": c.query, "documents": docs, "model": c.model,
            "return_documents": c.return_documents == "true",
            "truncation": c.truncation == "true",
        }
        if c.top_k is not None:
            body["top_k"] = c.top_k
        result = await _voyage_request(api_key, "POST", "/rerank", body=body, action_name="rerank")
        if result["status"] != "success":
            return result
        d = result["data"]
        result["data"] = {
            "results": d.get("data", []),
            "model": d.get("model"),
            "total_tokens": (d.get("usage") or {}).get("total_tokens"),
        }
        return result

    async def _list_files(self, c: VoyageListFilesConfig, api_key: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": c.limit, "order": c.order}
        if c.purpose:
            params["purpose"] = c.purpose
        if c.after:
            params["after"] = c.after
        return await _voyage_request(api_key, "GET", "/files", params=params, action_name="list_files")

    async def _bulk_delete_files(self, c: VoyageBulkDeleteFilesConfig, api_key: str) -> Dict[str, Any]:
        file_ids = _parse_json_field(c.file_ids, "file_ids")
        return await _voyage_request(api_key, "POST", "/files/delete", body={"file_ids": file_ids}, action_name="bulk_delete_files")

    async def _create_batch(self, c: VoyageCreateBatchConfig, api_key: str) -> Dict[str, Any]:
        req_params = _parse_json_field(c.request_params, "request_params")
        body: Dict[str, Any] = {
            "endpoint": c.endpoint,
            "input_file_id": c.input_file_id,
            "completion_window": c.completion_window,
            "request_params": req_params,
        }
        if c.metadata:
            body["metadata"] = _parse_json_field(c.metadata, "metadata")
        return await _voyage_request(api_key, "POST", "/batches", body=body, action_name="create_batch")
