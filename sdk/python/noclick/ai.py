"""AI: models paid from your NoClick balance, for code that isn't an agent, and
your agents as models.

    reply = noclick.AI.chat("Summarize this in one line: ...")
    vectors = noclick.AI.embed(["first", "second"]).vectors
    image = noclick.AI.image("A lighthouse at dusk, watercolor")
    clip = noclick.AI.video("Waves rolling under a lighthouse at dusk").wait()
    words = noclick.AI.transcribe("https://example.com/call.mp3")
    answer = noclick.AI.chat("Where's my refund?", model="agent:support")

Every call is charged in US dollars to your account; inside ``as_user`` it is
attributed to that user and counts against its spend cap. ``AI.base_url``
serves chat completions, responses, embeddings and the model list to any
OpenAI client.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Literal, Optional, Sequence, Union, overload

from ._client import USER_HEADER, Client, default_client, resolve_client
from ._object import compact, parse_time
from ._sync import synced
from ._scope import AMBIENT, resolve_scope, user_ref
from .operation import Operation, register_result

# Seconds a call may take before the client gives up (a large image, a long recording).
_IMAGE_TIMEOUT_S = 180
_TRANSCRIBE_TIMEOUT_S = 180


def _message(content: Any) -> Dict[str, Any]:
    return content if isinstance(content, dict) else {"role": "user", "content": content}


def _assembled(chunks: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """A streamed chat completion as the whole completion it adds up to."""
    text: List[str] = []
    thought: List[str] = []
    calls: Dict[int, Dict[str, Any]] = {}
    head: Dict[str, Any] = {}
    finish, usage, extra = None, None, {}
    for chunk in chunks:
        head = {k: chunk[k] for k in ("id", "created", "model") if chunk.get(k) is not None} or head
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            text.append(delta.get("content") or "")
            thought.append(delta.get("reasoning") or "")
            for call in delta.get("tool_calls") or []:
                slot = calls.setdefault(call.get("index", 0), {"id": None, "type": "function",
                                                               "function": {"name": "", "arguments": ""}})
                slot["id"] = call.get("id") or slot["id"]
                function = call.get("function") or {}
                slot["function"]["name"] += function.get("name") or ""
                slot["function"]["arguments"] += function.get("arguments") or ""
            finish = choice.get("finish_reason") or finish
        usage = chunk.get("usage") or usage
        extra.update({k: chunk[k] for k in ("cost_usd", "metadata", "noclick") if k in chunk})
    content = "".join(text)
    message: Dict[str, Any] = {"role": "assistant", "content": content if content or not calls else None}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    if "".join(thought):
        message["reasoning"] = "".join(thought)
    return {**head, "object": "chat.completion", "usage": usage,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}], **extra}


@dataclass(frozen=True)
class ChatReply:
    """A model's (or an agent's) answer: ``text``, and the whole ``message`` to
    append to the conversation."""

    #: The answer as text (empty when the model only called tools).
    text: str
    #: The assistant message as the API sent it (``role``, ``content``, ``tool_calls``).
    message: Dict[str, Any]
    model: Optional[str]
    #: Why the model stopped: ``stop``, ``length`` (``max_tokens`` reached, reasoning included: a model that
    #: spends them all reasoning answers with an empty ``text``) or ``tool_calls``.
    finish_reason: Optional[str]
    #: Tokens used: ``prompt_tokens``, ``completion_tokens``, ``total_tokens``, and ``reasoning_tokens``, the part of
    #: ``completion_tokens`` spent reasoning, where the model reports it (none for an agent).
    usage: Dict[str, int]
    #: What the call cost, in US dollars.
    cost_usd: Optional[float]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "ChatReply":
        raw = raw if isinstance(raw, dict) else {}
        choice = (raw.get("choices") or [{}])[0]
        message = dict(choice.get("message") or {})
        usage = dict(raw.get("usage") or {})
        reasoned = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        if isinstance(reasoned, int):
            usage["reasoning_tokens"] = reasoned
        return cls(
            message.get("content") or "", message, raw.get("model"), choice.get("finish_reason"), usage,
            raw.get("cost_usd"), raw,
        )

    @property
    def reasoning(self) -> Optional[str]:
        """What the model thought before it answered, where its provider returns it (None otherwise). Reasoning
        counts toward ``max_tokens``: ``usage["reasoning_tokens"]`` says how much of them it took."""
        return self.message.get("reasoning") or None

    @property
    def tool_calls(self) -> List[Dict[str, Any]]:
        """The tools the model asked to call (empty if none), in the OpenAI shape ``toolkit.handle_openai`` runs.
        An agent runs its own tools, so its reply never has any."""
        return list(self.message.get("tool_calls") or [])

    @property
    def conversation(self) -> Optional[str]:
        """An agent's conversation this reply is part of: pass it as ``conversation=`` to continue it."""
        return (self.raw.get("metadata") or {}).get("conversation")

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class Embeddings:
    """One vector per input, in the order you passed them."""

    vectors: List[List[float]]
    #: The length of each vector.
    dimensions: int
    model: Optional[str]
    #: Tokens used: ``prompt_tokens``, ``total_tokens``.
    usage: Dict[str, int]
    #: What the call cost, in US dollars.
    cost_usd: Optional[float]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Embeddings":
        raw = raw if isinstance(raw, dict) else {}
        rows = sorted(raw.get("data") or [], key=lambda row: row.get("index", 0))
        vectors = [list(row.get("embedding") or []) for row in rows]
        return cls(
            vectors, len(vectors[0]) if vectors else 0, raw.get("model"), dict(raw.get("usage") or {}),
            raw.get("cost_usd"), raw,
        )


