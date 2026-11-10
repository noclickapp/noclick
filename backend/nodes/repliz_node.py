"""Repliz Public API v1.0.0: explicit operations and a newest-first comment poll."""
from __future__ import annotations
from typing import Annotated, Literal, Union, Optional, Any
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import WorkflowNode, NodeConfig
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

class ReplizCredential(BaseModel):
    model_config = ConfigDict(title="Repliz API Keys", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://api.repliz.com/public", "x-credential-instructions": "Paste your Repliz Access Key and Secret Key. Repliz sends these as the Basic authentication username and password."})
    credential_type: Literal["repliz_api_keys"] = Field("repliz_api_keys", json_schema_extra={"ui:hidden": True})
    access_key: str = Field(..., min_length=1, title="Access Key", json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., min_length=1, title="Secret Key", json_schema_extra={"ui:widget": "password"})

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class ReplizListAccountsConfig(Input):
    operation: Literal['list_accounts'] = Field('list_accounts', json_schema_extra={"x-display-name": 'List Accounts', "x-is-trigger": False})
    page: int = Field(1, ge=1, description='Page to return, starting from `1`. Accounts are sorted newest first.')
    limit: int = Field(20, ge=1, le=100, description='Items per page, for example `20`. The response says how many pages there are in `totalPages`.')
    types: Optional[list[Literal['facebook', 'instagram', 'threads', 'tiktok', 'youtube', 'linkedin', 'shopee', 'twitter', 'whatsapp', 'telegram', 'pinterest']]] = Field(None, description='Only return accounts of these platforms. Send each one as `types[]=facebook`.')
    search: Optional[str] = Field(None, description='Matches the account name or username, case-insensitive.')
    status: Optional[Literal['connected', 'disconnected']] = Field(None, description='`connected` (Repliz can use the account) or `disconnected` (it has to be reconnected first). Every account when left out.')
    tags: Optional[list[str]] = Field(None, description='Only return accounts with at least one of these tags, case-insensitive. Send each one as `tags[]=Brand%20A`.')

class ReplizGetAccountConfig(Input):
    operation: Literal['get_account'] = Field('get_account', json_schema_extra={"x-display-name": 'Get Account', "x-is-trigger": False})
    accountId: str = Field(..., description='ID of the account, the `_id` from Get Account.')

class ReplizCountAccountsConfig(Input):
    operation: Literal['count_accounts'] = Field('count_accounts', json_schema_extra={"x-display-name": 'Count Accounts', "x-is-trigger": False})

class ReplizListAccountTagsConfig(Input):
    operation: Literal['list_account_tags'] = Field('list_account_tags', json_schema_extra={"x-display-name": 'List Account Tags', "x-is-trigger": False})

class BodyUpdateTagAccountDTO(Input):
    tags: list[str] = Field(..., description='Every tag of the account, at most 10 of up to 30 characters. Replaces the current tags; send `[]` to remove them all. Duplicates that differ only in case are kept once, and a tag another account already has takes its spelling.')

class ReplizUpdateAccountTagsConfig(Input):
    operation: Literal['update_account_tags'] = Field('update_account_tags', json_schema_extra={"x-display-name": 'Update Account Tags', "x-is-trigger": False})
    accountId: str = Field(..., description='ID of the account, the `_id` from Get Account.')
    body: BodyUpdateTagAccountDTO = Field(..., description='Request body as documented by Repliz.')

class ReplizListCommentsConfig(Input):
    operation: Literal['list_comments'] = Field('list_comments', json_schema_extra={"x-display-name": 'List Comments', "x-is-trigger": False})
    page: int = Field(1, ge=1, description='Page to return, starting from `1`. Comments are sorted newest first.')
    limit: int = Field(20, ge=1, le=100, description='Items per page, for example `20`. The response says how many pages there are in `totalPages`.')
    status: Optional[Literal['pending', 'resolved', 'ignored']] = Field(None, description='`pending` (not handled yet), `resolved` (replied to or handled), or `ignored`. Every status when left out.')
    accountIds: Optional[list[str]] = Field(None, description='Only return items of these accounts, as `_id`s from Get Account. Send each one as `accountIds[]=ID`. All accounts when left out.')
    search: Optional[str] = Field(None, description='Matches the comment text, case-insensitive.')

class ReplizGetCommentConfig(Input):
    operation: Literal['get_comment'] = Field('get_comment', json_schema_extra={"x-display-name": 'Get Comment', "x-is-trigger": False})
    commentId: str = Field(..., description="ID of the comment in Repliz, the `_id` from Get Comment. This isn't the platform's comment ID.")

class BodyReplyCommentDTO(Input):
    text: str = Field(..., description='Text of the reply. Required, even when an `image` is attached. The comment is set to `resolved` after the reply is sent.')
    image: Optional[Any] = Field(None, description='An image posted together with `text`. Supported on Facebook, Threads, TikTok, LinkedIn and X (Twitter).')

class ReplizReplyCommentConfig(Input):
    operation: Literal['reply_comment'] = Field('reply_comment', json_schema_extra={"x-display-name": 'Reply Comment', "x-is-trigger": False})
    commentId: str = Field(..., description="ID of the comment in Repliz, the `_id` from Get Comment. This isn't the platform's comment ID.")
    body: BodyReplyCommentDTO = Field(..., description='Request body as documented by Repliz.')

class ReplizDeleteCommentConfig(Input):
    operation: Literal['delete_comment'] = Field('delete_comment', json_schema_extra={"x-display-name": 'Delete Comment', "x-is-trigger": False})
    commentId: str = Field(..., description="ID of the comment in Repliz, the `_id` from Get Comment. This isn't the platform's comment ID.")

class BodyUpdateStatusCommentDTO(Input):
    status: Literal['pending', 'resolved', 'ignored'] = Field(..., description='The new status: `pending` (not handled yet), `resolved` (handled), or `ignored`. It only changes the comment in Repliz, nothing is sent to the platform.')

class ReplizUpdateCommentStatusConfig(Input):
    operation: Literal['update_comment_status'] = Field('update_comment_status', json_schema_extra={"x-display-name": 'Update Comment Status', "x-is-trigger": False})
    commentId: str = Field(..., description="ID of the comment in Repliz, the `_id` from Get Comment. This isn't the platform's comment ID.")
    body: BodyUpdateStatusCommentDTO = Field(..., description='Request body as documented by Repliz.')

class ReplizListContactsConfig(Input):
    operation: Literal['list_contacts'] = Field('list_contacts', json_schema_extra={"x-display-name": 'List Contacts', "x-is-trigger": False})
    page: int = Field(1, ge=1, description='Page to return, starting from `1`. Contacts are sorted by the latest interaction, or by the nearest follow-up when `followUp` is set.')
    limit: int = Field(20, ge=1, le=100, description='Items per page, from `1` to `100`, for example `20`. The response says how many pages there are in `totalPages`.')
    stage: Optional[Literal['new', 'contacted', 'interested', 'won', 'lost']] = Field(None, description='Funnel stage: `new`, `contacted`, `interested`, `won`, or `lost`. Every stage when left out.')
    search: Optional[str] = Field(None, description='Matches the contact name or note, case-insensitive.')
    tag: Optional[str] = Field(None, description='Only contacts that have this tag, exactly as listed by Get Contact Tag. Every tag when left out.')
    followUp: Optional[Literal['scheduled', 'due']] = Field(None, description='`scheduled` for contacts with a follow-up, `due` for follow-ups whose time has passed. Every contact when left out.')
    accountIds: Optional[list[str]] = Field(None, description='Only contacts of these accounts, as `_id`s from Get Account. Send each one as `accountIds[]=ID`, which is what Axios does with an array. All accounts when left out.')

class ReplizGetContactConfig(Input):
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"x-display-name": 'Get Contact', "x-is-trigger": False})
    contactId: str = Field(..., description='ID of the contact, the `_id` from Get Contact.')

