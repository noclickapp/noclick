"""Jogg Ai v2 API-key operations, pinned to the provider's published OpenAPI 2.0.0."""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class JoggAiAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Jogg Ai API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.jogg.ai/",
            "x-credential-instructions": "Copy your API key from the JoggAI dashboard and paste it here. NoClick sends it in the x-api-key header to api.jogg.ai. Video generation uses your JoggAI credits.",
        })
    credential_type: Literal["jogg_ai_api_key"] = Field("jogg_ai_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)




def _json_input(value, model):
    try:
        raw = json.loads(value) if isinstance(value, str) else value
        parsed = TypeAdapter(model).validate_python(raw)
        return TypeAdapter(model).dump_json(parsed, exclude_none=True).decode()
    except (ValueError, TypeError):
        raise ValueError("Enter JSON matching the documented field structure") from None


class JoggAiGetCurrentUserConfig(_Input):
    'Get Current User Information'
    operation: Literal['get_current_user'] = Field('get_current_user', json_schema_extra={"ui:hidden": True})


class JoggAiGetRemainingQuotaConfig(_Input):
    'Get Remaining Quota'
    operation: Literal['get_remaining_quota'] = Field('get_remaining_quota', json_schema_extra={"ui:hidden": True})


class JoggAiListPublicAvatarsConfig(_Input):
    'Get Public Avatar List'
    operation: Literal['list_public_avatars'] = Field('list_public_avatars', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='Page number for pagination', ge=1)
    page_size: int = Field(10, description='Number of items per page', ge=1, le=100)
    aspect_ratio: Optional[Literal['portrait', 'landscape', 'square']] = Field(None, description='Filter by aspect ratio')
    style: Optional[Literal['professional', 'social']] = Field(None, description='Filter by avatar style')
    gender: Optional[Literal['female', 'male']] = Field(None, description='Filter by avatar gender')
    age: Optional[Literal['adult', 'senior', 'young_adult']] = Field(None, description='Filter by age group')
    scene: Optional[Literal['lifestyle', 'outdoors', 'business', 'studio', 'health_fitness', 'education', 'news']] = Field(None, description='Filter by scene type')
    ethnicity: Optional[Literal['european', 'african', 'south_asian', 'east_asian', 'middle_eastern', 'south_american', 'north_american']] = Field(None, description='Filter by ethnicity')


class JoggAiListCustomAvatarsConfig(_Input):
    'Get Instant Avatar List'
    operation: Literal['list_custom_avatars'] = Field('list_custom_avatars', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='Page number for pagination', ge=1)
    page_size: int = Field(10, description='Number of items per page', ge=1, le=100)
    name: Optional[str] = Field(None, description='Avatar name filter - search avatars by name')
    status: Optional[Literal['processing', 'completed', 'failed']] = Field(None, description='Status filter')


class JoggAiListVoicesConfig(_Input):
    'Get Timbre List'
    operation: Literal['list_voices'] = Field('list_voices', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='Page number for pagination', ge=1)
    page_size: int = Field(10, description='Number of items per page', ge=1, le=100)
    gender: Optional[Literal['female', 'male']] = Field(None, description='Filter by gender')
    language: Optional[str] = Field(None, description='Filter by language')
    age: Optional[Literal['young', 'middle_aged', 'old']] = Field(None, description='Filter by age group')
    use_case: Optional[str] = Field(None, description='Filter by use case')


class JoggAiListCustomVoicesConfig(_Input):
    'Get User Timbre List'
    operation: Literal['list_custom_voices'] = Field('list_custom_voices', json_schema_extra={"ui:hidden": True})
    language: Optional[str] = Field(None, description='Filter by language')


class JoggAiListMusicConfig(_Input):
    'List background music'
    operation: Literal['list_music'] = Field('list_music', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='Page number', ge=1)
    page_size: int = Field(10, description='Items per page', ge=1, le=100)


class JoggAiListVisualStylesConfig(_Input):
    'List visual styles'
    operation: Literal['list_visual_styles'] = Field('list_visual_styles', json_schema_extra={"ui:hidden": True})
    aspect_ratio: Optional[Literal['portrait', 'landscape', 'square']] = Field(None, description='Filter by aspect ratio')


class JoggAiListTemplatesConfig(_Input):
    'List index templates'
    operation: Literal['list_templates'] = Field('list_templates', json_schema_extra={"ui:hidden": True})
    aspect_ratio: Optional[Literal['portrait', 'landscape', 'square']] = Field(None, description='Screen aspect ratio filter:\n* portrait - Portrait [9:16]\n* landscape - Landscape [16:9]\n* square - Square [1:1]\n')


class JoggAiListCustomTemplatesConfig(_Input):
    "List user's custom templates"
    operation: Literal['list_custom_templates'] = Field('list_custom_templates', json_schema_extra={"ui:hidden": True})
    aspect_ratio: Optional[Literal['portrait', 'landscape', 'square']] = Field(None, description='Filter by aspect ratio')


class JoggAiCreateAvatarVideoConfigAvatar(_Input):
    avatar_type: Literal[0, 1] = Field(..., description='Source type of the avatar:\n* 0 - Public avatar\n* 1 - Custom avatar\n')
    avatar_id: int = Field(..., description='ID of the avatar to use')


class JoggAiCreateAvatarVideoConfigVoice(_Input):
    type: Literal['script', 'audio'] = Field(..., description='Voice input type', min_length=1)
    script: Optional[str] = Field(None, description='Text script for voice synthesis (required when type is "script")')
    audio_url: Optional[str] = Field(None, description='Audio file URL for voice input (required when type is "audio")')
    voice_id: str = Field(..., description='Voice ID for text-to-speech', min_length=1)

    @model_validator(mode="after")
    def require_voice_source(self):
        if self.script and self.audio_url:
            raise ValueError("Supply script or audio_url, not both")
        if self.type == "script" and not self.script:
            raise ValueError("Supply a script for script voice input")
        if self.type == "audio" and not self.audio_url:
            raise ValueError("Supply audio_url for audio voice input")
        return self


class JoggAiCreateAvatarVideoConfig(_Input):
    'Create talking avatar video'
    operation: Literal['create_avatar_video'] = Field('create_avatar_video', json_schema_extra={"ui:hidden": True})
    avatar: Annotated[str, BeforeValidator(lambda value: _json_input(value, JoggAiCreateAvatarVideoConfigAvatar))] = Field(..., description='Avatar configuration', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "placeholder": '{\n  "avatar_id": 81,\n  "avatar_type": 0\n}'})
    voice: Annotated[str, BeforeValidator(lambda value: _json_input(value, JoggAiCreateAvatarVideoConfigVoice))] = Field(..., description='Voice configuration including script or audio input', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "placeholder": '{\n  "type": "script",\n  "voice_id": "en-US-ChristopherNeural",\n  "script": "Welcome to JoggAI! Create amazing videos with AI avatars in minutes."\n}'})
    aspect_ratio: Literal['portrait', 'landscape', 'square'] = Field(..., description='Aspect ratio of the output video', min_length=1)
    screen_style: Literal[1, 2, 3] = Field(..., description='Background style:\n* 1 - Full screen\n* 2 - Split screen\n* 3 - Picture in picture\n')
    caption: Optional[bool] = Field(None, description='Enable or disable subtitles')
    webhook_url: Optional[str] = Field(None, description='Webhook URL for status notifications')
    video_name: Optional[str] = Field(None, description='Custom name for the video')