@dataclass(frozen=True)
class GeneratedImage:
    """An image a model made, kept as one of your account's files."""

    #: A link to the image that keeps working.
    url: str
    width: Optional[int]
    height: Optional[int]
    model: Optional[str]
    #: What the image cost, in US dollars.
    cost_usd: Optional[float]
    #: When ``url`` stops working: ``None``, since the file is kept.
    expires_at: Any
    #: The file in your account's files.
    file_id: Optional[str] = None
    raw: Dict[str, Any] = dc_field(default_factory=dict, repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "GeneratedImage":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("url"), raw.get("width"), raw.get("height"), raw.get("model"), raw.get("cost_usd"),
            parse_time(raw.get("expires_at")), raw.get("file_id"), raw,
        )


@dataclass(frozen=True)
class GeneratedVideo:
    """A video a model made, kept as one of your account's files."""

    #: A link to the video that keeps working.
    url: str
    #: The file in your account's files.
    file_id: Optional[str]
    mime_type: Optional[str]
    seconds: Optional[int]
    resolution: Optional[str]
    model: Optional[str]
    #: What the video cost, in US dollars.
    cost_usd: Optional[float]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "GeneratedVideo":
        raw = raw if isinstance(raw, dict) else {}
        return cls(
            raw.get("url"), raw.get("file_id"), raw.get("mime_type"), raw.get("seconds"), raw.get("resolution"),
            raw.get("model"), raw.get("cost_usd"), raw,
        )


register_result("ai.video", lambda raw, op: GeneratedVideo._from(raw))


@dataclass(frozen=True)
class TranscriptSegment:
    """A stretch of speech: what was said between ``start_s`` and ``end_s``, and by
    whom when you asked for ``speakers``."""

    start_s: float
    end_s: float
    text: str
    #: Who said it: one of the names you gave ``speakers``, or ``speaker_1``, ``speaker_2``, ... in the
    #: order the voices first speak (None unless you asked).
    speaker: Optional[str] = None