class BodyUpdateContactDTO(Input):
    stage: Literal['new', 'contacted', 'interested', 'won', 'lost'] = Field(..., description='Funnel stage: `new`, `contacted`, `interested`, `won`, or `lost`.')
    tags: list[str] = Field(..., description='Every tag of the contact, at most 20 of up to 30 characters. Replaces the current tags; duplicates that differ only in case are kept once.')
    note: str = Field(..., description='Free note about the contact, up to 2000 characters.')

class ReplizUpdateContactConfig(Input):
    operation: Literal['update_contact'] = Field('update_contact', json_schema_extra={"x-display-name": 'Update Contact', "x-is-trigger": False})
    contactId: str = Field(..., description='ID of the contact, the `_id` from Get Contact.')
    body: BodyUpdateContactDTO = Field(..., description='Request body as documented by Repliz.')

class BodyFollowUpContactDTO(Input):
    at: str = Field(..., description='When to follow up, as an ISO date and time in the future. Replaces the current follow-up.')
    note: str = Field(..., description='What to follow up on, up to 500 characters. Can be empty.')
    message: Optional[str] = Field(None, description='The message to send when following up, written ahead, up to 1000 characters. Repliz never sends it by itself; in the app it is sent with one click as a DM or a reply to the latest comment. Empty when left out.')