class JoggAiGetAvatarVideoConfig(_Input):
    'Retrieve talking avatar video'
    operation: Literal['get_avatar_video'] = Field('get_avatar_video', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., description='Video ID from video creation endpoint', min_length=1)


class JoggAiCreateProductConfigMediaItem(_Input):
    type: Optional[Literal[1, 2]] = Field(None, description='Media type:\n* 1 - Image\n* 2 - Video\n')
    name: Optional[str] = Field(None)
    url: Optional[str] = Field(None)
    description: Optional[str] = Field(None)


class JoggAiCreateProductConfig(_Input):
    'Create Product V2'
    operation: Literal['create_product'] = Field('create_product', json_schema_extra={"ui:hidden": True})
    url: Optional[str] = Field(None, description='Product URL to crawl information from')
    name: Optional[str] = Field(None, description='Product name (required if no URL)')
    description: Optional[str] = Field(None, description='Product description and selling points')
    target_audience: Optional[str] = Field(None, description='Target audience')
    media: Optional[Annotated[str, BeforeValidator(lambda value: _json_input(value, list[JoggAiCreateProductConfigMediaItem]))]] = Field(None, description='Media resources array', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "placeholder": '[\n  {\n    "type": 1,\n    "name": "product-image.jpg",\n    "url": "https://example.com/yoga-mat.jpg",\n    "description": "Main product image"\n  }\n]'})

    @model_validator(mode="after")
    def require_product_source(self):
        if not self.url and not self.name:
            raise ValueError("Supply a product URL or name")
        return self