@dataclass(frozen=True)
class Transcript:
    """What was said in a recording, as one ``text`` and as timed ``segments``."""

    text: str
    #: The spoken language as an ISO 639-1 code (``en``), detected unless you passed one; ISO 639-3
    #: (``yue``) for a language with no two-letter code.
    language: Optional[str]
    duration_s: Optional[float]
    segments: List[TranscriptSegment]
    model: Optional[str]
    #: What the transcription cost, in US dollars.
    cost_usd: Optional[float]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "Transcript":
        raw = raw if isinstance(raw, dict) else {}
        segments = [
            TranscriptSegment(row.get("start_s"), row.get("end_s"), row.get("text") or "", row.get("speaker"))
            for row in raw.get("segments") or []
        ]
        return cls(
            raw.get("text") or "", raw.get("language"), raw.get("duration_s"), segments, raw.get("model"),
            raw.get("cost_usd"), raw,
        )

    def __str__(self) -> str:
        return self.text


register_result("ai.transcription", lambda raw, op: Transcript._from(raw))


@dataclass(frozen=True)
class AIModel:
    """A model you can call, and what it costs in US dollars (its provider's
    own price). Only the prices for its ``kind`` are set: per token for
    ``chat`` and ``embedding`` models, per token of the image an ``image`` model
    makes, per minute of audio for ``transcription`` ones, per second for
    ``video`` ones, and none for an
    ``agent``, whose turns cost what its model and tools do."""

    #: The id to pass as ``model=``, like ``openrouter/anthropic/claude-sonnet-4.6`` or ``agent:support``.
    id: str
    name: Optional[str]
    #: ``chat``, ``embedding``, ``image``, ``transcription`` or ``agent``.
    kind: str
    #: The most tokens a request can hold (chat and embedding models).
    context_length: Optional[int]
    input_usd_per_token: Optional[float]
    output_usd_per_token: Optional[float]
    usd_per_minute: Optional[float]
    #: What a minute of audio costs with ``speakers``; None for a model of another kind.
    usd_per_minute_with_speakers: Optional[float]
    #: What a second of video costs, for the clip a call naming no length or resolution makes.
    usd_per_second: Optional[float]
    #: The request fields a chat model takes, as its provider lists them (``tools``, ``tool_choice``,
    #: ``reasoning_effort``, ``temperature``, ...): one it doesn't list has no effect. None for other kinds.
    parameters: Optional[List[str]]
    #: How a chat model reasons; None for one that doesn't.
    reasoning: Optional["AIReasoning"]
    #: The frames a video model can start or end on a picture (``first_frame``, ``last_frame``): one listing
    #: ``first_frame`` takes ``AI.video(first_frame=...)``. None for other kinds.
    frame_images: Optional[List[str]]
    raw: Dict[str, Any] = dc_field(repr=False)

    @classmethod
    def _from(cls, raw: Any) -> "AIModel":
        raw = raw if isinstance(raw, dict) else {}
        parameters, reasoning, frames = raw.get("parameters"), raw.get("reasoning"), raw.get("frame_images")
        return cls(
            raw.get("id"), raw.get("name"), raw.get("kind"), raw.get("context_length"),
            raw.get("input_usd_per_token"), raw.get("output_usd_per_token"), raw.get("usd_per_minute"),
            raw.get("usd_per_minute_with_speakers"), raw.get("usd_per_second"),
            list(parameters) if isinstance(parameters, list) else None,
            AIReasoning._from(reasoning) if isinstance(reasoning, dict) else None,
            list(frames) if isinstance(frames, list) else None, raw,
        )


@dataclass(frozen=True)
class AIReasoning:
    """How a chat model reasons before it answers. Its reasoning counts toward ``max_tokens``, so a short
    budget can go entirely on reasoning and leave the answer empty (``finish_reason`` ``length``)."""

    #: It always reasons, whatever ``reasoning_effort`` says. Anthropic's models refuse a forced tool
    #: (``tool_choice`` ``required`` or naming a function) while they reason, so on one of theirs that
    #: always does, only ``auto`` and ``none`` work.
    mandatory: bool
    #: The ``reasoning_effort`` values it takes (``none`` among them where it can stop reasoning).
    efforts: List[str]
    #: Its effort when a call names none.
    default_effort: Optional[str]

    @classmethod
    def _from(cls, raw: Dict[str, Any]) -> "AIReasoning":
        return cls(bool(raw.get("mandatory")), list(raw.get("efforts") or []), raw.get("default_effort"))


