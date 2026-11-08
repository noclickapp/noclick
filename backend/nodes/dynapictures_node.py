"""DynaPictures API: fixed, one-request JSON operations, authenticated by API key.

Contract: https://dynapictures.com/openapi.json (1.0.0).
Authentication: https://dynapictures.com/auth.md. Image generation returns URLs;
AI jobs are asynchronous and polled explicitly. Writes are never retried.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.dynapictures.com"


class DynapicturesAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Dynapictures API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dynapictures.com/app/account",
            "x-credential-instructions": "Copy your API key from the DynaPictures account page. It grants your user's full access. Paste only the key; NoClick adds the Bearer header. Connecting reads your workspaces.",
        })
    credential_type: Literal["dynapictures_api_key"] = Field("dynapictures_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(ch.isspace() for ch in value) or value.lower().startswith("bearer"):
            raise ValueError("Paste only the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ReferenceImage(_Input):
    name: str = Field(..., description='Short name used in the prompt as `[name]`, e.g. `logo`.')
    url: str = Field(..., description='Public URL of the reference image.')


class LayerOverride(_Input):
    name: str = Field(..., description='The name of the layer to customize, shown in the settings panel when the layer is selected. `canvas` is the background.')
    text: str | None = Field(None, description='The text to render in a text layer. Basic HTML is supported and sanitized.')
    color: str | None = Field(None, description='The text color. E.g. `#000000`, `rgb(0,0,0)` or `rgba(0,0,0,0.5)`.')
    fontSize: str | None = Field(None, description='Font size of a text layer, e.g. `48px`.')
    backgroundColor: str | None = Field(None, description='The background color of the layer. E.g. `#000000`, `rgb(0,0,0)` or `rgba(0,0,0,0.5)`.')
    borderColor: str | None = Field(None, description='The border color of the layer. Set `borderWidth` as well. E.g. `#000000`, `rgb(0,0,0)` or `rgba(0,0,0,0.5)`.')
    borderWidth: str | None = Field(None, description='The border width of the layer, e.g. `1px`.')
    borderRadius: str | None = Field(None, description='The border radius of the layer, e.g. `5px` or `50%`.')
    opacity: float | None = Field(None, description='Layer opacity from `0` (hidden) to `1` (as designed).')
    imageUrl: str | None = Field(None, description='The image to render in an image layer.')
    imagePosition: Literal['cro', 'cov', 'ai_face', 'align'] | None = Field(None, description='How the image fits its container. Empty centers it. `cro` crops to fill, `cov` scales to cover, `ai_face` detects faces and keeps them visible, and `align` uses `imageAlignH` and `imageAlignV`.')
    imageAlignH: Literal['left', 'center', 'right', 'full'] | None = Field(None, description='Horizontal image alignment when `imagePosition` is `align`.')
    imageAlignV: Literal['top', 'center', 'bottom', 'full'] | None = Field(None, description='Vertical image alignment when `imagePosition` is `align`.')
    imageEffect: str | None = Field(None, description='A CSS filter applied to the image, e.g. `grayscale(100%)` or `blur(4px)`.')
    prompt: str | None = Field(None, description='Prompt for an AI Image layer in "Per request" mode. Supports `[name]` tokens that refer to `referenceImages`.')
    sourceImage: str | None = Field(None, description='URL of a photo for an AI Image layer to edit. Omit it for text-to-image.')
    referenceImages: list[ReferenceImage] | None = Field(None, description='Named reference images for an AI Image layer.')
    chartColor: str | None = Field(None, description='The color of the chart. E.g. `#000000`, `rgb(0,0,0)` or `rgba(0,0,0,0.5)`.')
    chartLabelColor: str | None = Field(None, description='The color of the chart axis labels. E.g. `#000000`, `rgb(0,0,0)` or `rgba(0,0,0,0.5)`.')
    chartDataLabels: list[str] | None = Field(None, description='Labels shown on the X axis.')
    chartDataValues: list[float] | None = Field(None, description='The data series of the chart.')
    value: float | None = Field(None, description='Progress value for gauge and line progress bar layers, usually `0` to `100`.')
    maxValue: float | None = Field(None, description='Total number of ticks of a radial tick gauge, e.g. `24`, `60` or `100`.')
    activeColor: str | None = Field(None, description='Color of the filled ticks of a radial tick gauge.')
    inactiveColor: str | None = Field(None, description='Color of the empty ticks of a radial tick gauge.')
    circleColor: str | None = Field(None, description='Color of the background ring of a simple gauge.')
    progressColor: str | None = Field(None, description='Color of the progress arc or of the filled part of a line progress bar.')
    textColor: str | None = Field(None, description='Color of the value label inside a simple gauge.')
    remainingColor: str | None = Field(None, description='Color of the unfilled track of a line progress bar.')
    label: str | None = Field(None, description='Overrides the label text of a line progress bar.')
    labelAlign: Literal['left', 'center', 'right'] | None = Field(None, description='Horizontal alignment of the line progress bar label.')


class PageOverride(_Input):
    index: int = Field(..., description='The page of the template this applies to, starting at 0.')
    layers: list[LayerOverride] | None = Field(None, description='New values for the layers of this page.')


class GenerateImageConfig(_Input):
    """Generate an image from a template."""
    operation: Literal["generate_image"] = Field("generate_image", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., description='The ID of the template, shown in the editor and returned by `GET /templates`.')
    format: Literal['png', 'jpeg', 'webp', 'avif', 'pdf', 'pptx'] | None = Field(None, description='Output format. `pdf` is for multipage templates and produces one file with every page.')
    metadata: str | None = Field(None, description='Custom data stored on the generated image and returned in responses and webhooks.')
    params: list[LayerOverride] | None = Field(None, description='New values for the layers of a single-page template.')
    pages: list[PageOverride] | None = Field(None, description='New values for the pages of a multipage template, instead of `params`.')
    responseFormat: Literal["json"] = Field("json", description='Return JSON containing generated image or PDF URLs.')


class SearchGeneratedImagesConfig(_Input):
    """Search generated images."""
    operation: Literal["search_generated_images"] = Field("search_generated_images", json_schema_extra={"ui:hidden": True})
    keyword: str | None = Field(None, description='Full-text search in metadata and parameters.')
    metadata: str | None = Field(None, description='Exact match on the metadata.')
    startDate: str | None = Field(None, description='Generated at or after this time, in ISO 8601.')
    endDate: str | None = Field(None, description='Generated before this time, in ISO 8601.')


class DeleteGeneratedImageConfig(_Input):
    """Delete a generated image."""
    operation: Literal["delete_generated_image"] = Field("delete_generated_image", json_schema_extra={"ui:hidden": True})
    teamUid: str = Field(..., description='The first path segment of the image URL.')
    filename: str = Field(..., description='The file name in the image URL.')


class StartAiGenerationConfig(_Input):
    """Start an AI image generation."""
    operation: Literal["start_ai_generation"] = Field("start_ai_generation", json_schema_extra={"ui:hidden": True})
    modelId: str = Field(..., description='The AI model. The API reference lists every model with its credit cost, e.g. `flux-2-pro`, `gemini-3.1-flash-image` or `gpt-image-2-med`.')
    prompt: str = Field(..., description='What to generate. May contain `[name]` tokens that refer to `referenceImages`.')
    ratio: Literal['1:1', '3:2', '2:3', '16:9', '9:16', '4:3', '3:4'] = Field('1:1', description='The aspect ratio. Supported ratios vary by model.')
    sourceImage: str | None = Field(None, description='URL of a photo to edit. Leave it out for text-to-image.')
    referenceImages: list[ReferenceImage] | None = Field(None, description='Named reference images. At most 6 input images in total, counting `sourceImage`.')


class GetAiGenerationConfig(_Input):
    """Get an AI generation job."""
    operation: Literal["get_ai_generation"] = Field("get_ai_generation", json_schema_extra={"ui:hidden": True})
    jobUid: str = Field(..., description='The `jobUid` from the start request.')


class ListTemplatesConfig(_Input):
    """List templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    workspace_id: str | None = Field(None, description='Only this workspace.')