class JoggAiUpdateProductConfigMediaItem(_Input):
    type: Optional[Literal[1, 2]] = Field(None)
    name: Optional[str] = Field(None)
    url: Optional[str] = Field(None)
    description: Optional[str] = Field(None)


class JoggAiUpdateProductConfig(_Input):
    'Update Product V2'
    operation: Literal['update_product'] = Field('update_product', json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., description='Product ID from creation step', min_length=1)
    name: Optional[str] = Field(None, description='Updated product name')
    description: Optional[str] = Field(None, description='Updated description')
    target_audience: Optional[str] = Field(None, description='Updated target audience')
    media: Optional[Annotated[str, BeforeValidator(lambda value: _json_input(value, list[JoggAiUpdateProductConfigMediaItem]))]] = Field(None, description='Updated media resources', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class JoggAiCreateProductVideoConfigVideoSpec(_Input):
    aspect_ratio: Literal['portrait', 'landscape', 'square'] = Field('landscape', description='Video aspect ratio')
    length: Literal['15', '30', '60'] = Field(..., description='Video length in seconds', min_length=1)
    caption: Optional[bool] = Field(None, description='Enable or disable subtitles')
    name: Optional[str] = Field(None, description='Video name')


class JoggAiCreateProductVideoConfigAvatar(_Input):
    id: int = Field(..., description='Avatar ID')
    type: Optional[Literal[0, 1]] = Field(None, description='Source type of the avatar:\n* 0 - Public avatar\n* 1 - Custom avatar\n')


class JoggAiCreateProductVideoConfigVoice(_Input):
    id: Optional[str] = Field(None, description='Voice ID for text-to-speech')


class JoggAiCreateProductVideoConfigAudio(_Input):
    music_id: Optional[int] = Field(None, description='Background music ID', ge=0)


class JoggAiCreateProductVideoConfigScript(_Input):
    style: Literal["Don't Worry", 'Storytime', 'Discovery', 'Data', 'Top 3 reasons', 'Light marketing'] = Field(..., description='Script writing style', min_length=1)
    language: str = Field(..., description='Script generation language', min_length=1)


class JoggAiCreateProductVideoConfig(_Input):
    'Generate Video from Product'
    operation: Literal['create_product_video'] = Field('create_product_video', json_schema_extra={"ui:hidden": True})
    product_id: str = Field(..., description='Product ID from product creation', min_length=1)
    visual_style: Optional[str] = Field(None, description='Visual style name from visual list')
    video_spec: Annotated[str, BeforeValidator(lambda value: _json_input(value, JoggAiCreateProductVideoConfigVideoSpec))] = Field(..., description='Video specification settings', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "placeholder": '{\n  "aspect_ratio": "portrait",\n  "length": "30",\n  "caption": true\n}'})
    avatar: Annotated[str, BeforeValidator(lambda value: _json_input(value, JoggAiCreateProductVideoConfigAvatar))] = Field(..., description='Avatar configuration', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "placeholder": '{\n  "id": 81,\n  "type": 0\n}'})
    voice: Annotated[str, BeforeValidator(lambda value: _json_input(value, JoggAiCreateProductVideoConfigVoice))] = Field(..., description='Voice configuration', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "placeholder": '{\n  "id": "en-US-ChristopherNeural"\n}'})
    audio: Annotated[str, BeforeValidator(lambda value: _json_input(value, JoggAiCreateProductVideoConfigAudio))] = Field(..., description='Audio configuration', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "placeholder": '{}'})
    script: Annotated[str, BeforeValidator(lambda value: _json_input(value, JoggAiCreateProductVideoConfigScript))] = Field(..., description='Script configuration', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "placeholder": '{\n  "style": "Storytime",\n  "language": "english"\n}'})
    override_script: Optional[str] = Field(None, description='Override the auto-generated script')
    webhook_url: Optional[str] = Field(None, description='Webhook URL for status notifications')


