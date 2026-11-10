"""YouTubeTranscript.dev V2 operations, pinned to the provider's 2.1.0 contract.

Each operation makes one request. Async results and pagination are returned
unchanged so workflows can poll jobs or request the next page explicitly.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://www.youtubetranscript.dev/api/v2"


class YoutubeTranscriptAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="YouTube Transcript API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.youtubetranscript.dev/dashboard",
            "x-credential-instructions": "Copy an API key from your YouTubeTranscript.dev dashboard and paste it here. NoClick sends it as a Bearer token to www.youtubetranscript.dev. Transcription, translation and theme unlocking can use credits.",
        },
    )
    credential_type: Literal["youtube_transcript_api_key"] = Field(
        "youtube_transcript_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class YoutubeTranscriptInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class FormatOptions(YoutubeTranscriptInput):
    timestamp: bool | None = Field(None, description='Include timestamped segments')
    paragraphs: bool | None = Field(None, description='Include paragraph groupings')
    words: bool | None = Field(None, description='Include word-level timestamps')


class AsrOptions(YoutubeTranscriptInput):
    language: str | None = Field(None, description='Source audio language as an ISO code (any of the 99 supported languages')
    codeSwitching: bool | None = Field(None, description='Transcribe mid-sentence language switches. Only applies when language="auto"')
    medicalMode: bool | None = Field(None, description='Boost accuracy for medical terminology (EN/ES/DE/FR only)')
    keyTerms: list[str] | None = Field(None, max_length=200, description='Words/phrases (max 6 words each) to boost recognition accuracy, e.g. product names or jargon. Beta - English audio only (ignored for other languages)')
    translateTo: str | None = Field(None, description='Translate transcript to this language')
    speakerLabels: bool | None = Field(None, description='Speaker diarization (billable). Mutually exclusive with multichannel - multichannel wins when both are set')
    speakerId: bool | None = Field(None, description='Map speaker labels to real names/roles (billable')
    speakerIdType: Literal['name', 'role'] | None = Field(None, description='Identify speakers by name or by role')
    speakerIdKnownValues: list[Annotated[str, Field(max_length=35)]] | None = Field(None, max_length=20, description='Known speaker names or roles to match against. Optional for "name" (inferred from conversation); REQUIRED for "role" - role-type speaker ID is skipped without at least one value')
    multichannel: bool | None = Field(None, description='Per-channel transcription (billable). Mutually exclusive with speakerLabels and speakerId - setting it disables both')
    speakersExpected: int | None = Field(None, ge=1, le=20, description='Exact speaker count. Null to auto-detect or use the min/max range')
    speakersExpectedMin: int | None = Field(None, ge=1, le=20, description='Hard lower bound on speaker labels (ignored when speakersExpected is set)')
    speakersExpectedMax: int | None = Field(None, ge=1, le=20, description='Hard upper bound on speaker labels (ignored when speakersExpected is set)')
    topicDetection: bool | None = Field(None, description='IAB topic categories (billable)')
    summarization: bool | None = Field(None, description='Auto summary (billable)')
    contentModeration: bool | None = Field(None, description='Content safety detection (billable)')
    piiRedaction: bool | None = Field(None, description='Redact personally identifiable information (billable)')
    profanityFiltering: bool | None = Field(None, description='Filter profanity (billable)')
    sentimentAnalysis: bool | None = Field(None, description='Per-segment sentiment (billable)')
    autoPunctuation: bool | None = Field(None, description='Automatic punctuation')
    textFormatting: bool | None = Field(None, description='Text formatting')
    fillerWords: bool | None = Field(None, description='Keep filler words (disfluencies)')
    customFormatting: bool | None = Field(None, description='Reformat dates/phones/emails using the patterns below (billable)')
    customFormatDate: Literal['mm/dd/yyyy', 'dd/mm/yyyy', 'yyyy-mm-dd', 'mm-dd-yyyy', 'dd.mm.yyyy'] | None = Field(None, description='Date pattern applied when customFormatting is on')
    customFormatPhone: Literal['(xxx)xxx-xxxx', 'xxx-xxx-xxxx', 'xxx.xxx.xxxx', '+x(xxx)xxx-xxxx'] | None = Field(None, description='Phone pattern applied when customFormatting is on')
    customFormatEmail: Literal['username@domain.com', 'firstname.lastname@domain.com'] | None = Field(None, description='Email pattern applied when customFormatting is on')


class TranscribeVideoConfig(YoutubeTranscriptInput):
    """Transcribe a single YouTube video."""
    operation: Literal['transcribe_video'] = Field('transcribe_video', json_schema_extra={"ui:hidden": True})
    video: str = Field(..., min_length=1, description='YouTube URL or 11-char ID. Required unless upload_id is set.')
    language: str | None = Field(None, description='Preferred transcript language (e.g. en, es). If unavailable, captions in another language may be returned; transcript.language reports the actual language.')
    mode: Literal['auto', 'captions_only', 'human_captions_only', 'speech_to_text_only'] = Field('captions_only', description='Where the transcript comes from. Replaces the legacy source + allow_asr\npair (still supported, but not in the same request as mode). Note that\nmode=auto is not legacy source=auto: source=auto alone never uses ASR\n(that is mode=captions_only).\n  - auto: captions first; speech-to-text (ASR) only when the video has none. Can charge ASR credits.\n  - captions_only: any captions (human or YouTube auto-generated), never ASR. When mode is omitted, the account default from the API Dashboard applies (auto for accounts created from October 2026, captions_only for older ones unless changed).\n  - human_captions_only: human-made captions only, never ASR.\n  - speech_to_text_only: always transcribe the audio with ASR. Charges ASR credits.\nOn /transcribe, ASR modes return status processing with a job_id to poll\nat GET /jobs/{job_id} when no webhook_url is given. Responses echo the\nmode the request ran with (for legacy requests, the equivalent mode).\n')
    format: FormatOptions | None = Field(None, description='Which extras to include in the transcript payload.')
    webhook_url: str | None = Field(None, description='Where ASR results are POSTed. Required for legacy ASR (source="asr" or upload_id) unless run from the dashboard. Optional with mode=auto or speech_to_text_only: poll GET /jobs/{job_id} instead. Ignored by captions_only and human_captions_only.')
    asr_options: AsrOptions | None = Field(None, description='Rich ASR configuration. Only applies when the\nvideo is transcribed via ASR (mode speech_to_text_only or auto fallback; legacy source="asr" or allow_asr). Billable\nadd-ons increase credit cost proportional to duration - use\n/transcribe/estimate to preview.\n')


class EstimateTranscriptionConfig(YoutubeTranscriptInput):
    """Estimate credit cost (dry run)."""
    operation: Literal['estimate_transcription'] = Field('estimate_transcription', json_schema_extra={"ui:hidden": True})
    video: str = Field(..., min_length=1)
    mode: Literal['auto', 'captions_only', 'human_captions_only', 'speech_to_text_only'] | None = Field(None, description='Where the transcript comes from. Replaces the legacy source + allow_asr\npair (still supported, but not in the same request as mode). Note that\nmode=auto is not legacy source=auto: source=auto alone never uses ASR\n(that is mode=captions_only).\n  - auto: captions first; speech-to-text (ASR) only when the video has none. Can charge ASR credits.\n  - captions_only: any captions (human or YouTube auto-generated), never ASR. When mode is omitted, the account default from the API Dashboard applies (auto for accounts created from October 2026, captions_only for older ones unless changed).\n  - human_captions_only: human-made captions only, never ASR.\n  - speech_to_text_only: always transcribe the audio with ASR. Charges ASR credits.\nOn /transcribe, ASR modes return status processing with a job_id to poll\nat GET /jobs/{job_id} when no webhook_url is given. Responses echo the\nmode the request ran with (for legacy requests, the equivalent mode).\n')
    asr_options: AsrOptions | None = Field(None, description='Rich ASR configuration. Only applies when the\nvideo is transcribed via ASR (mode speech_to_text_only or auto fallback; legacy source="asr" or allow_asr). Billable\nadd-ons increase credit cost proportional to duration - use\n/transcribe/estimate to preview.\n')


class CreateBatchConfig(YoutubeTranscriptInput):
    """Transcribe multiple videos."""
    operation: Literal['create_batch'] = Field('create_batch', json_schema_extra={"ui:hidden": True})
    video_ids: list[str] = Field(..., max_length=3000)
    language: str | None = Field(None, description='Preferred language for every video')
    mode: Literal['auto', 'captions_only', 'human_captions_only', 'speech_to_text_only'] = Field('captions_only', description='Where the transcript comes from. Replaces the legacy source + allow_asr\npair (still supported, but not in the same request as mode). Note that\nmode=auto is not legacy source=auto: source=auto alone never uses ASR\n(that is mode=captions_only).\n  - auto: captions first; speech-to-text (ASR) only when the video has none. Can charge ASR credits.\n  - captions_only: any captions (human or YouTube auto-generated), never ASR. When mode is omitted, the account default from the API Dashboard applies (auto for accounts created from October 2026, captions_only for older ones unless changed).\n  - human_captions_only: human-made captions only, never ASR.\n  - speech_to_text_only: always transcribe the audio with ASR. Charges ASR credits.\nOn /transcribe, ASR modes return status processing with a job_id to poll\nat GET /jobs/{job_id} when no webhook_url is given. Responses echo the\nmode the request ran with (for legacy requests, the equivalent mode).\n')
    format: FormatOptions | None = Field(None, description='Which extras to include in the transcript payload.')
    webhook_url: str | None = Field(None, description='Required when mode is auto or speech_to_text_only (legacy - source="asr" or allow_asr=true)')
    asr_options: AsrOptions | None = Field(None, description='Rich ASR configuration. Only applies when the\nvideo is transcribed via ASR (mode speech_to_text_only or auto fallback; legacy source="asr" or allow_asr). Billable\nadd-ons increase credit cost proportional to duration - use\n/transcribe/estimate to preview.\n')

    @model_validator(mode="after")
    def webhook_for_asr(self):
        if self.mode in {"auto", "speech_to_text_only"} and not self.webhook_url:
            raise ValueError("Batch ASR modes require webhook_url; use captions_only without a webhook")
        if not self.video_ids:
            raise ValueError("Provide at least one video ID")
        return self


class GetBatchConfig(YoutubeTranscriptInput):
    """Poll a V2 batch job."""
    operation: Literal['get_batch'] = Field('get_batch', json_schema_extra={"ui:hidden": True})
    batch_id: UUID = Field(...)


class ListJobsConfig(YoutubeTranscriptInput):
    """List transcription jobs."""
    operation: Literal['list_jobs'] = Field('list_jobs', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, ge=1)
    limit: int | None = Field(None, ge=1, le=100)
    status: Literal['completed', 'processing', 'failed', 'requires_asr_confirmation'] | None = Field(None)


class GetJobConfig(YoutubeTranscriptInput):
    """Poll a V2 transcription job."""
    operation: Literal['get_job'] = Field('get_job', json_schema_extra={"ui:hidden": True})
    job_id: UUID = Field(...)
    include_segments: bool | None = Field(None)
    include_paragraphs: bool | None = Field(None)
    include_words: bool | None = Field(None)


class ListTranscriptsConfig(YoutubeTranscriptInput):
    """List stored transcripts."""
    operation: Literal['list_transcripts'] = Field('list_transcripts', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, ge=1)
    limit: int | None = Field(None, ge=1, le=100)
    search: str | None = Field(None)
    status: str | None = Field(None)
    language: str | None = Field(None)
    date_from: datetime | None = Field(None)
    date_to: datetime | None = Field(None)
    include_segments: bool | None = Field(None)


class GetTranscriptConfig(YoutubeTranscriptInput):
    """Fetch a stored transcript."""
    operation: Literal['get_transcript'] = Field('get_transcript', json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1)
    id: UUID | None = Field(None)
    language: str | None = Field(None)
    source: Literal['auto', 'manual', 'asr'] | None = Field(None)
    include_timestamps: bool | None = Field(None)


class DeleteTranscriptConfig(YoutubeTranscriptInput):
    """Delete a stored transcript."""
    operation: Literal['delete_transcript'] = Field('delete_transcript', json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1)
    language: str | None = Field(None)
    source: Literal['auto', 'manual', 'asr'] | None = Field(None)


class ListTranscriptLanguagesConfig(YoutubeTranscriptInput):
    """List available languages for a video."""
    operation: Literal['list_transcript_languages'] = Field('list_transcript_languages', json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1)
    include_youtube_default: bool | None = Field(None)


class GetTranscriptThemesConfig(YoutubeTranscriptInput):
    """Read unlocked key moments, themes & keywords (free)."""
    operation: Literal['get_transcript_themes'] = Field('get_transcript_themes', json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1)
    id: str | None = Field(None)
    language: str | None = Field(None)
    source: Literal['auto', 'manual', 'asr'] | None = Field(None)


class UnlockTranscriptThemesConfig(YoutubeTranscriptInput):
    """Unlock key moments, themes & keywords (1 credit, once per transcript)."""
    operation: Literal['unlock_transcript_themes'] = Field('unlock_transcript_themes', json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1)
    id: str | None = Field(None)
    language: str | None = Field(None)
    source: Literal['auto', 'manual', 'asr'] | None = Field(None)


class TranslateTranscriptConfig(YoutubeTranscriptInput):
    """Translate a stored transcript."""
    operation: Literal['translate_transcript'] = Field('translate_transcript', json_schema_extra={"ui:hidden": True})
    video_id: str = Field(..., min_length=1)
    target_language: str = Field(..., min_length=1)
    source_language: str | None = Field(None)
    provider: Literal['ai', 'youtube'] | None = Field(None)
    allow_ai_fallback: bool | None = Field(None)


class BulkDeleteTranscriptsConfig(YoutubeTranscriptInput):
    """Delete transcripts by id."""
    operation: Literal['bulk_delete_transcripts'] = Field('bulk_delete_transcripts', json_schema_extra={"ui:hidden": True})
    ids: list[UUID] = Field(...)


class GetCreditsConfig(YoutubeTranscriptInput):
    """Get credit balance and plan."""
    operation: Literal['get_credits'] = Field('get_credits', json_schema_extra={"ui:hidden": True})


class ListFoldersConfig(YoutubeTranscriptInput):
    """List your folders with video counts (free)."""
    operation: Literal['list_folders'] = Field('list_folders', json_schema_extra={"ui:hidden": True})


class CreateFolderConfig(YoutubeTranscriptInput):
    """Create a folder (free)."""
    operation: Literal['create_folder'] = Field('create_folder', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=80)


class GetFolderConfig(YoutubeTranscriptInput):
    """Get one folder (free)."""
    operation: Literal['get_folder'] = Field('get_folder', json_schema_extra={"ui:hidden": True})
    folder_id: UUID = Field(...)


class RenameFolderConfig(YoutubeTranscriptInput):
    """Rename a folder (free)."""
    operation: Literal['rename_folder'] = Field('rename_folder', json_schema_extra={"ui:hidden": True})
    folder_id: UUID = Field(...)
    name: str = Field(..., min_length=1, max_length=80)


class DeleteFolderConfig(YoutubeTranscriptInput):
    """Delete a folder; its videos and transcripts stay (free)."""
    operation: Literal['delete_folder'] = Field('delete_folder', json_schema_extra={"ui:hidden": True})
    folder_id: UUID = Field(...)


class ListFolderVideosConfig(YoutubeTranscriptInput):
    """List a folder's videos (same shape as GET /videos) (free)."""
    operation: Literal['list_folder_videos'] = Field('list_folder_videos', json_schema_extra={"ui:hidden": True})
    folder_id: UUID = Field(...)
    search: str | None = Field(None)
    page: int | None = Field(None, ge=1)
    limit: int | None = Field(None, ge=1, le=100)