class ReplizSetContactFollowUpConfig(Input):
    operation: Literal['set_contact_follow_up'] = Field('set_contact_follow_up', json_schema_extra={"x-display-name": 'Set Contact Follow Up', "x-is-trigger": False})
    contactId: str = Field(..., description='ID of the contact, the `_id` from Get Contact.')
    body: BodyFollowUpContactDTO = Field(..., description='Request body as documented by Repliz.')

class ReplizRemoveContactFollowUpConfig(Input):
    operation: Literal['remove_contact_follow_up'] = Field('remove_contact_follow_up', json_schema_extra={"x-display-name": 'Remove Contact Follow Up', "x-is-trigger": False})
    contactId: str = Field(..., description='ID of the contact, the `_id` from Get Contact.')

class ReplizListSchedulesConfig(Input):
    operation: Literal['list_schedules'] = Field('list_schedules', json_schema_extra={"x-display-name": 'List Schedules', "x-is-trigger": False})
    page: int = Field(1, ge=1, description='Page to return, starting from `1`. Schedules are sorted by `scheduleAt`, the earliest first.')
    limit: int = Field(20, ge=1, le=100, description='Items per page, for example `20`. The response says how many pages there are in `totalPages`.')
    accountIds: Optional[list[str]] = Field(None, description='Only return items of these accounts, as `_id`s from Get Account. Send each one as `accountIds[]=ID`. All accounts when left out.')
    status: Optional[Literal['pending', 'process', 'error', 'success']] = Field(None, description='`pending` (waiting for `scheduleAt`), `process` (being published), `success` (published), or `error` (failed, the reason is in `errorMessage`). Every status when left out.')
    fromDate: Optional[str] = Field(None, description='Only schedules with `scheduleAt` from this moment, as an ISO 8601 date and time. Used only together with `toDate`.')
    toDate: Optional[str] = Field(None, description='Only schedules with `scheduleAt` up to this moment, as an ISO 8601 date and time. Used only together with `fromDate`.')

class ScheduleMedia(Input):
    alt: Optional[str] = Field(None, description='Alt text that describes the image for screen readers. Read by Instagram (`image` and `album`) and Pinterest (cut to 500 characters).')
    customThumbnail: Optional[bool] = Field(None, description='`true` makes Facebook, Instagram, TikTok, and YouTube use `thumbnail` as the video cover. Otherwise the platform picks one. Default `false`.')
    type: Literal['image', 'video'] = Field(..., description='`image` or `video`.')
    thumbnail: Optional[str] = Field(None, description='Cover image URL for a video. Facebook, Instagram, TikTok, and YouTube use it only when `customThumbnail` is `true`. WhatsApp, Telegram, and Pinterest use it whenever it is set.')
    url: str = Field(..., description='Public URL of the file. The platform downloads it when the post is published, so it has to stay reachable until then. Files in Repliz Storage work everywhere.')

class ScheduleReply(Input):
    title: Optional[str] = Field(None, description='Not used. Send `""`.')
    description: str = Field(..., description='Text of the reply. Required for `text`.')
    topic: Optional[str] = Field(None, description='Threads topic tag of the reply.')
    type: Literal['text', 'image', 'video', 'album'] = Field(..., description='`text`, `image`, `video`, or `album`.')
    medias: list[ScheduleMedia] = Field(..., description='Media objects, with the same rules as the main post. Send `[]` for `text`.')
    textAttachment: Optional[Any] = Field(None, description='Threads `text` replies. A long text attached under the reply, read like an article, with the same rules as `additionalInfo.textAttachment` of the main post. Other types and X (Twitter) ignore it.')
    delay: Optional[float] = Field(None, ge=0, le=1440, description="Minutes to wait after the post before it (the main post for the first reply) is published. `0` or left out posts it right away. It can't be less than the `delay` of the reply before it, and all `delay` values together can't exceed `1440` (24 hours).")