class _BaseUrl:
    def __get__(self, obj: Any, owner: Any) -> str:
        return f"{default_client().base_url}/v1/ai"


class AI:
    """Models paid from your NoClick balance, for code that isn't an agent: chat,
    embeddings, images, videos and transcription; and your agents as ``agent:<name>``
    models. Model ids are OpenRouter ids with the ``openrouter/`` prefix, except
    transcription's, NoClick's own ``noclick/transcribe-1``; leave ``model`` out for
    NoClick's default of each kind."""

    #: The OpenAI-compatible endpoint (``https://api.noclick.com/v1/ai`` on the hosted API): point any OpenAI client
    #: at it with your NoClick key for chat completions, responses, embeddings and the model list.
    base_url: str = _BaseUrl()

    @synced
    @classmethod
    async def chat(
        cls,
        messages: Union[str, Sequence[Any]],
        *,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        response_format: Optional[Dict[str, Any]] = None,
        tools: Optional[Sequence[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        reasoning_effort: Optional[str] = None,
        conversation: Optional[str] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> ChatReply:
        """Send a conversation to a chat model: a list of ``{"role", "content"}``
        messages, or a string as one user message. ``response_format`` asks for JSON
        (``{"type": "json_schema", "json_schema": ...}``); ``tools`` are OpenAI-format
        tool definitions, such as ``toolkit.definitions("openai")``, and ``tool_choice``
        says which the model calls: ``auto`` (its choice), ``none``, ``required`` (one of
        them), or one by name (``{"type": "function", "function": {"name": "submit"}}``).

        ``reasoning_effort`` sets how hard a model that reasons thinks first, among its
        ``reasoning.efforts`` in ``AI.models``: its reasoning counts toward ``max_tokens``,
        so a lower effort leaves more of them for the answer, and ``none`` turns it off
        where the model can stop. A field the model doesn't list in its ``parameters`` has
        no effect.

        ``model="agent:<name>"`` talks to one of your agents instead, which brings its
        own tools (so ``tools`` is refused) and keeps the conversation: pass
        ``conversation=reply.conversation`` to continue it, and only the messages after
        the last assistant message are sent. The answer streams, so a long turn never
        times out. A request with no conversation whose messages end in an assistant
        reply the agent gave recently continues that reply's conversation (in the same
        user), so a chat UI that resends the whole history keeps one thread (invite-only
        beta).

        Returns:
            The answer: its ``text``, the ``message`` to append to the conversation, and
            the tokens it used and what it cost.

        Usage:
            Ask for one answer::

                reply = noclick.AI.chat(
                    [
                        {"role": "system", "content": "You write one-line summaries."},
                        {"role": "user", "content": "Summarize: the meeting moved to Friday at 3pm."},
                    ],
                    model="openrouter/anthropic/claude-sonnet-4.6",
                    max_tokens=200,
                )
                print(reply.text, reply.cost_usd)

            Let the model use your users' connections, with a ``Toolkit``::

                toolkit = noclick.Toolkit(["gmail", "search"])
                messages = [{"role": "user", "content": "Summarize the emails Ana sent me this week"}]
                with noclick.as_user("user_42"):
                    while True:
                        reply = noclick.AI.chat(messages, tools=toolkit.definitions("openai"))
                        messages.append(reply.message)
                        if not reply.tool_calls:
                            break
                        messages += toolkit.handle_openai(reply.message)
                print(reply.text)

            Talk to one of your agents, then keep going in its conversation::

                reply = noclick.AI.chat("Where's my refund?", model="agent:support")
                follow_up = noclick.AI.chat("And how long will it take?", model="agent:support",
                                            conversation=reply.conversation)
                print(follow_up.text)
        """
        sent = [_message(messages)] if isinstance(messages, str) else [_message(m) for m in messages]
        body = compact(
            model=model, messages=sent, max_tokens=max_tokens, temperature=temperature,
            response_format=response_format, tools=list(tools) if tools is not None else None,
            tool_choice=tool_choice, reasoning_effort=reasoning_effort,
            metadata={"conversation": conversation} if conversation else None,
            stream=True, stream_options={"include_usage": True},
        )
        events = resolve_client(client)._events("POST", "/v1/ai/chat/completions", json=body, user=resolve_scope(user))
        return ChatReply._from(_assembled([data async for _, data in events]))

    @synced
    @classmethod
    async def embed(
        cls,
        texts: Union[str, Sequence[str]],
        *,
        model: Optional[str] = None,
        dimensions: Optional[int] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> Embeddings:
        """Turn text into vectors for search and clustering: one string, or a list of
        up to 2,048. ``dimensions`` shortens the vectors, for models that allow it.

        Returns:
            One vector per text, in order, with their length and what the call cost.

        Usage::

            docs = ["Refunds take 5 days.", "We ship worldwide.", "Support is open 9 to 5."]
            result = noclick.AI.embed(docs, model="openrouter/openai/text-embedding-3-small")
            print(result.dimensions, len(result.vectors))   # 1536 3

            [query] = noclick.AI.embed("How long do refunds take?", model="openrouter/openai/text-embedding-3-small").vectors
        """
        inputs = [texts] if isinstance(texts, str) else list(texts)
        raw = await resolve_client(client).request(
            "POST", "/v1/ai/embeddings", json=compact(model=model, input=inputs, dimensions=dimensions),
            user=resolve_scope(user),
        )
        return Embeddings._from(raw)

    @synced
    @classmethod
    async def image(
        cls,
        prompt: str,
        *,
        model: Optional[str] = None,
        size: Optional[str] = None,
        images: Optional[Sequence[str]] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> GeneratedImage:
        """Make one image from ``prompt``; ``size`` is ``"WIDTHxHEIGHT"`` in an aspect
        ratio the model makes (the model's own shape unless you say). ``images`` are pictures
        (URLs, up to 8) to make it from: one to edit, the prompt saying what to change, or
        several to combine.

        Returns:
            The image, kept as one of your account's files: a ``url`` that keeps working, its
            ``file_id``, its size and what it cost.

        Usage::

            image = noclick.AI.image("A lighthouse at dusk, watercolor", size="1024x1536")
            print(image.url, image.width, image.height, image.cost_usd)
            night = noclick.AI.image("Make it night", images=[image.url])
        """
        raw = await resolve_client(client).request(
            "POST", "/v1/ai/images", json=compact(prompt=prompt, model=model, size=size,
                                                  images=list(images) if images else None),
            user=resolve_scope(user), timeout=_IMAGE_TIMEOUT_S,
        )
        return GeneratedImage._from(raw)

    @synced
    @classmethod
    async def video(
        cls,
        prompt: str,
        *,
        model: Optional[str] = None,
        seconds: Optional[int] = None,
        resolution: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        audio: bool = True,
        first_frame: Optional[str] = None,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> Operation:
        """Start one video from ``prompt``. It takes minutes, so it runs as an operation.
        ``seconds``, ``resolution`` (``720p``, ``1080p``) and ``aspect_ratio`` (``16:9``,
        ``9:16``) are among the ones the model makes; left out, about 8 seconds at 720p.
        ``audio`` adds sound where the model makes it. ``first_frame`` is a picture the video
        starts from, to bring a photo to life: one of your account's files by its id, or a
        JPEG, PNG or WebP image's https URL, up to 10 MB, on a model whose ``frame_images``
        list ``first_frame`` (``AI.models(kind="video")``). Its price is quoted before it starts
        (``usd_per_second`` in ``AI.models(kind="video")``) and charged when it's done.

        Returns:
            An ``Operation`` at once, whose ``wait()`` gives the ``GeneratedVideo``, kept as one
            of your account's files.

        Usage::

            job = noclick.AI.video("Waves rolling under a lighthouse at dusk", seconds=8, aspect_ratio="9:16")
            clip = job.wait(timeout=600)
            print(clip.url, clip.seconds, clip.cost_usd)
            waving = noclick.AI.video("She turns and waves", first_frame="https://example.com/me.jpg").wait()
        """
        scope = resolve_scope(user)
        raw = await resolve_client(client).request(
            "POST", "/v1/ai/videos", json=compact(prompt=prompt, model=model, seconds=seconds, resolution=resolution,
                                                  aspect_ratio=aspect_ratio, audio=audio, first_frame=first_frame),
            user=scope,
        )
        return Operation._from_payload(raw, client=client, user=scope, kind="ai.video")

    @overload
    @classmethod
    async def transcribe(
        cls, audio: Union[str, bytes], *, model: Optional[str] = None, language: Optional[str] = None,
        speakers: Union[bool, Sequence[str]] = False, background: Literal[False] = False, user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> Transcript: ...

    @overload
    @classmethod
    async def transcribe(
        cls, audio: Union[str, bytes], *, model: Optional[str] = None, language: Optional[str] = None,
        speakers: Union[bool, Sequence[str]] = False, background: Literal[True], user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> Operation: ...

    @synced
    @classmethod
    async def transcribe(
        cls,
        audio: Union[str, bytes],
        *,
        model: Optional[str] = None,
        language: Optional[str] = None,
        speakers: Union[bool, Sequence[str]] = False,
        background: bool = False,
        user: Any = AMBIENT,
        client: Optional[Client] = None,
    ) -> Union[Transcript, Operation]:
        """Write down what is said in a recording: an ``https`` URL to it, or its bytes,
        up to 2 hours (25 MB as bytes, 200 MB behind a URL), in MP3, WAV, M4A, MP4, OGG, WebM,
        AAC, FLAC or AIFF. ``language`` (an ISO 639-1 code) skips detection. It runs on
        ``noclick/transcribe-1``, which takes the whole recording in one call and gives a segment
        per sentence, priced per minute of audio as ``usd_per_minute`` in ``AI.models``.

        ``speakers`` tells the voices apart, at the same price, each voice keeping its label from
        start to end, and gives a segment per voice's turn. ``True`` labels each segment's
        ``speaker`` ``speaker_1``, ``speaker_2`` and on, in the order they first speak. A list of
        names (``["rep", "customer"]``) says how many voices there are, and NoClick works out
        which is which from what they say (a rep introduces the company, say); a voice it can't
        tell takes the next unused name in speaking order.

        ``background=True`` returns an ``Operation`` at once: for a recording that may take
        longer than one request waits (90 seconds), as a very long one can (forty minutes usually
        take about 20 seconds). A call that doesn't run in the background and passes 90 seconds
        raises ``RequestTimeout`` naming its operation, which still finishes, is charged, and
        holds the transcript.

        Returns:
            The transcript: its ``text``, timed ``segments``, the ``language`` and how long the audio
            was. With ``background=True``, an ``Operation`` at once, whose ``wait()`` gives it.

        Usage:
            From a URL::

                words = noclick.AI.transcribe("https://example.com/calls/2026-09-26.mp3")
                print(words.language, words.duration_s)
                print(words.text)

            From a file you have::

                with open("voicemail.m4a", "rb") as f:
                    words = noclick.AI.transcribe(f.read(), language="en")
                for segment in words.segments:
                    print(f"{segment.start_s:6.1f}s  {segment.text}")

            Who said what on a sales call::

                call = noclick.AI.transcribe("https://example.com/calls/demo.mp3", speakers=["rep", "customer"])
                for segment in call.segments:
                    print(segment.speaker, segment.text)

            A two-hour meeting, in the background::

                job = noclick.AI.transcribe("https://example.com/meetings/all-hands.mp3", speakers=True,
                                            background=True)
                meeting = job.wait()
                print(len(meeting.segments), meeting.cost_usd)
        """
        if isinstance(speakers, str):
            raise TypeError("speakers is True or a list of names, like ['rep', 'customer']")
        who = (True if speakers else None) if isinstance(speakers, bool) else list(speakers)
        scope = resolve_scope(user)
        api = resolve_client(client)
        if isinstance(audio, str):
            raw = await api.request(
                "POST", "/v1/ai/transcriptions",
                json=compact(url=audio, model=model, language=language, speakers=who, background=background or None),
                user=scope, timeout=_TRANSCRIBE_TIMEOUT_S,
            )
        else:
            params = {"model": model, "language": language,
                      "speakers": None if who is None else ("true" if who is True else ",".join(who)),
                      "background": "true" if background else None}
            raw = await api.request(
                "POST", "/v1/ai/transcriptions", content=bytes(audio), params=params,
                user=scope, timeout=_TRANSCRIBE_TIMEOUT_S,
            )
        if background:
            return Operation._from_payload(raw, client=client, user=scope, kind="ai.transcription")
        return Transcript._from(raw)

    @synced
    @classmethod
    async def headers(cls, *, user: Any = AMBIENT, client: Optional[Client] = None) -> Dict[str, str]:
        """The headers a call to ``AI.base_url`` needs: your key as the bearer and, inside
        ``as_user`` (or with ``user=``), the ``NoClick-User`` that attributes the call to
        that user and holds it to the user's spend cap. Give them to an OpenAI client as
        ``default_headers``; without the user header the account pays and no user's cap
        applies. A client from a user session gets the session's token.

        Returns:
            ``Authorization`` and, when a user is in scope, ``NoClick-User``.

        Usage:
            One OpenAI client per user, talking to that user's agent::

                from openai import OpenAI

                with noclick.as_user("user_42"):
                    headers = noclick.AI.headers()   # the key rides in these, so api_key is a placeholder
                gpt = OpenAI(base_url=noclick.AI.base_url, api_key="-", default_headers=headers)
                reply = gpt.chat.completions.create(model="agent:assistant", messages=[{"role": "user", "content": "Hi"}])
        """
        api = resolve_client(client)
        headers = {"Authorization": f"Bearer {await api._bearer(api.timeout)}"}
        user_id = await user_ref(resolve_scope(user))
        if user_id:
            headers[USER_HEADER] = user_id
        return headers

    @synced
    @classmethod
    async def models(
        cls, *, kind: Optional[str] = None, q: Optional[str] = None, model: Optional[str] = None,
        user: Any = AMBIENT, client: Optional[Client] = None,
    ) -> List[AIModel]:
        """The models you can call (``kind``: ``chat``, ``embedding``, ``image``,
        ``transcription``, ``video`` or ``agent``); ``agent`` lists the agents you (or the user
        you act for) can talk to as ``agent:<name>``. ``q`` keeps those whose id or name contains
        it (any case), ``model`` the one with that id (``openrouter/`` may be left out).

        Returns:
            Every matching model with its prices in US dollars, the default of each kind first.

        Usage::

            for m in noclick.AI.models(kind="chat"):
                print(m.id, m.context_length, m.input_usd_per_token, m.output_usd_per_token)
            [sonnet] = noclick.AI.models(model="anthropic/claude-sonnet-4.6")
        """
        raw = await resolve_client(client).request(
            "GET", "/v1/ai/models", params={"kind": kind, "q": q, "model": model}, user=resolve_scope(user)) or {}
        return [AIModel._from(row) for row in raw.get("data") or []]