class AddFolderVideosConfig(YoutubeTranscriptInput):
    """Add videos to a folder (free)."""
    operation: Literal['add_folder_videos'] = Field('add_folder_videos', json_schema_extra={"ui:hidden": True})
    folder_id: UUID = Field(...)
    video_ids: list[str] = Field(..., max_length=100)


class RemoveFolderVideosConfig(YoutubeTranscriptInput):
    """Remove videos from a folder; transcripts are kept (free)."""
    operation: Literal['remove_folder_videos'] = Field('remove_folder_videos', json_schema_extra={"ui:hidden": True})
    folder_id: UUID = Field(...)
    video_ids: list[str] = Field(..., max_length=100)


class ListVideosConfig(YoutubeTranscriptInput):
    """List your videos with their folders and existing outputs (free)."""
    operation: Literal['list_videos'] = Field('list_videos', json_schema_extra={"ui:hidden": True})
    folder_id: UUID | None = Field(None)
    unfiled: bool | None = Field(None)
    channel: str | None = Field(None)
    sort: Literal['recent', 'oldest', 'longest', 'shortest', 'title'] | None = Field(None)
    search: str | None = Field(None)
    page: int | None = Field(None, ge=1)
    limit: int | None = Field(None, ge=1, le=100)


class ResolvePlaylistConfig(YoutubeTranscriptInput):
    """Resolve playlist videos."""
    operation: Literal['resolve_playlist'] = Field('resolve_playlist', json_schema_extra={"ui:hidden": True})
    playlist_id: str = Field(..., min_length=1, description="YouTube playlist ID to resolve")
    limit: int | None = Field(None, ge=1, le=100)