class JoggAiGetProductVideoConfig(_Input):
    'Check Product Video Status'
    operation: Literal['get_product_video'] = Field('get_product_video', json_schema_extra={"ui:hidden": True})
    product_video_id: str = Field(..., description='Product video ID', min_length=1)


class JoggAiListProductVideosConfig(_Input):
    'Get Product Video List'
    operation: Literal['list_product_videos'] = Field('list_product_videos', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='page', ge=1)
    page_size: int = Field(10, description='page_size', ge=1, le=100)
    status: Optional[Literal[3, 4, 5]] = Field(None, description='Filter by status:\n* 3 - Processing\n* 4 - Success\n* 5 - Failed\n')
    sort_by: str = Field('created_at', description='sort_by')
    sort_order: Literal['asc', 'desc'] = Field('desc', description='sort_order')


class JoggAiGenerateScriptsConfigProductInfoData(_Input):
    id: Optional[str] = Field(None, description="Product ID (required when source_type is 'id')")
    name: Optional[str] = Field(None, description="Product name (required when source_type is 'details')")
    description: Optional[str] = Field(None, description="Product description and selling points (required when source_type is 'details')")


class JoggAiGenerateScriptsConfigProductInfo(_Input):
    source_type: Literal['id', 'details'] = Field(..., description='Source type of product information:\n* id - Use product ID from product creation endpoint\n* details - Provide product details directly\n', min_length=1)
    data: JoggAiGenerateScriptsConfigProductInfoData = Field(..., description='Product data based on source_type', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @model_validator(mode="after")
    def require_product_details(self):
        if self.source_type == "id" and not self.data.id:
            raise ValueError("Supply the product ID")
        if self.source_type == "details" and not (self.data.name and self.data.description):
            raise ValueError("Supply product name and description")
        return self


class JoggAiGenerateScriptsConfig(_Input):
    'Submit AI script generation request'
    operation: Literal['generate_scripts'] = Field('generate_scripts', json_schema_extra={"ui:hidden": True})
    language: Literal['english', 'filipino', 'french', 'german', 'hindi', 'indonesian', 'italian', 'japanese', 'korean', 'malay', 'portuguese', 'russian', 'spanish', 'thai', 'vietnamese', 'arabic', 'greek', 'turkish', 'slovenian', 'croatian', 'romanian', 'chinese', 'bengali', 'urdu', 'hungarian', 'traditional-chinese', 'polish', 'cantonese', 'danish', 'malayalam', 'tamil', 'telugu', 'czech', 'hebrew', 'zulu', 'swedish', 'lithuanian', 'dutch', 'flemish', 'norwegian', 'finnish', 'bulgarian', 'latvian', 'ukrainian', 'mongolian', 'persian', 'odia', 'assamese', 'kannada', 'tagalog', 'amharic', 'serbian', 'slovak', 'swahili'] = Field(..., description='Script generation language', min_length=1)
    video_length_seconds: Literal['15', '30', '60'] = Field(..., description='Desired video length in seconds', min_length=1)
    script_style: Literal["Don't Worry", 'Storytime', 'Discovery', 'Data', 'Top 3 reasons', 'Light marketing'] = Field(..., description="Script writing style for video content:\n* Don't Worry - Casual and reassuring tone\n* Storytime - Narrative and engaging storytelling approach\n* Discovery - Exploratory and revealing style\n* Data - Fact-based and analytical presentation\n* Top 3 reasons - List-based persuasive format\n* Light marketing - Soft-sell marketing approach\n", min_length=1)
    product_info: Annotated[str, BeforeValidator(lambda value: _json_input(value, JoggAiGenerateScriptsConfigProductInfo))] = Field(..., description='Product information for script generation', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "placeholder": '{\n  "source_type": "id",\n  "data": {\n    "id": "NTQ0MTkzNjg"\n  }\n}'})
    target_audience: Optional[str] = Field(None, description='Target audience for the product (optional)')


