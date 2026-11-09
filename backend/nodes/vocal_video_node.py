"""Vocal Video API v2 workspace tools.

Contract: https://vocalvideo.com/docs/openapi, version 2.0.0.
Each operation makes one POST to its documented tool. Lists are ranked
shortlists, not paginated workspace totals. Responses retain provider flags,
including truncated writes, invitation previews and pending indexing.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://vocalvideo.com/api/v2/tools/"


class VocalVideoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Vocal Video API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://vocalvideo.com/app/api_keys",
            "x-credential-instructions": "Create a workspace API key in Vocal Video Settings → API keys. API access must be enabled for the account. Read scope supports get/list tools; write scope is required for mutations. Paste only the key, without Bearer.",
        },
    )
    credential_type: Literal["vocal_video_api_key"] = Field("vocal_video_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class VocalVideoGetAccountUsageConfig(_Input):
    """Read workspace totals, usage meters and allowances. The publish, video-request and AI-credit meters are separate."""
    operation: Literal['get_account_usage'] = Field('get_account_usage', json_schema_extra={"ui:hidden": True})

class VocalVideoListCollectorsConfig(_Input):
    """Find workspace video collectors. Results are a ranked shortlist; when truncated, narrow the filters rather than treating matched as a workspace total."""
    operation: Literal['list_collectors'] = Field('list_collectors', json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description='Full-text search across nickname and title.')
    status: Literal['active', 'inactive'] | None = Field(None, description='`active` covers collectors currently accepting responses (including freshly-initialized ones); `inactive` covers paused collectors. Omit for both. Archived collectors are never returned.')
    starred: StrictBool | None = Field(None, description='If true, return only starred collectors.')
    since_days: StrictInt | None = Field(None, description='Restrict to collectors created in the last N days.')
    sort: Literal['newest', 'oldest', 'abc', 'most_replies'] | None = Field(None, description='`newest` (default) by creation recency, `oldest` reverses it, `abc` orders alphabetically by nickname, `most_replies` by response count descending.')
    limit: StrictInt = Field(20, description='Max results to return.', le=50)

class VocalVideoGetCollectorConfig(_Input):
    """Read a collector, its ordered prompts, copy and settings."""
    operation: Literal['get_collector'] = Field('get_collector', json_schema_extra={"ui:hidden": True})
    id: StrictInt = Field(..., description='Collector id from list_collectors.')

class VocalVideoCreateCollectorConfig(_Input):
    """Create a video request campaign, optionally with AI-generated prompts. New collectors are active immediately; AI generation spends credits."""
    operation: Literal['create_collector'] = Field('create_collector', json_schema_extra={"ui:hidden": True})
    ai_prompt: str | None = Field(None, description='Plain-language description of what you want to collect. The generator seeds prompts + copy from this.')
    intended_usage: Literal['testimonials', 'employee', 'hiring', 'communication', 'learning', 'other'] | None = Field(None, description="Picks which generator template to use. Defaults to the account's primary signup usage.")
    nickname: str | None = Field(None, description='Workspace-only label for the collector.', max_length=191)
    title: str | None = Field(None, description='Public-facing title shown to respondents.', max_length=191)

class VocalVideoUpdateCollectorConfig(_Input):
    """Change selected collector copy and settings. Only supplied fields are sent; explicit null clears release, reward or template overrides."""
    operation: Literal['update_collector'] = Field('update_collector', json_schema_extra={"ui:hidden": True})
    collector_id: StrictInt = Field(...)
    intended_usage: Literal['testimonials', 'employee', 'hiring', 'communication', 'learning', 'other'] | None = Field(None, description="Re-point the collector's purpose (testimonials / employee / hiring / communication / learning / other).")
    nickname: str | None = Field(None, max_length=191)
    title: str | None = Field(None, max_length=191)
    video_label: str | None = Field(None, description='What kind of video its responses become, for viewers ("Customer Story", "Therapist Profile"): the line over the name on each video\'s title card and thumbnail. Never an ask, a name or a date; empty for job applications.', max_length=60)
    intro: str | None = Field(None, description='Public-facing welcome blurb shown to respondents.')
    finish_headline: str | None = Field(None, description='Thank-you screen headline shown after recording.', max_length=191)
    finish_body: str | None = Field(None, description='Thank-you screen body shown after recording.')
    contact_name: str | None = Field(None, description='Workspace contact name (the person fronting the request).', max_length=191)
    contact_title: str | None = Field(None, description='Workspace contact title.', max_length=191)
    sender_name: str | None = Field(None, description='Display name used as the From-name on invitation emails.', max_length=191)
    invitation_subject: str | None = Field(None, description='Subject line of the invitation email.', max_length=191)
    accept_audio: StrictBool | None = Field(None, description='Let a respondent answer with audio only, instead of video.')
    ask_company_name: StrictBool | None = Field(None, description='Ask the respondent for their company name on the attribution step.')
    ask_job_title: StrictBool | None = Field(None, description='Ask the respondent for their job title on the attribution step.')
    contact_email: str | None = Field(None, description='Reply-to address for the invitation and reminder emails.', max_length=191)
    enable_effects: StrictBool | None = Field(None, description='Offer background blur to respondents while they record.')
    force_landscape_video: StrictBool | None = Field(None, description='Make phone respondents record horizontally.')
    prize_drawing: StrictBool | None = Field(None, description='Enter respondents in the Vocal Video prize drawing.')
    release_id: StrictInt | None = Field(None, description="A custom release from this workspace for respondents to agree to; null uses the workspace default. Only reaches respondents while include_custom_release is on, and a wrong id comes back with the workspace's releases listed.")
    reward: Literal['donation', 'contest', 'giveaway'] | None = Field(None, description='Custom incentive type the customer fulfils themselves; null means none. Describe it in reward_blurb.')
    reward_blurb: str | None = Field(None, description='Describes the custom incentive to respondents. The editor caps it at 140 characters and nothing else does.', max_length=140)
    show_help: StrictBool | None = Field(None, description='Show Help & FAQ links to respondents.')
    show_how_it_works: StrictBool | None = Field(None, description='Show the "How it Works" explainer to respondents.')
    show_spokesperson: StrictBool | None = Field(None, description='Show the contact as a spokesperson on the collector pages.')
    show_step_numbers: StrictBool | None = Field(None, description='Number the steps a respondent walks through.')
    include_custom_release: StrictBool | None = Field(None, description="Use the workspace's custom release rather than the standard one. Needs a plan with custom releases.")
    kiosk_mode: StrictBool | None = Field(None, description='Run the collector as a kiosk: it returns to the start after each response. Overrides the custom thank-you call-to-action. Needs a plan with kiosk mode.')
    show_custom_finish_cta: StrictBool | None = Field(None, description='Show a custom call-to-action on the thank-you screen instead of the Vocal Video one. Kiosk mode overrides it. Needs a plan without the Vocal Video CTA.')
    custom_finish_cta_label: str | None = Field(None, description='Button text for the custom thank-you call-to-action.', max_length=191)
    custom_finish_cta_message: str | None = Field(None, description='Message above the custom thank-you call-to-action.', max_length=191)
    custom_finish_cta_url: str | None = Field(None, description='Where the custom thank-you call-to-action links.')
    invitation_body: str | None = Field(None, description='Body copy of the invitation email.')
    invitation_cta: str | None = Field(None, description='Call-to-action button label on the invitation email.', max_length=191)
    reminder_subject: str | None = Field(None, description='Subject line of the reminder email.', max_length=191)
    reminder_body: str | None = Field(None, description='Body copy of the reminder email.')
    reminder_cta: str | None = Field(None, description='Call-to-action button label on the reminder email.', max_length=191)
    show_logo: StrictBool | None = Field(None, description="Whether the workspace logo appears on the collector's public pages. Set false to hide it.")
    template_id: StrictInt | None = Field(None, description="Workspace template id (from list_templates) this collector's drafts assemble with — used by auto-assembly and as the reply page's default. Overrides the workspace default template. Pass null — or the current default's id — to clear the override so the collector follows the workspace default, tracking future default changes; the payload then reports template_id: null.")
    auto_assemble_drafts: StrictBool | None = Field(None, description="When true, every new finalized response automatically assembles a draft video using the collector's template (or the workspace default).")

class VocalVideoSetCollectorStatusConfig(_Input):
    """Activate a collector or pause it so its link stops accepting submissions."""
    operation: Literal['set_collector_status'] = Field('set_collector_status', json_schema_extra={"ui:hidden": True})
    collector_id: StrictInt = Field(...)
    status: Literal['active', 'inactive'] = Field(...)

class VocalVideoSendCollectorInvitationConfig(_Input):
    """Preview invitation recipients with confirm=false. After confirming the preview, run again with the same recipients/message, confirm=true and the returned confirmation_token. Sending emails spends one video-request credit per recipient."""
    operation: Literal['send_collector_invitation'] = Field('send_collector_invitation', json_schema_extra={"ui:hidden": True})
    collector_id: StrictInt = Field(...)
    emails: list[str] = Field(..., description='Recipient email addresses. Skipped reasons surface in the preview.')
    message: str | None = Field(None, description="Optional override for the invitation email body. Defaults to the collector's template copy.")
    confirm: StrictBool | None = Field(None, description='Set true only after the user has explicitly confirmed the preview. Defaults to false.')
    confirmation_token: str | None = Field(None, description='External API/MCP only: the token returned by the confirm:false preview. Required alongside confirm:true on that surface.')

    @model_validator(mode="after")
    def confirmation(self):
        if self.confirm and not self.confirmation_token:
            raise ValueError("Preview with confirm=false first, then supply the returned confirmation token to send")
        return self

class VocalVideoListRepliesConfig(_Input):
    """Find video/audio responses using transcript and respondent filters. Retains locked and pending-indexing indicators; pending indexing does not mean the workspace is empty."""
    operation: Literal['list_replies'] = Field('list_replies', json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description="Full-text search across transcript content, respondent name, job title, and company. Pass when the user's request implies a topic, theme, or keyword (e.g., 'hiring', 'onboarding', 'team culture'). Omit for unfiltered browse by recency.")
    response_type: Literal['testimonial', 'personal_message', 'leadership_message', 'expert_content', 'hiring_screening', 'impact_story', 'other'] | None = Field(None, description='Filter by response shape. `testimonial` is the default for customer/employee endorsements (~60% of corpus). `personal_message` is greetings/dedications addressed to specific people. `leadership_message` is exec/leadership outbound to a group. `expert_content` is educational/tutorial from an expert. `hiring_screening` is job/scholarship applications — exclude from marketing storyboards. `impact_story` is beneficiary/program narrative. For most storyboard-building, default to `testimonial` or omit to scan everything.')
    sentiment: Literal['positive', 'negative', 'neutral', 'mixed'] | None = Field(None, description="Filter by inferred sentiment. Useful for 'positive customer testimonials' or 'critical product feedback'. Corpus skews positive — `negative` / `mixed` filters meaningfully narrow.")
    specificity: Literal['low', 'medium', 'high'] | None = Field(None, description="Filter by how concrete the response is. `high` = specific outcomes, numbers, named details ('cut deployment time in half'). `low` = generic praise ('game changer', 'top-notch'). Storyboards usually benefit from `medium` or `high`. Pass `high` when the user wants impact-driven content.")
    topics: list[str] | None = Field(None, description="Filter to replies whose extracted topics overlap with these terms (any-match, case-insensitive). Example: ['team culture', 'onboarding'].")
    job_title_contains: str | None = Field(None, description='Substring match on respondent job_title (case-insensitive).')
    company_contains: str | None = Field(None, description='Substring match on respondent company_name (case-insensitive).')
    collector_id: StrictInt | None = Field(None, description='Restrict to one specific collector (a particular ask or survey).')
    format: Literal['video', 'audio'] | None = Field(None)
    starred: StrictBool | None = Field(None, description='If true, return only starred (favorited) responses.')
    has_release: StrictBool | None = Field(None, description='If true, return only responses with a signed release — safe for public use.')
    since_days: StrictInt | None = Field(None, description='Optional narrowing window — restrict to responses from the last N days. Results are already returned in recency order by default; only pass this when the user has expressed an explicit time constraint (e.g. "from this quarter", "last month"). Do NOT pass it for vague phrasings like "recent" — the natural sort handles that.')
    limit: StrictInt = Field(20, description='Max results to return.', le=50)

class VocalVideoGetReplyConfig(_Input):
    """Read a selected video/audio response and its footage details."""
    operation: Literal['get_reply'] = Field('get_reply', json_schema_extra={"ui:hidden": True})
    id: StrictInt = Field(..., description='Reply id from list_replies.')

class VocalVideoStarReplyConfig(_Input):
    """Mark a response as a workspace favorite."""
    operation: Literal['star_reply'] = Field('star_reply', json_schema_extra={"ui:hidden": True})
    id: StrictInt = Field(..., description='Reply id from list_replies.')

class VocalVideoUnstarReplyConfig(_Input):
    """Remove a response from workspace favorites."""
    operation: Literal['unstar_reply'] = Field('unstar_reply', json_schema_extra={"ui:hidden": True})
    id: StrictInt = Field(..., description='Reply id from list_replies.')

class VocalVideoListGalleriesConfig(_Input):
    """Find workspace galleries. Results are a shortlist; narrow filters when truncated."""
    operation: Literal['list_galleries'] = Field('list_galleries', json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description='Full-text search across title, headline, and subhead.')
    style: Literal['carousel', 'slideshow', 'wall', 'grid', 'list'] | None = Field(None, description='Filter by layout style (`carousel`, `slideshow`, `wall`, `grid`, `list`).')
    visibility: Literal['publicly', 'unlisted', 'privately'] | None = Field(None, description='`publicly` = public + searchable; `unlisted` = public link only; `privately` = workspace-only.')
    starred: StrictBool | None = Field(None, description='If true, return only starred (favorited) galleries.')
    since_days: StrictInt | None = Field(None, description='Restrict to galleries created in the last N days.')
    sort: Literal['newest', 'oldest', 'view'] | None = Field(None, description='`newest` (default) by creation recency, `oldest` reverses it, `view` by total view count.')
    limit: StrictInt = Field(20, description='Max results to return.', le=50)

class VocalVideoGetGalleryConfig(_Input):
    """Read gallery details and item slot IDs."""
    operation: Literal['get_gallery'] = Field('get_gallery', json_schema_extra={"ui:hidden": True})
    id: StrictInt = Field(..., description='Gallery id from list_galleries.')

class VocalVideoCreateGalleryConfig(_Input):
    """Create a gallery with optional published storyboards and uploaded clips. Unpublished storyboards and response clips are rejected by Vocal Video."""
    operation: Literal['create_gallery'] = Field('create_gallery', json_schema_extra={"ui:hidden": True})
    title: str | None = Field(None, description='Internal gallery title (workspace-only).', max_length=191)
    headline: str | None = Field(None, description='Public-facing headline shown above the items.', max_length=191)
    subhead: str | None = Field(None, description='Public-facing subhead under the headline.')
    style: Literal['carousel', 'slideshow', 'wall', 'grid', 'list'] | None = Field(None, description='Layout: `grid` (default), `carousel`, `slideshow`, `wall`, `list`.')
    storyboard_ids: list[StrictInt] | None = Field(None, description='Published videos to fill the gallery with, in display order. Anything not yet published is rejected — publish first or leave them out.')
    clip_ids: list[StrictInt] | None = Field(None, description='Uploaded clips from `list_uploaded_clips` to fill the gallery with, in display order. Added after any `storyboard_ids`. A clip from a response is rejected.')

class VocalVideoAddStoryboardToGalleryConfig(_Input):
    """Add one or several published videos to a gallery in the supplied order."""
    operation: Literal['add_storyboard_to_gallery'] = Field('add_storyboard_to_gallery', json_schema_extra={"ui:hidden": True})
    gallery_id: StrictInt = Field(...)
    storyboard_id: StrictInt | None = Field(None, description='A single published video.')
    storyboard_ids: list[StrictInt] | None = Field(None, description='Several published videos at once, added in array order. Preferred whenever there is more than one.')

    @model_validator(mode="after")
    def videos(self):
        if self.storyboard_id is None and not self.storyboard_ids:
            raise ValueError("Supply storyboard_id or storyboard_ids from published videos")
        return self

class VocalVideoRemoveFromGalleryConfig(_Input):
    """Remove an item from a gallery by slot ID, or by storyboard/clip ID. Slot ID from get_gallery is preferred."""
    operation: Literal['remove_from_gallery'] = Field('remove_from_gallery', json_schema_extra={"ui:hidden": True})
    gallery_id: StrictInt = Field(...)
    slot_id: StrictInt | None = Field(None, description='Slot id from get_gallery.items[].slot_id. Preferred.')
    storyboard_id: StrictInt | None = Field(None, description="Storyboard id — used to look up the slot if slot_id isn't passed.")
    clip_id: StrictInt | None = Field(None, description="Clip id — used to look up the slot if slot_id isn't passed.")

    @model_validator(mode="after")
    def target(self):
        if all(v is None for v in (self.slot_id, self.storyboard_id, self.clip_id)):
            raise ValueError("Supply a slot_id, storyboard_id or clip_id to remove")
        return self

class VocalVideoGetGalleryShareUrlConfig(_Input):
    """Get a gallery sharing URL without changing its visibility."""
    operation: Literal['get_gallery_share_url'] = Field('get_gallery_share_url', json_schema_extra={"ui:hidden": True})
    gallery_id: StrictInt = Field(...)

class VocalVideoGetGalleryEmbedCodeConfig(_Input):
    """Get a gallery embed snippet without changing its visibility."""
    operation: Literal['get_gallery_embed_code'] = Field('get_gallery_embed_code', json_schema_extra={"ui:hidden": True})
    gallery_id: StrictInt = Field(...)

class VocalVideoListStoryboardsConfig(_Input):
    """Find workspace videos by content, publication and visibility. Shortlist results are not workspace totals."""
    operation: Literal['list_storyboards'] = Field('list_storyboards', json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description='Full-text search across title, internal title, description, and the full transcript. Pass when the user names a topic, theme, or keyword. Omit for unfiltered browse by recency.')
    status: Literal['draft', 'published'] | None = Field(None, description='Filter by lifecycle. `published` covers anything the user has shipped (including publishing-in-progress / errored renders); `draft` covers unfinished editor work. Omit for both. Archived videos are never returned.')
    visibility: Literal['publicly', 'unlisted', 'privately'] | None = Field(None, description='Filter by public visibility. `publicly` = public + searchable; `unlisted` = public link only; `privately` = workspace-only. Useful for "show me public videos" or "find my private drafts".')
    aspect_ratio: Literal['square', 'portrait', 'landscape'] | None = Field(None, description='Filter by aspect ratio: `landscape`, `portrait`, or `square`.')
    starred: StrictBool | None = Field(None, description="If true, return only starred videos (the user's favorites).")
    since_days: StrictInt | None = Field(None, description='Restrict to videos created in the last N days (based on draft creation date). Only pass when the user named an explicit time window ("this quarter", "last month"). For "videos I published this quarter" use `since_published_days` instead. Results are recency-ordered by default — don\'t pass this for vague "recent".')
    since_published_days: StrictInt | None = Field(None, description='Restrict to videos published in the last N days (based on last_published_at). Use this for "newly published", "shipped this quarter", or gallery-refresh asks ("rotate in my newest published videos"). Drafts have no publish date and will not match.')
    sort: Literal['newest', 'oldest', 'play', 'view', 'published'] | None = Field(None, description='`newest` (default) by creation recency, `oldest` reverses it, `play` orders by total play count, `view` by total view count, `published` orders by last publish date (drafts sort last). Pick `play` or `view` for "most popular" / "best performing" asks; pick `published` for "most recently shipped".')
    limit: StrictInt = Field(20, description='Max results to return.', le=50)

class VocalVideoGetStoryboardSummaryConfig(_Input):
    """Read the lighter video metadata and design summary without the scene list."""
    operation: Literal['get_storyboard_summary'] = Field('get_storyboard_summary', json_schema_extra={"ui:hidden": True})
    id: StrictInt = Field(..., description='Storyboard id from list_storyboards.')

class VocalVideoGetStoryboardConfig(_Input):
    """Read a selected video and its scenes, or request the lighter summary."""
    operation: Literal['get_storyboard'] = Field('get_storyboard', json_schema_extra={"ui:hidden": True})
    id: StrictInt = Field(..., description='Storyboard id (e.g., from list_storyboards).')
    summary: StrictBool | None = Field(None, description='If true, return the lighter get_storyboard_summary payload (no scene list, no polish flags). Useful when picking a video from a list and you only need its metadata + design summary.')

class VocalVideoSetStoryboardMetadataConfig(_Input):
    """Change public video title/description and the internal workspace title."""
    operation: Literal['set_storyboard_metadata'] = Field('set_storyboard_metadata', json_schema_extra={"ui:hidden": True})
    storyboard_id: StrictInt = Field(...)
    title: str | None = Field(None, description='Public-facing title (share page, embed). Keep under ~80 characters.', max_length=191)
    internal_title: str | None = Field(None, description='Workspace-only disambiguation label. Never shown publicly.')
    description: str | None = Field(None, description='Public-facing description (share / embed). Under ~200 characters.')

class VocalVideoSetStoryboardVisibilityConfig(_Input):
    """Set video visibility to public and searchable, unlisted link access, or private workspace access."""
    operation: Literal['set_storyboard_visibility'] = Field('set_storyboard_visibility', json_schema_extra={"ui:hidden": True})
    storyboard_id: StrictInt = Field(...)
    visibility: Literal['publicly', 'unlisted', 'privately'] = Field(..., description='`publicly` (public + searchable), `unlisted` (public link only), or `privately` (workspace-only).')

class VocalVideoGetStoryboardShareUrlConfig(_Input):
    """Get a video sharing URL without changing its visibility."""
    operation: Literal['get_storyboard_share_url'] = Field('get_storyboard_share_url', json_schema_extra={"ui:hidden": True})
    storyboard_id: StrictInt = Field(...)

class VocalVideoGetStoryboardEmbedCodeConfig(_Input):
    """Get video embed HTML with optional layout, playback and display settings."""
    operation: Literal['get_storyboard_embed_code'] = Field('get_storyboard_embed_code', json_schema_extra={"ui:hidden": True})
    storyboard_id: StrictInt = Field(...)
    alignment: Literal['Left', 'Center'] | None = Field(None, description='`Center` (default) or `Left`. Applies when the embed is narrower than its container.')
    autoplay: StrictBool | None = Field(None, description='If true, the video starts muted on page load.')
    corners: Literal['square', 'small', 'large'] | None = Field(None, description='`square` (default), `small`, or `large` corner radius.')
    max_width: Literal[360, 540, 720, 1080, 1920] | None = Field(None, description="Cap the embed width in pixels. Omit to use the storyboard's aspect-ratio-derived default.")
    popover: StrictBool | None = Field(None, description='If true, the embed renders as a clickable thumbnail that opens the video in a popover.')
    shadow: Literal['None', 'Thin', 'Thick'] | None = Field(None, description='`None` (default), `Thin`, or `Thick` drop shadow.')
    show_pull_quote: StrictBool | None = Field(None, description="If true, the video's featured pull quote renders alongside the embed.")

VocalVideoConfig = Annotated[Union[
    VocalVideoGetAccountUsageConfig,
    VocalVideoListCollectorsConfig,
    VocalVideoGetCollectorConfig,
    VocalVideoCreateCollectorConfig,
    VocalVideoUpdateCollectorConfig,
    VocalVideoSetCollectorStatusConfig,
    VocalVideoSendCollectorInvitationConfig,
    VocalVideoListRepliesConfig,
    VocalVideoGetReplyConfig,
    VocalVideoStarReplyConfig,
    VocalVideoUnstarReplyConfig,
    VocalVideoListGalleriesConfig,
    VocalVideoGetGalleryConfig,
    VocalVideoCreateGalleryConfig,
    VocalVideoAddStoryboardToGalleryConfig,
    VocalVideoRemoveFromGalleryConfig,
    VocalVideoGetGalleryShareUrlConfig,
    VocalVideoGetGalleryEmbedCodeConfig,
    VocalVideoListStoryboardsConfig,
    VocalVideoGetStoryboardSummaryConfig,
    VocalVideoGetStoryboardConfig,
    VocalVideoSetStoryboardMetadataConfig,
    VocalVideoSetStoryboardVisibilityConfig,
    VocalVideoGetStoryboardShareUrlConfig,
    VocalVideoGetStoryboardEmbedCodeConfig,
], Field(discriminator="operation")]


class VocalVideoFullConfig(NodeConfig[VocalVideoConfig, VocalVideoAPIKeyCredential]):
    pass


class VocalVideoNode(WorkflowNode):
    integration_type = "automation-vocal-video"
    connection_evidence = ConnectionEvidence(
        noun="video collectors", operation="list_collectors",
        label_keys=("nickname", "title", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return VocalVideoFullConfig

    @staticmethod
    def _config_view(data):
        # Saved workflow attachment metadata is not part of the tool input.
        if isinstance(data.get("config"), dict):
            return {**data, "config": {k: v for k, v in data["config"].items() if k != "credentialIds"}}
        return data

    @classmethod
    def validate_config(cls, config_data):
        return super().validate_config(cls._config_view(config_data))

    @classmethod
    def parse_config(cls, config_data):
        return super().parse_config(cls._config_view(config_data))

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Vocal Video API key")
        config = self.config.config
        operation = config.operation
        # Every route comes from the discriminated operation union, never user URLs.
        body = config.model_dump(exclude={"operation"}, exclude_unset=True)
        # Omit optional nulls unless the contract explicitly accepts null.
        nullable = {"release_id", "reward", "template_id"} if operation == "update_collector" else set()
        body = {k: v for k, v in body.items() if v is not None or k in nullable}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(
                "POST", BASE_URL + operation, json=body,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
            )
        # Keep provider rejection words for the connection seam, redacting the key
        # if a faulty upstream echoes it. Never include request headers or bodies.
        if response.status_code != 200:
            message = "Vocal Video request failed"
            try:
                error = response.json().get("error", {})
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"][:2000].replace(credential.api_key, "[redacted]")
            except (ValueError, AttributeError):
                pass
            return {"status": "error", "operation": operation, "http_status": response.status_code, "error": message}
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json" or len(response.content) > 262144:
            raise ValueError("Expected a bounded Vocal Video JSON tool response; inspect writes before retrying")
        payload = response.json()
        if (not isinstance(payload, dict) or "error" in payload
                or not isinstance(payload.get("tool"), str) or not isinstance(payload.get("result"), dict)):
            raise ValueError("Vocal Video returned an invalid tool result; inspect writes before retrying")
        result = payload["result"]
        if result.get("error") or result.get("success") is False:
            return {"status": "error", "operation": operation, "error": "Vocal Video did not confirm the tool result", "data": result}
        return {"status": "success", "operation": operation, "tool": payload["tool"], "data": result}