class BodyCreateSchedulePublicDTO(Input):
    title: Optional[str] = Field(None, description='Title of the post. Read by YouTube (video title, which YouTube needs), Facebook `video`, TikTok `image` and `album` (up to 90 characters), and Pinterest (pin title, cut to 100 characters). Other platforms ignore it, so send `""`.')
    description: str = Field(..., description='The caption, or the post text for `text`, where it is required. YouTube uses it as the video description and Pinterest as the pin description, cut to 800 characters. Shopee needs 1 to 150 characters. Not used by `story`.')
    topic: Optional[str] = Field(None, description='Threads only: the topic tag shown on the post, for example `Social Media`. Send `""` for other platforms.')
    type: Literal['text', 'image', 'video', 'reel', 'album', 'link', 'story'] = Field(..., description='The kind of post: `text`, `image`, `video`, `reel`, `album`, `link`, or `story`. It decides which `medias` are needed.')
    medias: list[ScheduleMedia] = Field(..., description='The images and videos of the post. `text` needs none, so send `[]`. `image` and `link` need 1 image, `video` and `reel` 1 video, `album` 2 or more, and `story` 1 image or video.')
    meta: Optional[Any] = Field(None, description='The shared link of a `link` post, where it is required. Other types can leave it out.')
    additionalInfo: Optional[Any] = Field(None, description='Options that only some platforms have, such as music, privacy, or the channel to post to. Required for Pinterest, which needs `additionalInfo.channel`.')
    replies: Optional[list[ScheduleReply]] = Field(None, description='Threads and X (Twitter) only: posts added under the main post as a thread, in order. Other platforms reject it with `400`, so send `[]`.')
    scheduleAt: str = Field(..., description='When to publish, as an ISO 8601 date and time with a time zone, for example `2026-06-01T12:00:00.000Z`. Due schedules are picked up every minute, so a time in the past is published within a minute.')
    templateId: Optional[str] = Field(None, description='ID of an automation template, the `_id` from Get Template. Its configuration is copied into the schedule when it is saved and set on the post after it is published. Not applied on Shopee, X (Twitter), or Pinterest.')
    accountId: str = Field(..., description='ID of the connected account to post to, the `_id` from Get Account. Its platform decides which fields are read. One schedule posts to one account, so create one for each account.')

class ReplizCreateScheduleConfig(Input):
    operation: Literal['create_schedule'] = Field('create_schedule', json_schema_extra={"x-display-name": 'Create Schedule', "x-is-trigger": False})
    body: BodyCreateSchedulePublicDTO = Field(..., description='Request body as documented by Repliz.')

class ReplizGetScheduleConfig(Input):
    operation: Literal['get_schedule'] = Field('get_schedule', json_schema_extra={"x-display-name": 'Get Schedule', "x-is-trigger": False})
    scheduleId: str = Field(..., description='ID of the schedule, the `scheduleId` returned by Create Schedule or the `_id` from Get Schedule.')

class BodyUpdateSchedulePublicDTO(Input):
    title: Optional[str] = Field(None, description='Title of the post. Read by YouTube (video title, which YouTube needs), Facebook `video`, TikTok `image` and `album` (up to 90 characters), and Pinterest (pin title, cut to 100 characters). Other platforms ignore it, so send `""`.')
    description: str = Field(..., description='The caption, or the post text for `text`, where it is required. YouTube uses it as the video description and Pinterest as the pin description, cut to 800 characters. Shopee needs 1 to 150 characters. Not used by `story`.')
    topic: Optional[str] = Field(None, description='Threads only: the topic tag shown on the post, for example `Social Media`. Send `""` for other platforms.')
    type: Literal['text', 'image', 'video', 'reel', 'album', 'link', 'story'] = Field(..., description='The kind of post: `text`, `image`, `video`, `reel`, `album`, `link`, or `story`. It decides which `medias` are needed.')
    medias: list[ScheduleMedia] = Field(..., description='The images and videos of the post. `text` needs none, so send `[]`. `image` and `link` need 1 image, `video` and `reel` 1 video, `album` 2 or more, and `story` 1 image or video.')
    meta: Optional[Any] = Field(None, description='The shared link of a `link` post, where it is required. Other types can leave it out.')
    additionalInfo: Optional[Any] = Field(None, description='Options that only some platforms have, such as music, privacy, or the channel to post to. Required for Pinterest, which needs `additionalInfo.channel`.')
    replies: Optional[list[ScheduleReply]] = Field(None, description='Threads and X (Twitter) only: posts added under the main post as a thread, in order. Other platforms reject it with `400`, so send `[]`.')
    scheduleAt: str = Field(..., description='When to publish, as an ISO 8601 date and time with a time zone, for example `2026-06-01T12:00:00.000Z`. Due schedules are picked up every minute, so a time in the past is published within a minute.')
    templateId: Optional[str] = Field(None, description='ID of an automation template, the `_id` from Get Template. Its configuration is copied into the schedule when it is saved and set on the post after it is published. Not applied on Shopee, X (Twitter), or Pinterest.')