class GetTemplateConfig(_Input):
    """Get a template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., description='The ID of the template, shown in the editor and returned by `GET /templates`.')


class CreateDesignConfig(_Input):
    """Create an empty design."""
    operation: Literal["create_design"] = Field("create_design", json_schema_extra={"ui:hidden": True})
    workspaceUid: str = Field(..., description='The workspace to create the design in.')
    name: str = Field(..., description='The name of the design.')
    width: int = Field(650, description='Canvas width in pixels.')
    height: int = Field(500, description='Canvas height in pixels.')


class AddLayerConfig(_Input):
    """Add a layer."""
    operation: Literal["add_layer"] = Field("add_layer", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., description='The ID of the template, shown in the editor and returned by `GET /templates`.')
    type: Literal['text', 'image', 'ai_image', 'rectangle', 'circle'] = Field(..., description='The kind of layer to add.')
    pageIndex: int | None = Field(None, description='The page of a multipage design. Defaults to the first page.')
    text: str | None = Field(None, description='The text of a text layer.')
    imageUrl: str | None = Field(None, description='The image of an image layer.')
    prompt: str | None = Field(None, description='The prompt of an AI Image layer.')
    color: str | None = Field(None, description='The text color.')
    backgroundColor: str | None = Field(None, description='The background color.')
    fontSize: int | None = Field(None, description='The font size in pixels.')
    textAlign: str | None = Field(None, description='The text alignment.')
    fontFamily: str | None = Field(None, description='The font family.')
    fontWeight: str | None = Field(None, description='The font weight.')
    aiModel: str | None = Field(None, description='The model of an AI Image layer.')
    aiAspectRatio: str | None = Field(None, description='The aspect ratio of an AI Image layer.')
    x: float | None = Field(None, description='Left position in pixels.')
    y: float | None = Field(None, description='Top position in pixels.')
    width: float | None = Field(None, description='Width in pixels.')
    height: float | None = Field(None, description='Height in pixels.')
    zIndex: int | None = Field(None, description='The stacking order.')


class UpdateLayerConfig(_Input):
    """Update a layer."""
    operation: Literal["update_layer"] = Field("update_layer", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., description='The ID of the template, shown in the editor and returned by `GET /templates`.')
    layerId: str = Field(..., description='The ID of the layer.')
    x: float | None = Field(None, description='Left position in pixels.')
    y: float | None = Field(None, description='Top position in pixels.')
    width: float | None = Field(None, description='Width in pixels.')
    height: float | None = Field(None, description='Height in pixels.')
    text: str | None = Field(None, description='The new text.')
    styles: dict[str, Any] | None = Field(None, description='CSS-like style properties to merge into the layer.')


class DeleteLayerConfig(_Input):
    """Delete a layer."""
    operation: Literal["delete_layer"] = Field("delete_layer", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., description='The ID of the template, shown in the editor and returned by `GET /templates`.')
    layerId: str = Field(..., description='The ID of the layer.')


class ReorderLayerConfig(_Input):
    """Change a layer's stacking order."""
    operation: Literal["reorder_layer"] = Field("reorder_layer", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., description='The ID of the template, shown in the editor and returned by `GET /templates`.')
    layerId: str = Field(..., description='The ID of the layer.')
    op: Literal['toFront', 'toBack', 'up', 'down'] | None = Field(None, description='Move the layer relative to the others. Takes precedence over `zIndex`.')
    zIndex: int | None = Field(None, description='An absolute stacking position.')