class OnNewTranscriptConfig(PollTriggerConfigBase):
    """Watch successfully stored transcripts, with an initial silent baseline.

    Evidence: GET /transcripts and TranscriptListResponse in the provider's
    https://www.youtubetranscript.dev/api/v2/openapi.json (2.1.0).
    """
    operation: Literal["on_new_transcript"] = Field(
        "on_new_transcript", title="On New Transcript", json_schema_extra={
            "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
            "x-display-name": "On New Transcript",
        })
    language: str | None = Field(None, title="Language", description="Only watch transcripts in this language (for example en).")
    search: str | None = Field(None, title="Search", description="Filter the stored transcript history.")
    date_from: datetime | None = Field(None, title="Created after", description="Only watch transcripts created after this date and time.")


YoutubeTranscriptConfig = Annotated[Union[TranscribeVideoConfig, EstimateTranscriptionConfig, CreateBatchConfig, GetBatchConfig, ListJobsConfig, GetJobConfig, ListTranscriptsConfig, GetTranscriptConfig, DeleteTranscriptConfig, ListTranscriptLanguagesConfig, GetTranscriptThemesConfig, UnlockTranscriptThemesConfig, TranslateTranscriptConfig, BulkDeleteTranscriptsConfig, GetCreditsConfig, ListFoldersConfig, CreateFolderConfig, GetFolderConfig, RenameFolderConfig, DeleteFolderConfig, ListFolderVideosConfig, AddFolderVideosConfig, RemoveFolderVideosConfig, ListVideosConfig, ResolvePlaylistConfig, OnNewTranscriptConfig], Field(discriminator="operation")]