class ReplizUpdateScheduleConfig(Input):
    operation: Literal['update_schedule'] = Field('update_schedule', json_schema_extra={"x-display-name": 'Update Schedule', "x-is-trigger": False})
    scheduleId: str = Field(..., description='ID of the schedule, the `scheduleId` returned by Create Schedule or the `_id` from Get Schedule.')
    body: BodyUpdateSchedulePublicDTO = Field(..., description='Request body as documented by Repliz.')

class ReplizDeleteScheduleConfig(Input):
    operation: Literal['delete_schedule'] = Field('delete_schedule', json_schema_extra={"x-display-name": 'Delete Schedule', "x-is-trigger": False})
    scheduleId: str = Field(..., description='ID of the schedule, the `scheduleId` returned by Create Schedule or the `_id` from Get Schedule.')

class ReplizRetryScheduleConfig(Input):
    operation: Literal['retry_schedule'] = Field('retry_schedule', json_schema_extra={"x-display-name": 'Retry Schedule', "x-is-trigger": False})
    scheduleId: str = Field(..., description='ID of the schedule, the `scheduleId` returned by Create Schedule or the `_id` from Get Schedule.')

class ReplizListChatsConfig(Input):
    operation: Literal['list_chats'] = Field('list_chats', json_schema_extra={"x-display-name": 'List Chats', "x-is-trigger": False})
    page: int = Field(1, ge=1, description='Page to return, starting from `1`. Chats with the most recent message come first.')
    limit: int = Field(20, ge=1, le=100, description='Items per page, for example `20`. The response says how many pages there are in `totalPages`.')
    status: Optional[Literal['unread', 'unreplied']] = Field(None, description='`unread`: chats with unread messages. `unreplied`: chats whose last message came from the other person. Every chat when left out.')
    accountIds: Optional[list[str]] = Field(None, description='Only return items of these accounts, as `_id`s from Get Account. Send each one as `accountIds[]=ID`. All accounts when left out.')
    search: Optional[str] = Field(None, description='Matches the name of the person or the text of the last message, case-insensitive.')

class ReplizListMessagesConfig(Input):
    operation: Literal['list_messages'] = Field('list_messages', json_schema_extra={"x-display-name": 'List Messages', "x-is-trigger": False})
    chatId: str = Field(..., description='ID of the chat, the `_id` from Get Chat.')
    page: int = Field(1, ge=1, description='Page to return, starting from `1`.')
    limit: int = Field(20, ge=1, le=100, description='Items per page, for example `20`. The response says how many pages there are in `totalPages`.')

class BodySendMessageDTO(Input):
    type: Literal['text', 'image', 'video', 'audio', 'document', 'button', 'carousel', 'quick_reply'] = Field(..., description='Message type: `text`, `image`, `video`, `audio`, `document`, `button`, `carousel`, or `quick_reply`. It decides which of the other fields is read. `button`, `carousel`, and `quick_reply` work on Facebook and Instagram only.')
    text: Optional[str] = Field(None, description='Message text, required for `text`. With `image`, `video`, or `document`, Telegram sends it as the caption.')
    replyToMessageId: Optional[str] = Field(None, description='Send this message as a reply to an earlier message in the same chat: its `messageId` from Get Message. The platform shows that message quoted above this one, and the response of Get Message has it in `quoted`. Works with every type on Facebook, Instagram, and Telegram; TikTok replies are `text` only. Not a reply when left out.')
    image: Optional[Any] = Field(None, description='The image to send, required for `image`.')
    video: Optional[Any] = Field(None, description='The video to send, required for `video`.')
    audio: Optional[Any] = Field(None, description='The audio file to send, required for `audio`.')
    document: Optional[Any] = Field(None, description='The file to send, required for `document`.')
    button: Optional[Any] = Field(None, description='The text and its buttons, required for `button`. The text goes in `button.text`, not in `text`.')
    carousel: Optional[Any] = Field(None, description='The cards to send, required for `carousel`.')
    quickReply: Optional[Any] = Field(None, description='The text and its quick replies, required for `quick_reply`. The text goes in `quickReply.text`, not in `text`.')