class ResizeCanvasConfig(_Input):
    """Resize the canvas."""
    operation: Literal["resize_canvas"] = Field("resize_canvas", json_schema_extra={"ui:hidden": True})
    uid: str = Field(..., description='The ID of the template, shown in the editor and returned by `GET /templates`.')
    width: int = Field(..., description='The new width in pixels.')
    height: int = Field(..., description='The new height in pixels.')


class ListWorkspacesConfig(_Input):
    """List workspaces."""
    operation: Literal["list_workspaces"] = Field("list_workspaces", json_schema_extra={"ui:hidden": True})



class CreateWorkspaceConfig(_Input):
    """Create a workspace."""
    operation: Literal["create_workspace"] = Field("create_workspace", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='The name of the workspace.')


class UpdateWorkspaceConfig(_Input):
    """Rename a workspace."""
    operation: Literal["update_workspace"] = Field("update_workspace", json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., description='The ID of the workspace.')
    name: str = Field(..., description='The name of the workspace.')


class DeleteWorkspaceConfig(_Input):
    """Delete a workspace."""
    operation: Literal["delete_workspace"] = Field("delete_workspace", json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., description='The ID of the workspace.')


class ListMediaAssetsConfig(_Input):
    """List media assets."""
    operation: Literal["list_media_assets"] = Field("list_media_assets", json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., description='The ID of the workspace.')
    p: int = Field(1, description='The page, starting at 1.', ge=1)


class UploadMediaAssetFromUrlConfig(_Input):
    """Upload an image from a URL."""
    operation: Literal["upload_media_asset_from_url"] = Field("upload_media_asset_from_url", json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., description='The ID of the workspace.')
    url: str = Field(..., description='Public URL of the image to import into the media library.')
    mimeType: str | None = Field(None, description='The MIME type of the image.')
    name: str | None = Field(None, description='A display name.')
    folderUid: str | None = Field(None, description='The folder to put it in.')