class YoutubeTranscriptFullConfig(NodeConfig[YoutubeTranscriptConfig, YoutubeTranscriptAPIKeyCredential]):
    pass


ROUTES = {'transcribe_video': ('POST', '/transcribe'),
 'estimate_transcription': ('POST', '/transcribe/estimate'),
 'create_batch': ('POST', '/batch'),
 'get_batch': ('GET', '/batch/{batch_id}'),
 'list_jobs': ('GET', '/jobs'),
 'get_job': ('GET', '/jobs/{job_id}'),
 'list_transcripts': ('GET', '/transcripts'),
 'get_transcript': ('GET', '/transcripts/{video_id}'),
 'delete_transcript': ('DELETE', '/transcripts/{video_id}'),
 'list_transcript_languages': ('GET', '/transcripts/{video_id}/languages'),
 'get_transcript_themes': ('GET', '/transcripts/{video_id}/themes'),
 'unlock_transcript_themes': ('POST', '/transcripts/{video_id}/themes'),
 'translate_transcript': ('POST', '/transcripts/{video_id}/translate'),
 'bulk_delete_transcripts': ('POST', '/transcripts/bulk-delete'),
 'get_credits': ('GET', '/credits'),
 'list_folders': ('GET', '/folders'),
 'create_folder': ('POST', '/folders'),
 'get_folder': ('GET', '/folders/{folder_id}'),
 'rename_folder': ('PATCH', '/folders/{folder_id}'),
 'delete_folder': ('DELETE', '/folders/{folder_id}'),
 'list_folder_videos': ('GET', '/folders/{folder_id}/videos'),
 'add_folder_videos': ('POST', '/folders/{folder_id}/videos'),
 'remove_folder_videos': ('DELETE', '/folders/{folder_id}/videos'),
 'list_videos': ('GET', '/videos'),
 'resolve_playlist': ('POST', '/playlists/resolve')}