class JoggAiGetScriptResultsConfig(_Input):
    'Get AI script generation status'
    operation: Literal['get_script_results'] = Field('get_script_results', json_schema_extra={"ui:hidden": True})
    task_id: str = Field(..., description='Task ID from script generation request', min_length=1)


class JoggAiCreateTemplateVideoConfigVariablesItemProperties(_Input):
    content: Optional[str] = Field(None, description='Variable content:\n* For text/script type: Required, the text content\n* For image/video type: Optional, can be used as URL (compatible with url field)\n')
    url: Optional[str] = Field(None, description='Media resource URL for image/video type.\nEither url or asset_id is required for image/video type.\n')
    asset_id: Optional[int] = Field(None, description='Asset ID for image/video type.\nObtained after uploading via /v2/upload/asset endpoint.\nEither url or asset_id is required for image/video type.\n')
    webhook_url: Optional[str] = Field(None, description='Webhook URL for status notifications')


class JoggAiCreateTemplateVideoConfigVariablesItem(_Input):
    type: Literal['text', 'image', 'video', 'script'] = Field(..., description='Variable type', min_length=1)
    name: str = Field(..., description='Variable name', min_length=1)
    properties: JoggAiCreateTemplateVideoConfigVariablesItemProperties = Field(..., json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @model_validator(mode="after")
    def require_variable_content(self):
        if self.type in {"text", "script"} and not self.properties.content:
            raise ValueError("Supply text or script variable content")
        if self.type in {"image", "video"} and not (self.properties.url or self.properties.asset_id or self.properties.content):
            raise ValueError("Supply a media URL or asset ID")
        return self


class JoggAiCreateTemplateVideoConfig(_Input):
    'Create video from template'
    operation: Literal['create_template_video'] = Field('create_template_video', json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., description='Template ID')
    video_name: Optional[str] = Field(None, description='Custom name for the video')
    avatar_id: Optional[int] = Field(None, description='Digital person ID')
    avatar_type: Optional[Literal[0, 1]] = Field(None, description='Source type of the avatar:\n* 0 - Public avatar\n* 1 - Custom avatar\n')
    voice_language: str = Field(..., description='Voice language for text-to-speech', min_length=1)
    voice_id: Optional[str] = Field(None, description='Voice ID for text-to-speech')
    captions_enabled: Optional[bool] = Field(None, description='Enable captions/subtitles')
    background_music_id: Optional[int] = Field(None, description='Background music ID')
    variables: Annotated[str, BeforeValidator(lambda value: _json_input(value, list[JoggAiCreateTemplateVideoConfigVariablesItem]))] = Field(..., description='Variables to replace in the template', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "placeholder": '[\n  {\n    "type": "text",\n    "name": "product_name",\n    "properties": {\n      "content": "Amazing Smart Watch"\n    }\n  },\n  {\n    "type": "script",\n    "name": "script",\n    "properties": {\n      "content": "Discover the future of wearable technology with our Amazing Smart Watch!"\n    }\n  }\n]'})
    disable_random_trans: Optional[bool] = Field(None, description='Disable random transitions')
    disable_random_moving: Optional[bool] = Field(None, description='Disable random image effects')
    disable_trans: Optional[bool] = Field(None, description='Disable all transitions')
    disable_moving: Optional[bool] = Field(None, description='Disable all image effects')


class JoggAiGetTemplateVideoConfig(_Input):
    'Get template video status and details'
    operation: Literal['get_template_video'] = Field('get_template_video', json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., description='Video ID', min_length=1)

JoggAiConfig = Annotated[Union[
    JoggAiGetCurrentUserConfig,
    JoggAiGetRemainingQuotaConfig,
    JoggAiListPublicAvatarsConfig,
    JoggAiListCustomAvatarsConfig,
    JoggAiListVoicesConfig,
    JoggAiListCustomVoicesConfig,
    JoggAiListMusicConfig,
    JoggAiListVisualStylesConfig,
    JoggAiListTemplatesConfig,
    JoggAiListCustomTemplatesConfig,
    JoggAiCreateAvatarVideoConfig,
    JoggAiGetAvatarVideoConfig,
    JoggAiCreateProductConfig,
    JoggAiUpdateProductConfig,
    JoggAiCreateProductVideoConfig,
    JoggAiGetProductVideoConfig,
    JoggAiListProductVideosConfig,
    JoggAiGenerateScriptsConfig,
    JoggAiGetScriptResultsConfig,
    JoggAiCreateTemplateVideoConfig,
    JoggAiGetTemplateVideoConfig,
], Field(discriminator="operation")]


