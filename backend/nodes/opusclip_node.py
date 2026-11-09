"""OpusClip Open API v1.0: projects, clips, collections and social publishing.

Contract: https://help.opus.pro/api-reference/openapi.json
Each operation makes one documented request. Job creation returns a job ID;
poll explicitly for completion. Writes are never retried automatically.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, Json, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.opus.pro"
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class OpusClipAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="OpusClip API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://clip.opus.pro/",
        "x-credential-instructions": "Copy your organization's API access key from the lower left corner of the OpusClip dashboard. API access requires an eligible plan and credits for processing. Paste the key without the Bearer prefix. NoClick checks your connected social accounts.",
    })
    credential_type: Literal["opusclip_api_key"] = Field("opusclip_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=8192, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def structured_json(cls, value):
        # The editor stores JSON text; workflow expressions may supply objects.
        if isinstance(value, dict):
            value = dict(value)
            for name, field in cls.model_fields.items():
                if (field.json_schema_extra or {}).get("ui:widget") == "code_editor" and isinstance(value.get(name), (dict, list)):
                    value[name] = json.dumps(value[name], allow_nan=False)
        return value


class OpusClipListBrandTemplatesConfig(_Input):
    """List brand templates."""
    operation: Literal['list_brand_templates'] = Field('list_brand_templates', json_schema_extra={"ui:hidden": True})
    q: Literal['mine'] = Field('mine', description='', title='Q')


class ConclusionAction(_Input):
    type: Literal['EMAIL', 'WEBHOOK'] = Field(..., description='Specifies the action to be taken upon project conclusion. Options include sending an email or triggering a webhook.', title='Type', examples=['EMAIL'])
    notifyFailure: bool | None = Field(None, description='Indicates whether to notify on failure.', title='Notify failure', examples=[True])
    email: str | None = Field(None, description='Email address to send notifications to, if type is EMAIL.', title='Email', min_length=1, examples=['user@example.com'])
    url: str | None = Field(None, description='Webhook URL to trigger, if type is WEBHOOK.', title='Url', min_length=1, examples=['https://example.com/webhook'])


class CurationRange(_Input):
    startSec: float | None = Field(None, description='The start time of the range to be curated.', title='Start sec', examples=[106])
    endSec: float | None = Field(None, description='The end time of the range to be curated.', title='End sec', examples=[204])


class CurationPreferences(_Input):
    topicKeywords: list[str] | None = Field(None, description='Keywords used to find relevant moments to clip from', title='Topic keywords', examples=[['Fancy Words']])
    range: CurationRange | None = Field(None, description='The range of the original long-form video to generate clips from.', title='Range', examples=[{'startSec': 106, 'endSec': 204}])
    genre: Literal['Auto', 'Q&A', 'Commentary', 'Marketing', 'Webinar', 'Motivational speech', 'Podcast', 'Academic', 'Listicle', 'Product reviews', 'How-to', 'Comedy', 'Sports commentary', 'Church', 'News', 'Vlog', 'Gaming', 'Others'] | None = Field(None, description='The genre of the clips, will apply suitable AI curation models to find the best results.', title='Genre', examples=['Auto'])
    enableAutoHook: bool | None = Field(None, description='Whether to add an AI-generated headline ("auto headline") over the first seconds of each clip. Disabled by default for API submissions: omit it or send `false` and no headline is added. Only applies to a clipping run, so it has no effect together with `skipCurate` or `skipSlicing`.', title='Enable auto hook', examples=[False])


class ImportPreferences(_Input):
    sourceLang: str | None = Field(None, description='Select the language to detect the video\'s spoken content, or leave it blank for automatic detection. Using ISO-639 language codes, examples: "en" for English, "de" for German, "fr" for French.', title='Source lang', min_length=1, examples=['en'])


class OpusClipCreateClipProjectConfig(_Input):
    """Create clip project."""
    operation: Literal['create_clip_project'] = Field('create_clip_project', json_schema_extra={"ui:hidden": True})
    videoUrl: str = Field(..., description='This parameter defines the url of the long-form video. OpusClip can import public videos from the following platforms: \n- YouTube, Google Drive, Vimeo, Zoom, Rumble, Twitch, Facebook, LinkedIn, X, Dropbox, Riverside, Loom, Frame.io, StreamYard\n- Any public video s3 link of an mp4 file (up to 10GB per video)', title='Video url', min_length=1, examples=['https://www.youtube.com/watch?v=LXvv6CbGg8A'])
    conclusionActions: Json[list[ConclusionAction]] | None = Field(None, description='Actions to be taken upon project conclusion, such as sending an email or triggering a webhook.', title='Conclusion actions', json_schema_extra=JSON_EDITOR, examples=[[{'type': 'EMAIL', 'notifyFailure': True, 'email': 'opusclip@opus.pro'}]])
    curationPref: Json[CurationPreferences] | None = Field(None, description='Preferences for advanced curation of the video.', title='Curation pref', json_schema_extra=JSON_EDITOR, examples=[{'range': {'startSec': 28, 'endSec': 636}, 'topicKeywords': ['OpusClip'], 'genre': 'Auto'}])
    importPref: Json[ImportPreferences] | None = Field(None, description='Preferences for importing the video, such as source language.', title='Import pref', json_schema_extra=JSON_EDITOR, examples=[{'sourceLang': 'auto'}])
    brandTemplateId: str | None = Field(None, description='ID of the brand template to be used for the project.', title='Brand template id', min_length=1, examples=['preset-fancy-Karaoke'])


class OpusClipGetClipProjectConfig(_Input):
    """Get clip project."""
    operation: Literal['get_clip_project'] = Field('get_clip_project', json_schema_extra={"ui:hidden": True})
    projectId: str = Field(..., description='', title='Project id', min_length=1)


class OpusClipUpdateProjectVisibilityConfig(_Input):
    """Update project visibility."""
    operation: Literal['update_project_visibility'] = Field('update_project_visibility', json_schema_extra={"ui:hidden": True})
    projectId: str = Field(..., description='', title='Project id', min_length=1)
    visibility: Literal['DEFAULT', 'PUBLIC'] = Field(..., description='The visibility of the project. `DEFAULT`: Team members can open, edit and export the project. `PUBLIC`: Anyone can open, edit and export the project.', title='Visibility', examples=['PUBLIC'])


class OpusClipListExportableClipsConfig(_Input):
    """List exportable clips."""
    operation: Literal['list_exportable_clips'] = Field('list_exportable_clips', json_schema_extra={"ui:hidden": True})
    organization_id: str | None = Field(None, description='Organization ID. Required for users with multiple organizations.', title='Organization id', min_length=1, examples=['org_Example00000001'])
    q: Literal['findByCollectionId', 'findByProjectId'] = Field('findByProjectId', description='Query type', title='Q', examples=['findByProjectId'])
    projectId: str | None = Field(None, description='Project ID, required when q=findByProjectId', title='Project id', min_length=1, examples=['P0000000demo'])
    collectionId: str | None = Field(None, description='Collection ID, required when q=findByCollectionId', title='Collection id', min_length=1, examples=['xmAwhhFi0IJt'])
    pageNum: float | None = Field(None, description='Page Num, started with 1', title='Page num', ge=1, examples=[1])
    pageSize: float | None = Field(None, description='Page Size', title='Page size', ge=1, examples=[10])

    @model_validator(mode="after")
    def selected_source(self):
        if not getattr(self, "projectId" if self.q == "findByProjectId" else "collectionId"):
            raise ValueError("Supply the ID selected by the query type")
        return self


class OpusClipRemoveCollectionContentConfig(_Input):
    """Remove collection content."""
    operation: Literal['remove_collection_content'] = Field('remove_collection_content', json_schema_extra={"ui:hidden": True})
    q: Literal['findByCollectionIdAndContentId'] = Field('findByCollectionIdAndContentId', description='**Query type**\n `findByCollectionIdAndContentId` is the only valid value, means delete relation by collectionId + contentId', title='Q')
    collectionId: str = Field(..., description='The collectionID of the collection that you want to remove the clip from.', title='Collection id', min_length=1, examples=['xmAwhhFi0IJt'])
    contentId: str = Field(..., description='The ID of the clip that you want to remove from the collection. FullClipId: {projectId}.{curationId}', title='Content id', min_length=1, examples=['P0000000demo.CUexample2'])


class OpusClipAddCollectionContentConfig(_Input):
    """Add collection content."""
    operation: Literal['add_collection_content'] = Field('add_collection_content', json_schema_extra={"ui:hidden": True})
    collectionId: str = Field(..., description='The collectionID of the collection that you want to add the clip to.', title='Collection id', min_length=1, examples=['xmAwhhFi0IJt'])
    contentId: str = Field(..., description='The ID of the clip that you want to add to the collection. FullClipId: {projectId}.{curationId}', title='Content id', min_length=1, examples=['P0000000demo.CUexample2'])


class OpusClipDeleteCollectionConfig(_Input):
    """Delete collection."""
    operation: Literal['delete_collection'] = Field('delete_collection', json_schema_extra={"ui:hidden": True})
    collectionId: str = Field(..., description='The unique collection ID of the collection that you want to delete.', title='Collection id', min_length=1)


class OpusClipCreateCollectionConfig(_Input):
    """Create collection."""
    operation: Literal['create_collection'] = Field('create_collection', json_schema_extra={"ui:hidden": True})
    collectionName: str = Field(..., description='The name of the collection that you want to create.', title='Collection name', min_length=1, examples=['Opus demo clips'])


class OpusClipListCollectionsConfig(_Input):
    """List collections."""
    operation: Literal['list_collections'] = Field('list_collections', json_schema_extra={"ui:hidden": True})
    q: Literal['findByContentId', 'mine'] = Field('mine', description='**Query type**\n `q = mine` means list collections of your account.\n `q = findByContentId` means list collections contained the specific content(clip).', title='Q', examples=['mine'])
    contentId: str | None = Field(None, description='If specified, will only return collections that contain the clip with this contentID.', title='Content id', min_length=1, examples=['P0000000demo.CUexample2'])

    @model_validator(mode="after")
    def selected_content(self):
        if self.q == "findByContentId" and not self.contentId:
            raise ValueError("Supply contentId when finding collections by content")
        return self


class OpusClipExportCollectionConfig(_Input):
    """Export collection."""
    operation: Literal['export_collection'] = Field('export_collection', json_schema_extra={"ui:hidden": True})
    collectionId: str = Field(..., description='The collectionID of the collection that you want to export', title='Collection id', min_length=1)


class CensorOptions(_Input):
    beepSound: bool | None = Field(None, description='Use beep sound instead of the censored words.', title='Beep sound', examples=[True])


class OpusClipCreateCensorJobConfig(_Input):
    """Create censor job."""
    operation: Literal['create_censor_job'] = Field('create_censor_job', json_schema_extra={"ui:hidden": True})
    projectId: str = Field(..., description='The project id that you want to censor.', title='Project id', min_length=1, examples=['P0000000demo'])
    clipId: str = Field(..., description='The clip id that you want to censor.', title='Clip id', min_length=1, examples=['lDIOHRzdac'])
    options: Json[CensorOptions] | None = Field(None, description='Some options for the censor job.', title='Options', json_schema_extra=JSON_EDITOR, examples=[{'beepSound': False}])


class OpusClipGetCensorJobConfig(_Input):
    """Get censor job."""
    operation: Literal['get_censor_job'] = Field('get_censor_job', json_schema_extra={"ui:hidden": True})
    jobId: str = Field(..., description='The jobId that you want to get the status of.', title='Job id', min_length=1)


class OpusClipListSocialAccountsConfig(_Input):
    """List social accounts."""
    operation: Literal['list_social_accounts'] = Field('list_social_accounts', json_schema_extra={"ui:hidden": True})
    q: Literal['mine'] = Field('mine', description='Query type', title='Q', examples=['mine'])


class OpusClipCreateSocialCopyJobConfig(_Input):
    """Create social copy job."""
    operation: Literal['create_social_copy_job'] = Field('create_social_copy_job', json_schema_extra={"ui:hidden": True})
    projectId: str = Field(..., description='Project ID', title='Project id', min_length=1)
    clipId: str = Field(..., description='Bare clip ID (e.g. `CUexample1`). **Not** the composite `{projectId}.{clipId}` form returned as `id` by `GET /api/exportable-clips` — pass only the part after the dot.', title='Clip id', min_length=1)
    postAccountId: str = Field(..., description='Unique ID of the connected social account record', title='Post account id', min_length=1)
    subAccountId: str = Field(..., description='Sub-account ID used by Facebook pages, Instagram business accounts, or LinkedIn', title='Sub account id', min_length=1)
    prompt: str | None = Field(None, description='Custom style or tone instruction for generation', title='Prompt', min_length=1)
    forceRegenerate: bool | None = Field(None, description='Whether to bypass the cached result and regenerate', title='Force regenerate')


class OpusClipGetSocialCopyJobConfig(_Input):
    """Get social copy job."""
    operation: Literal['get_social_copy_job'] = Field('get_social_copy_job', json_schema_extra={"ui:hidden": True})
    jobId: str = Field(..., description='Unique ID of the social copy generation job', title='Job id', min_length=1)


class PostCustom(_Input):
    description: str | None = Field(None, description='Description of the post, including hashtags', title='Description', min_length=1)
    privacy: Literal['public', 'private', 'unlisted'] | None = Field(None, description='Privacy setting for YouTube', title='Privacy')


class PostDetail(_Input):
    title: str = Field(..., description='Title of the post', title='Title', min_length=1)
    mediaType: str | None = Field(None, description='Media type. Supported values depend on the connected platform', title='Media type', min_length=1)
    custom: PostCustom | None = Field(None, description='', title='Custom')


class OpusClipPublishPostConfig(_Input):
    """Publish post."""
    operation: Literal['publish_post'] = Field('publish_post', json_schema_extra={"ui:hidden": True})
    projectId: str = Field(..., description='Project ID', title='Project id', min_length=1)
    clipId: str = Field(..., description='Bare clip ID (e.g. `qU3iVMSO77`). **Not** the composite `{projectId}.{clipId}` form returned as `id` by `GET /api/exportable-clips` — pass only the part after the dot.', title='Clip id', min_length=1)
    postAccountId: str = Field(..., description='Unique ID of the connected social account record', title='Post account id', min_length=1)
    subAccountId: str | None = Field(None, description='Sub-account ID used by Facebook pages, Instagram business accounts, or LinkedIn', title='Sub account id', min_length=1)
    postDetail: Json[PostDetail] = Field(..., description='', title='Post detail', json_schema_extra=JSON_EDITOR)


class OpusClipSchedulePostConfig(_Input):
    """Schedule post."""
    operation: Literal['schedule_post'] = Field('schedule_post', json_schema_extra={"ui:hidden": True})
    projectId: str = Field(..., description='Project ID', title='Project id', min_length=1)
    clipId: str = Field(..., description='Bare clip ID (e.g. `qU3iVMSO77`). **Not** the composite `{projectId}.{clipId}` form returned as `id` by `GET /api/exportable-clips` — pass only the part after the dot.', title='Clip id', min_length=1)
    postAccountId: str = Field(..., description='Unique ID of the connected social account record', title='Post account id', min_length=1)
    subAccountId: str | None = Field(None, description='Sub-account ID used by Facebook pages, Instagram business accounts, or LinkedIn', title='Sub account id', min_length=1)
    publishAt: str = Field(..., description='Future publish time in UTC ISO 8601 format', title='Publish at', min_length=1)
    postDetail: Json[PostDetail] = Field(..., description='', title='Post detail', json_schema_extra=JSON_EDITOR)


class OpusClipCancelScheduledPostConfig(_Input):
    """Cancel scheduled post."""
    operation: Literal['cancel_scheduled_post'] = Field('cancel_scheduled_post', json_schema_extra={"ui:hidden": True})
    scheduleId: str = Field(..., description='Unique ID of the schedule task to cancel', title='Schedule id', min_length=1)


class OpusClipCreateThumbnailJobConfig(_Input):
    """Create thumbnail job."""
    operation: Literal['create_thumbnail_job'] = Field('create_thumbnail_job', json_schema_extra={"ui:hidden": True})
    jobType: Literal['thumbnail'] = Field('thumbnail', description='The type of generative job to create. Currently the only published value is `thumbnail`.', title='Job type')
    sourceUri: str = Field(..., description='URL of the source video to extract thumbnails from.', title='Source uri', min_length=1, examples=['https://youtube.com/watch?v=...'])
    referenceImageUri: str | None = Field(None, description="Optional reference image URL. The thumbnail composition draws stylistic cues from this image. Upload via `POST /api/upload-links` with `usecase: 'FreeToolMedia'`, then pass the returned `cdnUrl` here.", title='Reference image uri', min_length=1, examples=['https://cdn.opus.pro/uploads/.../ref.png'])
    maskImageUri: str | None = Field(None, description='Optional mask image URL for inpainting.', title='Mask image uri', min_length=1, examples=['https://cdn.opus.pro/uploads/.../mask.png'])
    prompt: str | None = Field(None, description='Optional text prompt steering the thumbnail composition.', title='Prompt', min_length=1, examples=['punchy red overlay, bold sans-serif title'])


class OpusClipGetGenerativeJobConfig(_Input):
    """Get generative job."""
    operation: Literal['get_generative_job'] = Field('get_generative_job', json_schema_extra={"ui:hidden": True})
    jobId: str = Field(..., description='The jobId returned by `POST /api/generative-jobs`.', title='Job id', min_length=1)


class OpusClipGetTranscriptConfig(_Input):
    """Get transcript."""
    operation: Literal['get_transcript'] = Field('get_transcript', json_schema_extra={"ui:hidden": True})
    q: Literal['findByProjectId'] = Field('findByProjectId', description='Query variant. Public callers must pass `findByProjectId`.', title='Q')
    projectId: str = Field(..., description='Project ID.', title='Project id', min_length=1, examples=['P2120900kDmP'])


OpusClipConfig = Annotated[Union[
    OpusClipListBrandTemplatesConfig,
    OpusClipCreateClipProjectConfig,
    OpusClipGetClipProjectConfig,
    OpusClipUpdateProjectVisibilityConfig,
    OpusClipListExportableClipsConfig,
    OpusClipRemoveCollectionContentConfig,
    OpusClipAddCollectionContentConfig,
    OpusClipDeleteCollectionConfig,
    OpusClipCreateCollectionConfig,
    OpusClipListCollectionsConfig,
    OpusClipExportCollectionConfig,
    OpusClipCreateCensorJobConfig,
    OpusClipGetCensorJobConfig,
    OpusClipListSocialAccountsConfig,
    OpusClipCreateSocialCopyJobConfig,
    OpusClipGetSocialCopyJobConfig,
    OpusClipPublishPostConfig,
    OpusClipSchedulePostConfig,
    OpusClipCancelScheduledPostConfig,
    OpusClipCreateThumbnailJobConfig,
    OpusClipGetGenerativeJobConfig,
    OpusClipGetTranscriptConfig
], Field(discriminator="operation")]


class OpusClipFullConfig(NodeConfig[OpusClipConfig, OpusClipAPIKeyCredential]):
    pass


# (HTTP method, path, path fields, query fields, header fields, body fields, has body)
OPERATIONS = {'list_brand_templates': ('GET', '/api/brand-templates', {}, {'q': 'q'}, {}, [], False),
 'create_clip_project': ('POST',
                         '/api/clip-projects',
                         {},
                         {},
                         {},
                         ['videoUrl', 'conclusionActions', 'curationPref', 'importPref', 'brandTemplateId'],
                         True),
 'get_clip_project': ('GET', '/api/clip-projects/{projectId}', {'projectId': 'projectId'}, {}, {}, [], False),
 'update_project_visibility': ('POST',
                               '/api/clip-projects/{projectId}/update-visibility',
                               {'projectId': 'projectId'},
                               {},
                               {},
                               ['visibility'],
                               True),
 'list_exportable_clips': ('GET',
                           '/api/exportable-clips',
                           {},
                           {'q': 'q',
                            'projectId': 'projectId',
                            'collectionId': 'collectionId',
                            'pageNum': 'pageNum',
                            'pageSize': 'pageSize'},
                           {'organization_id': 'x-opus-org-id'},
                           [],
                           False),
 'remove_collection_content': ('POST',
                               '/api/collection-contents/delete-collection-contents',
                               {},
                               {},
                               {},
                               ['q', 'collectionId', 'contentId'],
                               True),
 'add_collection_content': ('POST',
                            '/api/collection-contents',
                            {},
                            {},
                            {},
                            ['collectionId', 'contentId'],
                            True),
 'delete_collection': ('DELETE',
                       '/api/collections/{collectionId}',
                       {'collectionId': 'collectionId'},
                       {},
                       {},
                       [],
                       False),
 'create_collection': ('POST', '/api/collections', {}, {}, {}, ['collectionName'], True),
 'list_collections': ('GET', '/api/collections', {}, {'q': 'q', 'contentId': 'contentId'}, {}, [], False),
 'export_collection': ('POST',
                       '/api/collections/{collectionId}/export',
                       {'collectionId': 'collectionId'},
                       {},
                       {},
                       [],
                       True),
 'create_censor_job': ('POST', '/api/censor-jobs', {}, {}, {}, ['projectId', 'clipId', 'options'], True),
 'get_censor_job': ('GET', '/api/censor-jobs/{jobId}', {'jobId': 'jobId'}, {}, {}, [], False),
 'list_social_accounts': ('GET', '/api/social-accounts', {}, {'q': 'q'}, {}, [], False),
 'create_social_copy_job': ('POST',
                            '/api/social-copy-jobs',
                            {},
                            {},
                            {},
                            ['projectId',
                             'clipId',
                             'postAccountId',
                             'subAccountId',
                             'prompt',
                             'forceRegenerate'],
                            True),
 'get_social_copy_job': ('GET', '/api/social-copy-jobs/{jobId}', {'jobId': 'jobId'}, {}, {}, [], False),
 'publish_post': ('POST',
                  '/api/post-tasks',
                  {},
                  {},
                  {},
                  ['projectId', 'clipId', 'postAccountId', 'subAccountId', 'postDetail'],
                  True),
 'schedule_post': ('POST',
                   '/api/publish-schedules',
                   {},
                   {},
                   {},
                   ['projectId', 'clipId', 'postAccountId', 'subAccountId', 'publishAt', 'postDetail'],
                   True),
 'cancel_scheduled_post': ('DELETE',
                           '/api/publish-schedules/{scheduleId}',
                           {'scheduleId': 'scheduleId'},
                           {},
                           {},
                           [],
                           False),
 'create_thumbnail_job': ('POST',
                          '/api/generative-jobs',
                          {},
                          {},
                          {},
                          ['jobType', 'sourceUri', 'referenceImageUri', 'maskImageUri', 'prompt'],
                          True),
 'get_generative_job': ('GET', '/api/generative-jobs/{jobId}', {'jobId': 'jobId'}, {}, {}, [], False),
 'get_transcript': ('GET', '/api/transcripts', {}, {'q': 'q', 'projectId': 'projectId'}, {}, [], False)}


class OpusClipNode(WorkflowNode):
    integration_type = "automation-opusclip"
    connection_evidence = ConnectionEvidence(
        noun="connected social accounts", operation="list_social_accounts",
        label_keys=("extUserName", "postAccountId"),
    )

    @classmethod
    def get_config_model(cls):
        return OpusClipFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect an OpusClip API key")
        method, path, path_fields, query_fields, header_fields, body_fields, has_body = OPERATIONS[config.operation]
        data = config.model_dump(mode="json", exclude_none=True)
        for field, wire in path_fields.items():
            value = data[field]
            if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Use a valid OpusClip resource ID")
            path = path.replace("{" + wire + "}", quote(value, safe=""))
        params = {wire: data[field] for field, wire in query_fields.items() if field in data}
        headers = {"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}
        headers.update({wire: data[field] for field, wire in header_fields.items() if field in data})
        body = {field: data[field] for field in body_fields if field in data}
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params,
                                            **({"json": body} if has_body else {}))
        if not 200 <= response.status_code < 300:
            message = response.text.replace(credential.api_key, "[redacted]")[:2000]
            raise ValueError(f"OpusClip HTTP {response.status_code}: {message}")
        payload = response.json()
        expected = list if config.operation in {"list_brand_templates", "list_exportable_clips"} else dict
        if not isinstance(payload, expected):
            raise ValueError("OpusClip returned an unexpected response shape")
        if isinstance(payload, dict) and (payload.get("errorName") or payload.get("errors")):
            message = json.dumps(payload).replace(credential.api_key, "[redacted]")[:2000]
            raise ValueError("OpusClip rejected the request: " + message)
        if config.operation == "list_social_accounts":
            accounts = payload.get("data")
            if not isinstance(accounts, list) or any(
                not isinstance(row, dict) or not all(isinstance(row.get(key), str) for key in
                    ("postAccountId", "platform", "extUserId", "extUserName"))
                for row in accounts
            ):
                raise ValueError("OpusClip returned an invalid social-account list")
        # Preserve job states, pagination metadata and export URLs as published.
        return {"data": payload.get("data", payload) if isinstance(payload, dict) else payload}
