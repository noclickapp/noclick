"""Memelord Tools API v2.1.0: one documented REST call per operation.

Contract: https://www.memelord.com/api/v1/openapi.json
Documentation: https://www.memelord.com/hackers/docs#tools-api
Video creation returns job IDs; use check_video_status separately to poll.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://www.memelord.com"


class MemelordAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Memelord API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.memelord.com/settings/developer",
            "x-credential-instructions": "Create an API key in Memelord Developer Settings and paste it here. Generation and editing draw from your Memelord usage balance; account, discovery, and job-status reads are free.",
        })
    credential_type: Literal["memelord_api_key"] = Field("memelord_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, min_length=1,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class MemelordCharacter(_Input):
    target: str = Field(..., min_length=1, max_length=120)
    image_urls: list[str] = Field(..., min_length=1, max_length=8)


class MemelordSearchMemesConfig(_Input):
    'Search Memelord\'s template library of memes, video clips, and stickers. Default method "semantic_context" matches what a meme MEANS or depicts (natural-language queries like "when the deploy works on the first try"). Use "fulltext" for exact names and proper nouns ("drake", "spongebob"), "fuzzy" for misspellings, "semantic_combined" when visual identity matters, or "semantic_media" with media_url to find templates that look like a given image. Results come best match first and include ids you can pass as template_id to generate_caption_meme / generate_ai_meme / generate_video_meme / get_meme_template. Paging: each response has has_more and next_offset; to get the next page, repeat the exact same call (same query, method, filters, limit, min_score) with offset set to next_offset, and stop when has_more is false (next_offset is null). Pass ids you already have in exclude_ids only when starting a fresh search, not while paging, or the pages shift. Free.'
    operation: Literal['search_memes'] = Field('search_memes', title='Search Memes', json_schema_extra={"ui:hidden": True})
    query: str | None = Field(None, description='Search text. Required unless method is "semantic_media".')
    method: Literal['semantic_context', 'semantic_combined', 'semantic_media', 'fulltext', 'fuzzy'] | None = Field(None, description='semantic_context (default) | semantic_combined | semantic_media | fulltext | fuzzy')
    type: Literal['meme', 'video', 'sticker'] | None = Field(None, description='Only return this asset type. Use "video" to find templates for generate_video_meme.')
    limit: int | None = Field(None, ge=1, le=100, description='Max results (default 20, max 100)')
    offset: int | None = Field(None, ge=0, le=1000, description="Results to skip (default 0, max 1000). Pass the previous response's next_offset to fetch the next page.")
    min_score: float | None = Field(None, ge=0, le=1, description='Override the per-method relevance floor (0-1). Lower it when a specific query returns nothing.')
    media_url: str | None = Field(None, description='Image/video URL to search by, for method "semantic_media"', json_schema_extra={"format": "uri"})
    tags: list[str] | None = Field(None, description='Only assets carrying any of these tags')
    template_approved: bool | None = Field(None, description='Only curator-approved templates')
    face_swappable: bool | None = Field(None, description='Only templates with a face that can be swapped')
    include_nsfw: bool | None = Field(None, description='Include NSFW-tagged assets (default true)')
    exclude_ids: list[str] | None = Field(None, description='Asset ids to skip (e.g. ones you already used)')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordGetMemeTemplateConfig(_Input):
    'Fetch one template asset by id: name, type (meme | video | sticker), media URL, description, tags, dimensions, and how many text slots its layout has. Use it to inspect a search result before generating with template_id. Free.'
    operation: Literal['get_meme_template'] = Field('get_meme_template', title='Get Meme Template', json_schema_extra={"ui:hidden": True})
    template_id: str = Field(..., description='Asset id from search_memes or get_trending_memes')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordGetTrendingMemesConfig(_Input):
    'What\'s trending right now: the most recent curated trending templates with a short cultural-context blurb explaining the format. Use it to pick timely templates for generate_caption_meme / generate_ai_meme / generate_video_meme, or to answer "what memes are hot this week". NSFW drops are never included. Free.'
    operation: Literal['get_trending_memes'] = Field('get_trending_memes', title='Get Trending Memes', json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=12, description='Number of trending templates (default 3, max 12)')
    media_type: Literal['image', 'video'] | None = Field(None, description='Only still images or only video clips. Omit for a mix.')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordListImageToolsConfig(_Input):
    'Catalog of one-shot image tools you can run with run_image_tool: celebrity face swaps (Trump, Elon, Zuck, Vance, …), filters (Bust Down, Wojakify, GigaChad, Looksmaxxing, mugshot, Windows 95), and text-to-image generators (mascots, logos, Pokémon-style cards). Each entry lists its tool_id, whether it needs an image and/or a prompt, and any extra params. Free.'
    operation: Literal['list_image_tools'] = Field('list_image_tools', title='List Image Tools', json_schema_extra={"ui:hidden": True})
    category: Literal['image-to-image', 'image-text-to-image', 'text-to-image'] | None = Field(None, description='Filter by input contract')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordGenerateCaptionMemeConfig(_Input):
    'Classic caption memes: Jester picks a real meme template from the library (or uses template_id), writes new text for its caption slots, and renders that text on the unchanged template image. The picture is never AI-edited or repainted — use generate_ai_meme for that. Returns signed image URLs plus template_id, caption_slots, and an edit_handle you can hand to edit_meme to change the wording. Use search_memes or get_trending_memes first if you want to pick the template yourself. Billed against your usage balance.'
    operation: Literal['generate_caption_meme'] = Field('generate_caption_meme', title='Generate Caption Meme', json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, description='Topic, idea, or joke premise for the meme')
    count: int | None = Field(None, ge=1, le=10, description='Number of memes to generate (default 1, max 10)')
    template_id: str | None = Field(None, description='Pin a specific image template asset id (from search_memes / get_trending_memes)')
    include_nsfw: bool | None = Field(None, description='Allow NSFW-tagged templates (default true)')
    include_political: bool | None = Field(None, description='Allow political-tagged templates (default true)')
    category: Literal['classic', 'trending'] | None = Field(None, description='Template pool: "classic" (default) draws from classic templates that have real caption slots; "trending" draws from current trending templates')
    caption_style: Literal['tiktok', 'snapchat'] | None = Field(None, description='Style for single-caption renders (one caption on the image): "tiktok" (default, bold centered outlined text) or "snapchat" (translucent strip across the image). Both are drawn on top of the image. Multi-slot templates keep their own text boxes and ignore this.')
    use_search_context: bool | None = Field(None, description='Ground the joke in live web search results about the topic (default true). Disable for faster, purely template-driven output.')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordGenerateAiMemeConfig(_Input):
    'AI-remixed image memes: Jester picks a meme template (or uses template_id), AI-edits the picture itself to fit the joke — swapping subjects, adding objects, or painting in people and products from reference_image_urls — then captions it. Use generate_caption_meme instead when you only want new text on an unchanged classic template. Returns signed image URLs plus template_id, caption_slots, and an edit_handle for edit_meme. Billed against your usage balance.'
    operation: Literal['generate_ai_meme'] = Field('generate_ai_meme', title='Generate AI Meme', json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, description='Topic, idea, or joke premise for the meme')
    count: int | None = Field(None, ge=1, le=10, description='Number of memes to generate (default 1, max 10)')
    template_id: str | None = Field(None, description='Pin a specific image template asset id (from search_memes / get_trending_memes)')
    include_nsfw: bool | None = Field(None, description='Allow NSFW-tagged templates (default true)')
    include_political: bool | None = Field(None, description='Allow political-tagged templates (default true)')
    category: Literal['trending', 'classic'] | None = Field(None, description='Restrict template selection to the trending pool or the classics pool (default: both)')
    reference_image_urls: list[str] | None = Field(None, max_length=3, description='Up to 3 public image URLs (a person, product, logo, or style) for the AI edit to paint into the template; upload local files with upload_media first')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordEditMemeConfig(_Input):
    "Change the text of an image meme you already generated. Pass the edit_handle from a generate_caption_meme / generate_ai_meme (or previous edit_meme) result together with a plain-language instruction; use the slot numbers from that result's caption_slots as target_index to change just one box. Re-renders the image and returns a fresh URL, the updated caption_slots, and a new edit_handle (earlier handles stay valid, so you can branch from any version). Handles only work for the account that created them. Billed against your usage balance."
    operation: Literal['edit_meme'] = Field('edit_meme', title='Edit Meme', json_schema_extra={"ui:hidden": True})
    instruction: str = Field(..., min_length=1, description='What to change, e.g. "make the bottom text about JavaScript instead"')
    edit_handle: UUID = Field(..., description='edit_handle from the generate_caption_meme, generate_ai_meme, or edit_meme result being edited')
    target_index: int | None = Field(None, ge=1, description='slot number (from caption_slots) of the one text box to change. Omit to let the editor decide.')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordGenerateVideoMemeConfig(_Input):
    'Generate AI-captioned video memes from a topic. Jester picks video templates (or uses template_id), writes the caption text, and starts render jobs. Rendering is asynchronous: this returns job_ids immediately — poll check_video_status (or list_video_jobs) until status is "completed" to get the MP4 URL. Billed against your usage balance.'
    operation: Literal['generate_video_meme'] = Field('generate_video_meme', title='Generate Video Meme', json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, description='Topic or idea for the video meme')
    count: int | None = Field(None, ge=1, le=5, description='Number of video memes (default 1, max 5)')
    category: Literal['trending', 'classic'] | None = Field(None, description='Restrict template selection to trending or classics')
    include_nsfw: bool | None = Field(None, description='Allow NSFW-tagged templates (default true)')
    include_political: bool | None = Field(None, description='Allow political-tagged templates (default true)')
    template_id: str | None = Field(None, description='Pin a specific video template asset id (from search_memes with type "video")')
    force_caption_style: Literal['top', 'tiktok'] | None = Field(None, description='Force the caption-bar path: "top" (letterbox above the clip) or "tiktok" (centered overlay). Omit to let templates with saved compositions use them.')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordEditVideoMemeConfig(_Input):
    'Rewrite the caption of a video meme and re-render it. Provide the template_id and the current caption from a previous generate_video_meme job plus a plain-language instruction. Starts a new render job — poll check_video_status for the MP4. Billed against your usage balance.'
    operation: Literal['edit_video_meme'] = Field('edit_video_meme', title='Edit Video Meme', json_schema_extra={"ui:hidden": True})
    instruction: str = Field(..., min_length=1, description='What to change about the caption')
    template_id: str = Field(..., description='Video template asset id')
    caption: str = Field(..., description='Current caption text to edit')
    force_caption_style: Literal['top', 'tiktok'] | None = Field(None, description='Force caption style: "top" (letterbox) or "tiktok" (centered overlay)')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordCheckVideoStatusConfig(_Input):
    'Check one video job from any video-producing tool. Returns status (pending / processing → completed | failed) and the MP4 download URL once complete. Free — poll every few seconds after a tool returns a job_id.'
    operation: Literal['check_video_status'] = Field('check_video_status', title='Check Video Status', json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., description='job_id returned by a video tool (e.g. generate_video_meme, edit_video_meme, run_agent) or list_video_jobs')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordListVideoModelsConfig(_Input):
    "List the pro AI video models this account can run — Kling 3.0, Kling O3, Seedance, Wan 3.0, Cinema Studio 4.0 (run with run_video_model), Genjutsu character transpose (run with run_genjutsu), and Gemini Omni, Google's Gemini video model for editing a clip, animating a still, or generating from a prompt (run with run_gemini_omni). Each entry lists required and optional inputs, rules, and params (options, ranges, defaults). Call this before run_video_model to pick a model and valid params. Free."
    operation: Literal['list_video_models'] = Field('list_video_models', title='List Video Models', json_schema_extra={"ui:hidden": True})
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordRunVideoModelConfig(_Input):
    'Generate new AI video footage with one model from list_video_models: from a prompt alone, a start frame (image_url, optional end_image_url), or reference images / clips / audio. Use this for original footage ("a cinematic drone shot over Tokyo at night", "animate this photo"). For a meme template turned into a captioned video clip use generate_video_meme; for still images use run_image_tool or generate_ai_meme; to put a person into an existing clip use run_genjutsu. Media must be public URLs the user provided — never invent or guess them; if the user gave you local files, upload them with upload_media and pass the returned url. Invalid requests come back as status "invalid_request" listing every problem, with nothing charged. The request\'s full cost is reserved from your usage balance before it starts; a balance that cannot cover it gets the usual usage-balance error and nothing is started or charged. Returns a job_id; poll check_video_status until completed (usually a few minutes). Billed against your usage balance per generated second once the job finishes; the reservation is released if it fails.'
    operation: Literal['run_video_model'] = Field('run_video_model', title='Run Video Model', json_schema_extra={"ui:hidden": True})
    model_id: Literal['kling', 'kling-o3', 'seedance', 'wan', 'cinema-studio'] = Field(..., description='model_id from list_video_models')
    prompt: str = Field(..., min_length=1, max_length=2000, description='Scene, action, camera, lighting, and motion')
    image_url: str | None = Field(None, description='Start / first-frame image (models with a start frame)', json_schema_extra={"format": "uri"})
    end_image_url: str | None = Field(None, description='Last-frame image; requires image_url', json_schema_extra={"format": "uri"})
    reference_image_urls: list[str] | None = Field(None, max_length=10, description='Reference images (Image 1, Image 2, … in the prompt)')
    reference_video_urls: list[str] | None = Field(None, max_length=5, description='Reference clips for motion / camera (Video 1, …)')
    reference_audio_urls: list[str] | None = Field(None, max_length=5, description='Reference audio (Audio 1, …)')
    duration: int | None = Field(None, description="Length in seconds, within the model's range")
    aspect_ratio: str | None = Field(None, description="One of the model's aspect_ratio options")
    resolution: str | None = Field(None, description="One of the model's resolution options")
    generate_audio: bool | None = Field(None, description='Generate a soundtrack, where the model supports it')
    variant: str | None = Field(None, description='Model version / quality tier from list_video_models')
    seed: int | None = Field(None, ge=0, le=2147483647, description='Seed for reproducibility (Wan only)')
    title: str | None = Field(None, max_length=120, description='Short title for the saved video')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordRunGenjutsuConfig(_Input):
    'Genjutsu character transpose: put a person or character into an existing video clip while keeping its motion, choreography, camera, timing, and audio ("put me in this music video", "swap the dancer for my character"). Needs the source clip (video_url, or video_job_id of a finished video on this account) and 1-8 photos in total of who to put in (character_image_urls for one person). Several people can be recast in ONE call: pass characters=[{target, image_urls}] with one entry per person, where target is who in the source clip they replace ("the king", "the guy playing chess") and image_urls are that person\'s own photos; all entries share the 8-photo cap. Both must be real media the user provided — never invent, guess, or substitute URLs. When the user gives you local photos or a local clip, upload each with upload_media first (clips over 3 MB via create_media_upload_url) and pass the returned urls. If anything is missing the call returns status "needs_input" listing everything still needed, with nothing started or charged: ask the user once, then call again. To generate new footage use run_video_model; for meme-template video clips use generate_video_meme. The clip\'s full cost is reserved from your usage balance before it starts; a balance that cannot cover it gets the usual usage-balance error and nothing is started or charged. Returns a job_id; poll check_video_status until completed. Billed against your usage balance per second of the source clip once the job finishes; the reservation is released if it fails.'
    operation: Literal['run_genjutsu'] = Field('run_genjutsu', title='Run Genjutsu', json_schema_extra={"ui:hidden": True})
    video_url: str | None = Field(None, description='Public URL of the source clip (4-30 s; longer is trimmed); upload_media returns one for a local file')
    video_job_id: str | None = Field(None, description='job_id of a finished video on this account, instead of video_url')
    character_image_urls: list[str] | None = Field(None, max_length=8, description='1-8 public photo URLs of ONE person / character, clear front-facing first; upload local photos with upload_media. For several people use characters')
    characters: list[MemelordCharacter] | None = Field(None, max_length=8, description='Several people in one generation: one entry per person to swap in. Takes precedence over character_image_urls')
    prompt: str | None = Field(None, max_length=400, description="Optional short direction in the user's words (wardrobe, lighting)")
    mode: Literal['motion-transfer', 'object-swap'] | None = Field(None, description='motion-transfer (default, a person into the clip) or object-swap (swap an object / creature)')
    resolution: Literal['720p', '480p'] | None = Field(None, description='Output resolution (default 720p)')
    title: str | None = Field(None, max_length=120, description='Short title for the saved video')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordRunGeminiOmniConfig(_Input):
    'Run Gemini Omni, Google\'s Gemini video model, by name. Three lanes, picked from the inputs: EDIT an existing clip with a plain-language instruction (video_url, or video_job_id of a finished video on this account, plus prompt — "make it snow", "turn the car red", "add a top hat on the dog"); ANIMATE a still (image_url + prompt); or GENERATE a short clip from the prompt alone. Up to 3 reference_image_urls can ground identity, product, or style. Media must be public URLs the user provided — never invent or guess them; if the user gave you local files, upload them with upload_media first and pass the returned url. This runs Omni only: a safety-filter block comes back as an error instead of being re-routed to another model (for an edit that may try other engines use run_agent; for captioned meme clips use generate_video_meme; for other AI video models use run_video_model). Invalid requests come back as status "invalid_request" listing every problem, with nothing charged. Returns a job_id; poll check_video_status until completed (usually a couple of minutes). Billed against your usage balance once the render finishes.'
    operation: Literal['run_gemini_omni'] = Field('run_gemini_omni', title='Run Gemini Omni', json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, max_length=2000, description='What to generate, or what to change about the source clip')
    video_url: str | None = Field(None, description='Public URL of the clip to edit; upload_media returns one for a local file. Not combined with image_url')
    video_job_id: str | None = Field(None, description='job_id of a finished video on this account to edit, instead of video_url')
    image_url: str | None = Field(None, description='Public URL of a still image to animate. Not combined with video_url / video_job_id')
    reference_image_urls: list[str] | None = Field(None, max_length=3, description='Up to 3 public reference image URLs (identity, product, style)')
    title: str | None = Field(None, max_length=120, description='Short title for the saved video')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordRunAgentConfig(_Input):
    'Hand a natural-language request to Jester, Memelord\'s full meme agent — the same brain behind the Memelord chat. Jester decides what to do: search templates, caption a meme, remix a format, edit or generate an image, face-swap, make or caption a video, add text-to-speech or lipsync, convert to GIF, and more. Use this when a request does not map cleanly onto a specific tool ("turn this photo into a 3-panel meme about my cat", "make a video meme with the drake format about Mondays", "put my face on Elon"). Pass thread_id from a previous result to continue the conversation. Returns the assistant\'s message plus any images; videos come back as job_ids to poll with check_video_status. Billed against your usage balance.'
    operation: Literal['run_agent'] = Field('run_agent', title='Run Jester Agent', json_schema_extra={"ui:hidden": True})
    prompt: str = Field(..., min_length=1, description='What you want, in plain language')
    image_urls: list[str] | None = Field(None, max_length=5, description='Public image URLs to work with (photos to meme-ify, faces to swap, images to edit); upload local files with upload_media first')
    count: int | None = Field(None, ge=1, le=5, description='How many results you want (default 1, max 5)')
    thread_id: str | None = Field(None, description='thread_id from a previous run_agent result to continue that conversation')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordRunImageToolConfig(_Input):
    'Run one specific image tool from list_image_tools by tool_id — e.g. "donald-trump-face-swapper" with a face photo, "bust-down-filter" on a portrait, or "mascot-generator" with a prompt. Provide image_url for image-to-image tools, prompt for text-to-image tools, and params for any extra inputs the tool lists. Returns the resulting image URL(s). Prefer this over run_agent when you already know exactly which tool you want. Billed against your usage balance.'
    operation: Literal['run_image_tool'] = Field('run_image_tool', title='Run Image Tool', json_schema_extra={"ui:hidden": True})
    tool_id: str = Field(..., description='tool_id from list_image_tools')
    image_url: str | None = Field(None, description='Public URL of the input image (required by image tools); upload a local file with upload_media first', json_schema_extra={"format": "uri"})
    prompt: str | None = Field(None, description='Text input (required by text-to-image tools)')
    params: dict[str, str | float | bool] | None = Field(None, description='Extra tool-specific inputs keyed by the param key from list_image_tools')
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


class MemelordGetAccountConfig(_Input):
    'Return the authenticated Memelord account: user id, display name, email, usage balance (USD, rounded to cents), whether billable tools can run, where to add credits, how this MCP session is authenticated (OAuth or API key), and on API-key sessions the end_user_id received from the X-Memelord-End-User header (null when none was sent). Call this to confirm who you are acting as or to check whether billable tools will succeed. Free.'
    operation: Literal['get_account'] = Field('get_account', title='Get Account', json_schema_extra={"ui:hidden": True})
    end_user_id: str | None = Field(None, pattern='^[A-Za-z0-9_.:-]{1,128}$', description='Optional opaque id of your end user behind this call (never an email or a name), for usage reporting. Same as the X-Memelord-End-User header.')


MemelordOperation = Annotated[Union[
    MemelordSearchMemesConfig,
    MemelordGetMemeTemplateConfig,
    MemelordGetTrendingMemesConfig,
    MemelordListImageToolsConfig,
    MemelordGenerateCaptionMemeConfig,
    MemelordGenerateAiMemeConfig,
    MemelordEditMemeConfig,
    MemelordGenerateVideoMemeConfig,
    MemelordEditVideoMemeConfig,
    MemelordCheckVideoStatusConfig,
    MemelordListVideoModelsConfig,
    MemelordRunVideoModelConfig,
    MemelordRunGenjutsuConfig,
    MemelordRunGeminiOmniConfig,
    MemelordRunAgentConfig,
    MemelordRunImageToolConfig,
    MemelordGetAccountConfig
], Field(discriminator="operation")]


class MemelordFullConfig(NodeConfig[MemelordOperation, MemelordAPIKeyCredential]):
    pass


ROUTES = {'search_memes': ('GET', '/api/v1/templates/search'), 'get_meme_template': ('GET', '/api/v1/templates/{template_id}'), 'get_trending_memes': ('GET', '/api/v1/templates/trending'), 'list_image_tools': ('GET', '/api/v1/image-tools'), 'generate_caption_meme': ('POST', '/api/v1/memes/caption'), 'generate_ai_meme': ('POST', '/api/v1/memes/ai'), 'edit_meme': ('POST', '/api/v1/memes/edit'), 'generate_video_meme': ('POST', '/api/v1/video-memes'), 'edit_video_meme': ('POST', '/api/v1/video-memes/edit'), 'check_video_status': ('GET', '/api/v1/video-jobs/{job_id}'), 'list_video_models': ('GET', '/api/v1/video-models'), 'run_video_model': ('POST', '/api/v1/video-models/run'), 'run_genjutsu': ('POST', '/api/v1/genjutsu/run'), 'run_gemini_omni': ('POST', '/api/v1/gemini-omni/run'), 'run_agent': ('POST', '/api/v1/jester/run'), 'run_image_tool': ('POST', '/api/v1/image-tools/run'), 'get_account': ('GET', '/api/v1/account')}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class MemelordNode(WorkflowNode):
    integration_type = "automation-memelord"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_account")
    edit_examples = ["Search meme templates about shipping software", "Create a caption meme", "Check a video job"]

    @classmethod
    def get_config_model(cls):
        return MemelordFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Memelord API key")
        config = self.config.config
        secret = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for name in ("template_id", "job_id"):
            if "{" + name + "}" in path:
                identifier = values.pop(name)
                if not identifier or identifier in {".", ".."} or any(c in identifier for c in "/\\?#"):
                    raise ValueError("Use the template or job ID returned by Memelord")
                path = path.replace("{" + name + "}", quote(identifier, safe=""))
        # Arrays are repeated query keys; explicit false/zero values survive.
        params = [(key, str(item).lower() if isinstance(item, bool) else item)
                  for key, value in values.items()
                  for item in (value if isinstance(value, list) else [value])] if method == "GET" else None
        async with guarded_async_client(timeout=180, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + secret, "Accept": "application/json"},
                params=params, **({"json": values} if method == "POST" else {}))
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Memelord returned a non-JSON response") from None
        if not isinstance(body, dict):
            raise ValueError("Memelord returned an unexpected response shape")
        body = _redact(body, secret)
        if response.status_code != 200 or body.get("success") is False or body.get("status") in {"invalid_request", "needs_input", "failed"}:
            result = {"status": "error", "success": False, "http_status": response.status_code,
                      "error": body.get("error") or body.get("message") or "Memelord could not complete this request",
                      "data": body}
        else:
            result = {"status": "success", "data": body}
        await self.emit(result)
        return result