class GetMediaAssetConfig(_Input):
    """Get a media asset."""
    operation: Literal["get_media_asset"] = Field("get_media_asset", json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., description='The ID of the workspace.')
    assetId: str = Field(..., description='The ID of the asset.')


class DeleteMediaAssetConfig(_Input):
    """Delete a media asset."""
    operation: Literal["delete_media_asset"] = Field("delete_media_asset", json_schema_extra={"ui:hidden": True})
    workspaceId: str = Field(..., description='The ID of the workspace.')
    assetId: str = Field(..., description='The ID of the asset.')


class SubscribeWebhookConfig(_Input):
    """Subscribe a webhook."""
    operation: Literal["subscribe_webhook"] = Field("subscribe_webhook", json_schema_extra={"ui:hidden": True})
    targetUrl: str = Field(..., description='The URL that receives the notifications.')
    eventType: Literal['NEW_IMAGE'] = Field("NEW_IMAGE", description='The event to subscribe to.')
    templateId: str = Field(..., description='The template to watch.')


class UnsubscribeWebhookConfig(_Input):
    """Unsubscribe a webhook."""
    operation: Literal["unsubscribe_webhook"] = Field("unsubscribe_webhook", json_schema_extra={"ui:hidden": True})
    targetUrl: str = Field(..., description='The URL that receives the notifications.')
    eventType: Literal['NEW_IMAGE'] = Field("NEW_IMAGE", description='The event to subscribe to.')
    templateId: str = Field(..., description='The template to watch.')


DynapicturesOperation = Annotated[Union[
    GenerateImageConfig,
    SearchGeneratedImagesConfig,
    DeleteGeneratedImageConfig,
    StartAiGenerationConfig,
    GetAiGenerationConfig,
    ListTemplatesConfig,
    GetTemplateConfig,
    CreateDesignConfig,
    AddLayerConfig,
    UpdateLayerConfig,
    DeleteLayerConfig,
    ReorderLayerConfig,
    ResizeCanvasConfig,
    ListWorkspacesConfig,
    CreateWorkspaceConfig,
    UpdateWorkspaceConfig,
    DeleteWorkspaceConfig,
    ListMediaAssetsConfig,
    UploadMediaAssetFromUrlConfig,
    GetMediaAssetConfig,
    DeleteMediaAssetConfig,
    SubscribeWebhookConfig,
    UnsubscribeWebhookConfig
], Field(discriminator="operation")]


class DynapicturesConfig(NodeConfig[DynapicturesOperation, DynapicturesAPIKeyCredential]):
    pass