class ReplizSendMessageConfig(Input):
    operation: Literal['send_message'] = Field('send_message', json_schema_extra={"x-display-name": 'Send Message', "x-is-trigger": False})
    chatId: str = Field(..., description='ID of the chat, the `_id` from Get Chat.')
    body: BodySendMessageDTO = Field(..., description='Request body as documented by Repliz.')

class ReplizNewCommentConfig(PollTriggerConfigBase):
    """Poll the newest 100 comments per tick. Use a short interval for busy accounts."""
    operation: Literal["on_new_comment"] = Field("on_new_comment", json_schema_extra={"x-is-trigger": True, "x-display-name": "On New Comment"})
    accountIds: Optional[list[str]] = Field(None, description="Account IDs to monitor; all accounts if omitted.")

ReplizOperation = Annotated[Union[ReplizListAccountsConfig, ReplizGetAccountConfig, ReplizCountAccountsConfig, ReplizListAccountTagsConfig, ReplizUpdateAccountTagsConfig, ReplizListCommentsConfig, ReplizGetCommentConfig, ReplizReplyCommentConfig, ReplizDeleteCommentConfig, ReplizUpdateCommentStatusConfig, ReplizListContactsConfig, ReplizGetContactConfig, ReplizUpdateContactConfig, ReplizSetContactFollowUpConfig, ReplizRemoveContactFollowUpConfig, ReplizListSchedulesConfig, ReplizCreateScheduleConfig, ReplizGetScheduleConfig, ReplizUpdateScheduleConfig, ReplizDeleteScheduleConfig, ReplizRetryScheduleConfig, ReplizListChatsConfig, ReplizListMessagesConfig, ReplizSendMessageConfig, ReplizNewCommentConfig], Field(discriminator="operation")]

class ReplizNodeConfig(NodeConfig[ReplizOperation, ReplizCredential]):
    pass