BODY_FIELDS = {'transcribe_video': ['video', 'language', 'mode', 'format', 'webhook_url', 'asr_options'],
 'estimate_transcription': ['video', 'mode', 'asr_options'],
 'create_batch': ['video_ids', 'language', 'mode', 'format', 'webhook_url', 'asr_options'],
 'translate_transcript': ['target_language', 'source_language', 'provider', 'allow_ai_fallback'],
 'bulk_delete_transcripts': ['ids'],
 'create_folder': ['name'],
 'rename_folder': ['name'],
 'add_folder_videos': ['video_ids'],
 'remove_folder_videos': ['video_ids'],
 'resolve_playlist': ['playlist_id', 'limit']}


class YoutubeTranscriptNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-youtube-transcript"
    connection_evidence = ConnectionEvidence(
        noun="stored transcripts", operation="list_transcripts",
        label_keys=("video_title", "video_id", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return YoutubeTranscriptFullConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_transcript":
            return bool(output.get("new_transcript_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        transcripts = output.get("transcripts") if isinstance(output, dict) else None
        if not isinstance(transcripts, list):
            return super().resolve_agent_event(output)
        if not transcripts:
            return None
        lines = []
        for item in transcripts[:10]:
            lines.append(
                f"- {item.get('video_title') or 'Untitled video'} "
                f"(transcript {item.get('id')}, video {item.get('video_id')}, "
                f"language {item.get('language')}, created {item.get('created_at')})")
        if len(transcripts) > 10:
            lines.append(f"- … and {len(transcripts) - 10} more")
        return {"text": f"YouTube Transcript: {len(transcripts)} new transcript(s) are ready. "
                "Use the video and transcript ids to fetch the full transcript.\n" + "\n".join(lines),
                "conversation_key": None}

    async def _poll_new_transcripts(self, config):
        transcripts = []
        for page in range(1, 21):
            result = await self._execute_operation(ListTranscriptsConfig(
                page=page, limit=100, status="succeeded", language=config.language,
                search=config.search, date_from=config.date_from))
            if result["status"] != "success":
                raise ValueError("Could not poll YouTube Transcript history: " + str(result.get("error")))
            data = result["data"]
            history = data["history"]
            if any(not isinstance(item, dict) or not item.get("id") for item in history):
                raise ValueError("YouTube Transcript history contains an invalid transcript")
            transcripts.extend(history)
            pagination = data.get("pagination")
            if not isinstance(pagination, dict) or not isinstance(pagination.get("hasMore"), bool):
                raise ValueError("YouTube Transcript history is missing pagination.hasMore")
            if not pagination["hasMore"]:
                break
        else:
            raise ValueError("More than 2,000 transcripts match; narrow the language, search or created-after filter")
        fresh = await self._filter_unseen(transcripts, lambda item: str(item["id"]))
        return {"status": "success", "transcripts": fresh, "new_transcript_count": len(fresh)}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a YouTube Transcript API key")
        config = self.config.config
        if isinstance(config, OnNewTranscriptConfig):
            output = await self._poll_new_transcripts(config)
        else:
            output = await self._execute_operation(config)
        await self.emit(output)
        return output

    async def _execute_operation(self, op):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a YouTube Transcript API key")
        key = self.config.credentials.api_key
        method, path = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for name in tuple(values):
            placeholder = "{" + name + "}"
            if placeholder in path:
                path = path.replace(placeholder, quote(str(values.pop(name)), safe=""))
        body_names = BODY_FIELDS.get(op.operation, ())
        body = {name: values.pop(name) for name in body_names if name in values}
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(
                method, BASE_URL + path,
                headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                params=values, **({"json": body} if body_names else {}),
            )
        if len(response.content) > 20_000_000:
            raise ValueError("YouTube Transcript response exceeds the content limit")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("YouTube Transcript returned a non-JSON response") from None

        def redact(value):
            if isinstance(value, str):
                return value.replace(key, "[redacted]")
            if isinstance(value, list):
                for index, item in enumerate(value):
                    value[index] = redact(item)
            if isinstance(value, dict):
                for name, item in list(value.items()):
                    safe_name = name.replace(key, "[redacted]")
                    value[safe_name] = redact(item)
                    if safe_name != name:
                        del value[name]
            return value

        data = redact(data)
        if not isinstance(data, dict):
            raise ValueError("YouTube Transcript returned an unexpected JSON envelope")
        failed = response.status_code not in {200, 201, 202}
        if not failed and op.operation != "list_transcripts":
            failed = bool(data.get("error")) or data.get("status") == "failed"
        if not failed and op.operation == "list_transcripts":
            if not isinstance(data.get("history"), list):
                raise ValueError("YouTube Transcript response is missing transcript history")
        output = {"status": "error" if failed else "success", "http_status": response.status_code, "data": data}
        if failed:
            output["error"] = data
        # Keep the documented envelope intact; this alias lets connection evidence
        # display the account's video titles through the shared list collector.
        if not failed and op.operation == "list_transcripts":
            output["items"] = data["history"]
        return output