# method, route, path fields, query fields, body fields, JSON body present.
ROUTES = {'generate_image': ('POST',
                    '/designs/{uid}',
                    ('uid',),
                    (),
                    ('format', 'metadata', 'params', 'pages', 'responseFormat'),
                    True),
 'search_generated_images': ('GET',
                             '/generated-images',
                             (),
                             ('keyword', 'metadata', 'startDate', 'endDate'),
                             (),
                             False),
 'delete_generated_image': ('DELETE',
                            '/images/{teamUid}/{filename}',
                            ('teamUid', 'filename'),
                            (),
                            (),
                            False),
 'start_ai_generation': ('POST',
                         '/ai/generate',
                         (),
                         (),
                         ('modelId', 'prompt', 'ratio', 'sourceImage', 'referenceImages'),
                         True),
 'get_ai_generation': ('GET', '/ai/generate/{jobUid}', ('jobUid',), (), (), False),
 'list_templates': ('GET', '/templates', (), ('workspace_id',), (), False),
 'get_template': ('GET', '/templates/{uid}', ('uid',), (), (), False),
 'create_design': ('POST', '/designs', (), (), ('workspaceUid', 'name', 'width', 'height'), True),
 'add_layer': ('POST',
               '/designs/{uid}/layers',
               ('uid',),
               (),
               ('type',
                'pageIndex',
                'text',
                'imageUrl',
                'prompt',
                'color',
                'backgroundColor',
                'fontSize',
                'textAlign',
                'fontFamily',
                'fontWeight',
                'aiModel',
                'aiAspectRatio',
                'x',
                'y',
                'width',
                'height',
                'zIndex'),
               True),
 'update_layer': ('PATCH',
                  '/designs/{uid}/layers/{layerId}',
                  ('uid', 'layerId'),
                  (),
                  ('x', 'y', 'width', 'height', 'text', 'styles'),
                  True),
 'delete_layer': ('DELETE', '/designs/{uid}/layers/{layerId}', ('uid', 'layerId'), (), (), False),
 'reorder_layer': ('POST',
                   '/designs/{uid}/layers/{layerId}/z-index',
                   ('uid', 'layerId'),
                   (),
                   ('op', 'zIndex'),
                   True),
 'resize_canvas': ('POST', '/designs/{uid}/canvas/resize', ('uid',), (), ('width', 'height'), True),
 'list_workspaces': ('GET', '/workspaces', (), (), (), False),
 'create_workspace': ('POST', '/workspaces', (), (), ('name',), True),
 'update_workspace': ('PUT', '/workspaces/{workspaceId}', ('workspaceId',), (), ('name',), True),
 'delete_workspace': ('DELETE', '/workspaces/{workspaceId}', ('workspaceId',), (), (), False),
 'list_media_assets': ('GET', '/media/{workspaceId}/assets', ('workspaceId',), ('p',), (), False),
 'upload_media_asset_from_url': ('POST',
                                 '/media/{workspaceId}/assets/from-url',
                                 ('workspaceId',),
                                 (),
                                 ('url', 'base64', 'mimeType', 'name', 'folderUid'),
                                 True),
 'get_media_asset': ('GET',
                     '/media/{workspaceId}/assets/{assetId}',
                     ('workspaceId', 'assetId'),
                     (),
                     (),
                     False),
 'delete_media_asset': ('DELETE',
                        '/media/{workspaceId}/assets/{assetId}',
                        ('workspaceId', 'assetId'),
                        (),
                        (),
                        False),
 'subscribe_webhook': ('POST', '/hooks', (), (), ('targetUrl', 'eventType', 'templateId'), True),
 'unsubscribe_webhook': ('DELETE', '/hooks', (), (), ('targetUrl', 'eventType', 'templateId'), True)}


def _segment(value):
    if not value or value in {".", ".."} or any(ord(ch) < 32 for ch in value):
        raise ValueError("Use a nonempty DynaPictures resource ID")
    return quote(value, safe="")


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value


class DynapicturesNode(WorkflowNode):
    integration_type = "automation-dynapictures"
    connection_evidence = ConnectionEvidence(noun="workspaces", operation="list_workspaces")

    @classmethod
    def get_config_model(cls):
        return DynapicturesConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a DynaPictures API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, route, path_fields, query_fields, body_fields, has_body = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        for field in path_fields:
            route = route.replace("{" + field + "}", _segment(values[field]))
        params = {field: values[field] for field in query_fields if field in values}
        body = {field: values[field] for field in body_fields if field in values} if has_body else None
        # This operation always returns JSON URLs, never response-body base64.
        if op.operation == "generate_image":
            body["responseFormat"] = "json"
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + route,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    params=params, **({"json": body} if has_body else {}))
        except httpx.HTTPError:
            raise ValueError("DynaPictures request failed; inspect any write before retrying") from None
        if not 200 <= response.status_code < 300:
            try:
                message = response.json().get("message")
            except (ValueError, AttributeError):
                message = None
            return {"status": "error", "success": False, "http_status": response.status_code,
                "error": _redact(message, key) if isinstance(message, str) else "DynaPictures rejected the request"}
        if op.operation == "delete_generated_image" and not response.content:
            data = {"deleted": True}
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("DynaPictures returned an invalid JSON response") from None
            if not isinstance(data, (dict, list)):
                raise ValueError("DynaPictures returned an unexpected response shape")
            if isinstance(data, dict) and data.get("error") is True:
                return {"status": "error", "success": False, "http_status": response.status_code,
                    "error": _redact(data.get("message", "DynaPictures rejected the request"), key)}
            if op.operation in {"list_workspaces", "list_templates", "search_generated_images"}:
                if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                    raise ValueError("DynaPictures returned an unexpected list response")
                if op.operation in {"list_workspaces", "list_templates"} and any(
                    not isinstance(row.get(field), str) or not row[field]
                    for row in data for field in ("id", "name")
                ):
                    raise ValueError("DynaPictures returned an incomplete resource list")
            elif not isinstance(data, dict):
                raise ValueError("DynaPictures returned an unexpected object response")
        output = {"status": "success", "success": True, "operation": op.operation,
            "http_status": response.status_code, "data": _redact(data, key)}
        await self.emit(output)
        return output