OPERATIONS = {'list_accounts': {'method': 'GET', 'path': '/public/account', 'parameters': [('page', 'query', 'number'), ('limit', 'query', 'number'), ('types', 'query', 'array'), ('search', 'query', 'string'), ('status', 'query', 'string'), ('tags', 'query', 'array')], 'body': False}, 'get_account': {'method': 'GET', 'path': '/public/account/{accountId}', 'parameters': [('accountId', 'path', 'string')], 'body': False}, 'count_accounts': {'method': 'GET', 'path': '/public/account/count', 'parameters': [], 'body': False}, 'list_account_tags': {'method': 'GET', 'path': '/public/account/tag', 'parameters': [], 'body': False}, 'update_account_tags': {'method': 'PUT', 'path': '/public/account/{accountId}/tag', 'parameters': [('accountId', 'path', 'string')], 'body': True}, 'list_comments': {'method': 'GET', 'path': '/public/comment', 'parameters': [('page', 'query', 'number'), ('limit', 'query', 'number'), ('status', 'query', 'string'), ('accountIds', 'query', 'array'), ('search', 'query', 'string')], 'body': False}, 'get_comment': {'method': 'GET', 'path': '/public/comment/{commentId}', 'parameters': [('commentId', 'path', 'string')], 'body': False}, 'reply_comment': {'method': 'POST', 'path': '/public/comment/{commentId}', 'parameters': [('commentId', 'path', 'string')], 'body': True}, 'delete_comment': {'method': 'DELETE', 'path': '/public/comment/{commentId}', 'parameters': [('commentId', 'path', 'string')], 'body': False}, 'update_comment_status': {'method': 'PUT', 'path': '/public/comment/{commentId}/status', 'parameters': [('commentId', 'path', 'string')], 'body': True}, 'list_contacts': {'method': 'GET', 'path': '/public/contact', 'parameters': [('page', 'query', 'number'), ('limit', 'query', 'number'), ('stage', 'query', 'string'), ('search', 'query', 'string'), ('tag', 'query', 'string'), ('followUp', 'query', 'string'), ('accountIds', 'query', 'array')], 'body': False}, 'get_contact': {'method': 'GET', 'path': '/public/contact/{contactId}', 'parameters': [('contactId', 'path', 'string')], 'body': False}, 'update_contact': {'method': 'PUT', 'path': '/public/contact/{contactId}', 'parameters': [('contactId', 'path', 'string')], 'body': True}, 'set_contact_follow_up': {'method': 'PUT', 'path': '/public/contact/{contactId}/follow-up', 'parameters': [('contactId', 'path', 'string')], 'body': True}, 'remove_contact_follow_up': {'method': 'DELETE', 'path': '/public/contact/{contactId}/follow-up', 'parameters': [('contactId', 'path', 'string')], 'body': False}, 'list_schedules': {'method': 'GET', 'path': '/public/schedule', 'parameters': [('page', 'query', 'number'), ('limit', 'query', 'number'), ('accountIds', 'query', 'array'), ('status', 'query', 'string'), ('fromDate', 'query', 'string'), ('toDate', 'query', 'string')], 'body': False}, 'create_schedule': {'method': 'POST', 'path': '/public/schedule', 'parameters': [], 'body': True}, 'get_schedule': {'method': 'GET', 'path': '/public/schedule/{scheduleId}', 'parameters': [('scheduleId', 'path', 'string')], 'body': False}, 'update_schedule': {'method': 'PUT', 'path': '/public/schedule/{scheduleId}', 'parameters': [('scheduleId', 'path', 'string')], 'body': True}, 'delete_schedule': {'method': 'DELETE', 'path': '/public/schedule/{scheduleId}', 'parameters': [('scheduleId', 'path', 'string')], 'body': False}, 'retry_schedule': {'method': 'PUT', 'path': '/public/schedule/{scheduleId}/retry', 'parameters': [('scheduleId', 'path', 'string')], 'body': False}, 'list_chats': {'method': 'GET', 'path': '/public/chat', 'parameters': [('page', 'query', 'number'), ('limit', 'query', 'number'), ('status', 'query', 'string'), ('accountIds', 'query', 'array'), ('search', 'query', 'string')], 'body': False}, 'list_messages': {'method': 'GET', 'path': '/public/chat/{chatId}/message', 'parameters': [('chatId', 'path', 'string'), ('page', 'query', 'number'), ('limit', 'query', 'number')], 'body': False}, 'send_message': {'method': 'POST', 'path': '/public/chat/{chatId}/message', 'parameters': [('chatId', 'path', 'string')], 'body': True}}

class ReplizNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-repliz"
    connection_evidence = ConnectionEvidence(operation="list_accounts", noun="social accounts")

    @classmethod
    def get_config_model(cls):
        return ReplizNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your Repliz API keys")
        auth = httpx.BasicAuth(credential.access_key, credential.secret_key)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, "https://api.repliz.com" + path, auth=auth, params=params, **({"json": body} if body is not None else {}))
            response.raise_for_status()
            return response.json() if response.content else {}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("comments")) if config.get("operation") == "on_new_comment" else True

    @classmethod
    def resolve_agent_event(cls, output):
        if "comments" not in output:
            return super().resolve_agent_event(output)
        comments = output["comments"]
        if not comments:
            return None
        lines = [f"{c['comment']['owner']['name']} commented: {c['comment']['text']} (comment {c['_id']}, account {c['accountId']}, post {c['content']['url']})" for c in comments]
        return {"text": "Repliz new comments:\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        if config.operation == "on_new_comment":
            # Monitor the newest 100 comments, as ordered by the provider.
            params = [("page", 1), ("limit", 100)]
            params += [("accountIds[]", value) for value in (config.accountIds or [])]
            response = await self._request("GET", "/public/comment", params=params)
            comments = response["docs"]
            fresh = await self._filter_unseen(comments, lambda c: c["_id"])
            return {"comments": fresh, "new_comment_count": len(fresh)}
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, mode="json")
        path = spec["path"]
        params = []
        for name, location, kind in spec["parameters"]:
            if name not in values:
                continue
            value = values[name]
            if location == "path":
                path = path.replace("{" + name + "}", quote(str(value), safe=""))
            elif kind == "array":
                params.extend((name + "[]", item) for item in value)
            else:
                params.append((name, value))
        return await self._request(spec["method"], path, params=params, body=values.get("body"))