class JoggAiFullConfig(NodeConfig[JoggAiConfig, JoggAiAPIKeyCredential]):
    pass


ROUTES = {
    'get_current_user': ('GET', '/v2/user/whoami'),
    'get_remaining_quota': ('GET', '/v2/user/remaining_quota'),
    'list_public_avatars': ('GET', '/v2/avatars/public'),
    'list_custom_avatars': ('GET', '/v2/avatars/custom'),
    'list_voices': ('GET', '/v2/voices'),
    'list_custom_voices': ('GET', '/v2/voices/custom'),
    'list_music': ('GET', '/v2/musics'),
    'list_visual_styles': ('GET', '/v2/visual_styles'),
    'list_templates': ('GET', '/v2/templates'),
    'list_custom_templates': ('GET', '/v2/templates/custom'),
    'create_avatar_video': ('POST', '/v2/create_video_from_avatar'),
    'get_avatar_video': ('GET', '/v2/avatar_video/{id}'),
    'create_product': ('POST', '/v2/product'),
    'update_product': ('PUT', '/v2/product'),
    'create_product_video': ('POST', '/v2/create_video_from_product'),
    'get_product_video': ('GET', '/v2/product_video/{product_video_id}'),
    'list_product_videos': ('GET', '/v2/product_videos'),
    'generate_scripts': ('POST', '/v2/ai_scripts'),
    'get_script_results': ('GET', '/v2/ai_scripts/results/{task_id}'),
    'create_template_video': ('POST', '/v2/create_video_with_template'),
    'get_template_video': ('GET', '/v2/template_video/{video_id}'),
}

JSON_FIELDS = {'create_avatar_video': ['avatar', 'voice'], 'create_product': ['media'], 'update_product': ['media'], 'create_product_video': ['video_spec', 'avatar', 'voice', 'audio', 'script'], 'generate_scripts': ['product_info'], 'create_template_video': ['variables']}


class JoggAiNode(WorkflowNode):
    integration_type = "automation-jogg-ai"
    connection_evidence = ConnectionEvidence(
        noun="Jogg Ai account", identity_operation="get_current_user",
        identity_keys=("username", "email"),
    )

    @classmethod
    def get_config_model(cls):
        return JoggAiFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Jogg Ai API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for name in tuple(values):
            if "{" + name + "}" in path:
                if not re.fullmatch(r"[A-Za-z0-9_-]+", str(values[name])):
                    raise ValueError("Use a single Jogg Ai resource ID")
                path = path.replace("{" + name + "}", quote(str(values.pop(name)), safe=""))
        for name in JSON_FIELDS.get(config.operation, ()):
            if name in values:
                values[name] = json.loads(values[name])
        key = self.config.credentials.api_key
        async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
            response = await client.request(
                method, "https://api.jogg.ai" + path,
                headers={"x-api-key": key, "Accept": "application/json"},
                **({"params": values} if method == "GET" else {"json": values}),
            )
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("Jogg Ai returned an unexpected redirect")
        body = response.json()
        if not isinstance(body, dict) or type(body.get("code")) is not int or not isinstance(body.get("msg"), str):
            raise ValueError("Jogg Ai returned an invalid response envelope")
        if body["code"] != 0:
            raise ValueError(f"Jogg Ai {body['code']}: {body['msg'].replace(key, '[redacted]')}")
        if config.operation == "update_product":
            result = {"status": "success", "code": body["code"], "message": body["msg"]}
            await self.emit(result)
            return result
        if not isinstance(body.get("data"), (dict, list)):
            raise ValueError("Jogg Ai returned no result data")
        # Keep asynchronous task status and pagination exactly as the provider returned them.
        result = {"status": "success", "data": body["data"]}
        await self.emit(result)
        return result
