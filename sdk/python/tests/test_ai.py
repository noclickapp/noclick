"""noclick.AI against a mocked API: chat streams from /v1/ai/chat/completions
and adds up to one reply (tool calls, usage, cost, an agent's conversation),
errors in OpenAI's envelope raise the matching noclick error, and the other
calls send what the API takes."""

import json
from datetime import datetime, timezone

import httpx
import pytest

import noclick as nc
from platform_helpers import body, listing

MODEL = "openrouter/anthropic/claude-sonnet-4.6"


def stream(*chunks, head=": keepalive\n\n"):
    text = head + "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=text.encode())


def chunk(delta=None, finish=None, **extra):
    return {"id": "gen_1", "object": "chat.completion.chunk", "created": 1790000000, "model": MODEL,
            "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}], **extra}


USAGE = {"id": "gen_1", "object": "chat.completion.chunk", "model": MODEL, "choices": [],
         "usage": {"prompt_tokens": 24, "completion_tokens": 7, "total_tokens": 31}, "cost_usd": 0.00018}


def test_chat_streams_and_adds_up_to_one_reply(api, client):
    route = api.post("/v1/ai/chat/completions").mock(return_value=stream(
        chunk({"role": "assistant", "content": ""}), chunk({"content": "Moved to Friday, "}), chunk({"content": "3pm."}),
        chunk(finish="stop"), USAGE))
    with nc.as_user("user_42"):
        reply = nc.AI.chat("Summarize: the meeting moved to Friday at 3pm.", model=MODEL, max_tokens=200,
                           temperature=0.2)
    request = route.calls.last.request
    assert body(request) == {
        "model": MODEL, "max_tokens": 200, "temperature": 0.2, "stream": True, "stream_options": {"include_usage": True},
        "messages": [{"role": "user", "content": "Summarize: the meeting moved to Friday at 3pm."}],
    }
    assert request.headers["NoClick-User"] == "user_42" and request.headers["Accept"] == "text/event-stream"
    assert (reply.text, str(reply), reply.finish_reason, reply.cost_usd) == ("Moved to Friday, 3pm.",) * 2 + ("stop", 0.00018)
    assert reply.usage["total_tokens"] == 31 and reply.tool_calls == [] and reply.model == MODEL
    assert reply.message == {"role": "assistant", "content": "Moved to Friday, 3pm."} and reply.conversation is None

    nc.AI.chat([{"role": "system", "content": "Be brief."}, "Hi"], response_format={"type": "json_object"})
    assert body(route.calls.last.request) == {
        "messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}],
        "response_format": {"type": "json_object"}, "stream": True, "stream_options": {"include_usage": True},
    }


def test_streamed_tool_calls_add_up_and_feed_a_toolkit(api, client):
    parts = [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "search", "arguments": ""}},
             {"index": 0, "function": {"arguments": '{"query": '}}, {"index": 0, "function": {"arguments": '"refunds"}'}}]
    api.post("/v1/ai/chat/completions").mock(return_value=stream(
        *[chunk({"tool_calls": [p]}) for p in parts], chunk(finish="tool_calls"), USAGE))
    run = api.post("/v1/toolkits/call").respond(json={"name": "search", "content": "Refunds take 5 days.", "is_error": False})
    tools = [{"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}}]
    reply = nc.AI.chat("How long do refunds take?", tools=tools)
    call = {"id": "call_1", "type": "function", "function": {"name": "search", "arguments": '{"query": "refunds"}'}}
    assert reply.text == "" and reply.tool_calls == [call] and reply.finish_reason == "tool_calls"
    assert reply.message == {"role": "assistant", "content": None, "tool_calls": [call]}
    [message] = nc.Toolkit(["search"]).handle_openai(reply.message)
    assert body(run.calls.last.request) == {"name": "search", "arguments": {"query": "refunds"}}
    assert message == {"role": "tool", "tool_call_id": "call_1", "content": "Refunds take 5 days."}


def test_chat_forces_a_tool_and_sets_the_effort_and_a_reply_that_spent_max_tokens_reasoning_says_so(api, client):
    usage = {"prompt_tokens": 30, "completion_tokens": 50, "total_tokens": 80,
             "completion_tokens_details": {"reasoning_tokens": 50}}
    route = api.post("/v1/ai/chat/completions").mock(side_effect=[
        stream(chunk({"role": "assistant", "content": "", "reasoning": "The user wants "}),
               chunk({"reasoning": "one number, so"}), chunk(finish="length"), {**USAGE, "usage": usage}),
        stream(chunk({"content": "4"}), chunk(finish="stop"), USAGE),
    ])
    submit = {"type": "function", "function": {"name": "submit"}}
    reply = nc.AI.chat("Pick a number.", max_tokens=50, tools=[submit], tool_choice=submit, reasoning_effort="low")
    sent = body(route.calls.last.request)
    assert (sent["tool_choice"], sent["reasoning_effort"], sent["max_tokens"]) == (submit, "low", 50)
    # All 50 tokens went on reasoning: no answer, and the reply shows why.
    assert (reply.text, reply.finish_reason, reply.reasoning) == ("", "length", "The user wants one number, so")
    assert reply.usage["reasoning_tokens"] == reply.usage["completion_tokens"] == 50
    assert reply.message["reasoning"] == "The user wants one number, so"
    plain = nc.AI.chat("Pick a number.")
    assert (plain.reasoning, "reasoning_tokens" in plain.usage) == (None, False)
    assert plain.message == {"role": "assistant", "content": "4"}


def test_an_agent_reply_carries_its_conversation(api, client):
    route = api.post("/v1/ai/chat/completions").mock(return_value=stream(
        chunk({"role": "assistant", "content": ""}), chunk({"content": "It's on its way."}),
        chunk(finish="stop", cost_usd=0.004, metadata={"conversation": "c_1"},
              noclick={"agent_id": "a_1", "operation_id": "op_1", "conversation": "c_1", "tool_calls": [
                  {"tool": "shopify__get_order", "arguments": {}, "result": "{}", "is_error": False,
                   "created_at": "2026-10-15T10:00:00+00:00"}]}),
        head=": keepalive\n\n: keepalive\n\n"))
    reply = nc.AI.chat("Where's my refund?", model="agent:support")
    assert (reply.text, reply.conversation, reply.cost_usd, reply.tool_calls) == ("It's on its way.", "c_1", 0.004, [])
    assert reply.raw["noclick"]["tool_calls"][0]["tool"] == "shopify__get_order"
    nc.AI.chat("And when?", model="agent:support", conversation=reply.conversation)
    assert body(route.calls.last.request)["metadata"] == {"conversation": "c_1"}


def test_openai_shaped_errors_raise_noclick_errors(api, client):
    route = api.post("/v1/ai/chat/completions")
    route.respond(400, json={"error": {"message": "No agent 'nobody' here.", "type": "invalid_request_error",
                                       "param": "model", "code": "invalid_request", "next_step": "List them."}})
    with pytest.raises(nc.InvalidRequest) as refused:
        nc.AI.chat("hi", model="agent:nobody")
    assert refused.value.type == "invalid_request" and refused.value.param == "model"
    assert refused.value.next_step == "List them."

    # A rate limit before the stream starts is retried with backoff first.
    route.side_effect = [
        httpx.Response(429, headers={"retry-after": "2"}, json={"error": {
            "message": "slow down", "type": "rate_limit_error", "code": "rate_limited"}}),
        stream(chunk({"content": "ok"}), chunk(finish="stop")),
    ]
    assert nc.AI.chat("hi").text == "ok" and client.sleeps == [2.0]

    # A failure after it started is the stream's last event.
    route.side_effect = None
    route.mock(return_value=stream(chunk({"content": "Fri"}), {"error": {
        "message": "The model's provider failed (502): provider hung up", "type": "server_error",
        "code": "upstream_error"}}))
    with pytest.raises(nc.UpstreamError, match="provider hung up"):
        nc.AI.chat("hi")

    # A timeout answers 503 (the edge swaps a 504's body for its own page); the code decides either way.
    embed = api.post("/v1/ai/embeddings")
    for status in (503, 504):
        embed.mock(return_value=httpx.Response(status, headers={"x-should-retry": "false"}, json={"error": {
            "message": "The agent is still answering after 90 seconds.", "type": "server_error",
            "code": "request_timeout", "operation_id": "op_1"}}))
        client.sleeps.clear()
        with pytest.raises(nc.RequestTimeout) as late:
            nc.AI.embed("x")
        assert late.value.operation_id == "op_1" and client.sleeps == [] and isinstance(late.value, TimeoutError)
        assert late.value.status == status


def test_embed_keeps_input_order(api, client):
    route = api.post("/v1/ai/embeddings").respond(json={
        "object": "list", "model": "openrouter/openai/text-embedding-3-small",
        "data": [{"index": 1, "embedding": [0.3, 0.4]}, {"index": 0, "embedding": [0.1, 0.2]}],
        "usage": {"prompt_tokens": 6, "total_tokens": 6}, "cost_usd": 0.0000001,
    })
    result = nc.AI.embed(["first", "second"], model="openrouter/openai/text-embedding-3-small", dimensions=2)
    assert body(route.calls.last.request) == {
        "model": "openrouter/openai/text-embedding-3-small", "input": ["first", "second"], "dimensions": 2,
    }
    assert result.vectors == [[0.1, 0.2], [0.3, 0.4]] and result.dimensions == 2 and result.cost_usd == 0.0000001
    nc.AI.embed("one")
    assert body(route.calls.last.request) == {"input": ["one"]}


def test_image_is_kept_as_a_file(api, client):
    route = api.post("/v1/ai/images").respond(json={
        "object": "image", "url": "https://assets.test/img_1.png", "file_id": "f_1", "width": 1024, "height": 1536,
        "model": "openrouter/openai/gpt-image-2.5-sunburst", "cost_usd": 0.04, "expires_at": None,
    })
    image = nc.AI.image("A lighthouse at dusk, watercolor", size="1024x1536")
    assert body(route.calls.last.request) == {"prompt": "A lighthouse at dusk, watercolor", "size": "1024x1536"}
    assert (image.url, image.file_id, image.width, image.height, image.cost_usd, image.expires_at) == (
        "https://assets.test/img_1.png", "f_1", 1024, 1536, 0.04, None)
    nc.AI.image("Make it night", images=[image.url])
    assert body(route.calls.last.request) == {"prompt": "Make it night", "images": ["https://assets.test/img_1.png"]}


def test_a_video_is_an_operation_that_ends_in_the_file(api, client):
    started = {"id": "op_v", "object": "operation", "kind": "ai.video", "status": "running"}
    route = api.post("/v1/ai/videos").respond(202, json=started)
    api.get("/v1/operations/op_v/wait").respond(json={**started, "status": "succeeded", "result": {
        "object": "video", "url": "https://assets.test/v.mp4", "file_id": "f_v", "mime_type": "video/mp4",
        "seconds": 8, "resolution": "720p", "model": "openrouter/google/veo-3.1-fast", "cost_usd": 1.2}})
    with nc.as_user("user_42"):
        job = nc.AI.video("Waves under a lighthouse", seconds=8, aspect_ratio="9:16")
    request = route.calls.last.request
    assert body(request) == {"prompt": "Waves under a lighthouse", "seconds": 8, "aspect_ratio": "9:16", "audio": True}
    assert request.headers["NoClick-User"] == "user_42" and (job.id, job.kind) == ("op_v", "ai.video")
    clip = job.wait()
    assert isinstance(clip, nc.GeneratedVideo)
    assert (clip.url, clip.file_id, clip.seconds, clip.resolution, clip.cost_usd) == (
        "https://assets.test/v.mp4", "f_v", 8, "720p", 1.2)
    # A photo brought to life: the picture it starts from, by a file's id or a URL.
    nc.AI.video("She turns and waves", first_frame="f_photo")
    assert body(route.calls.last.request) == {"prompt": "She turns and waves", "audio": True, "first_frame": "f_photo"}


def test_a_refusal_for_money_carries_its_offers(api, client):
    offer = {"kind": "plan", "label": "the Plus plan, billed monthly", "price_usd": 25.0,
             "url": "https://noclick.com/pay/j_1", "expires_at": "2026-10-17T09:00:00+00:00", "operation_id": "op_pay"}
    api.post("/v1/ai/images").respond(402, json={"error": {
        "message": "The account's balance can't cover this.", "type": "invalid_request_error", "code": "payment_required",
        "required_usd": 0.04, "balance_usd": 0.0, "offers": [offer]}})
    api.get("/v1/operations/op_pay/wait").respond(json={
        "id": "op_pay", "kind": "payment", "status": "succeeded",
        "result": {"object": "payment", "kind": "plan", "what": "the Plus plan, billed monthly", "price_usd": 25.0}})
    with pytest.raises(nc.PaymentRequired) as refused:
        nc.AI.image("A lighthouse")
    [made] = refused.value.offers
    assert (made.kind, made.label, made.price_usd, made.url) == ("plan", "the Plus plan, billed monthly", 25.0,
                                                                 "https://noclick.com/pay/j_1")
    assert made.expires_at == datetime(2026, 10, 17, 9, tzinfo=timezone.utc)
    assert (made.operation.id, made.operation.wait()["what"]) == ("op_pay", "the Plus plan, billed monthly")
    assert nc.PlanRequired("No phone numbers on Free.").offers == []


def test_transcribe_a_url_or_bytes(api, client):
    transcript = {
        "object": "transcript", "text": "Hi, it's Ana.", "language": "en", "duration_s": 3.2, "cost_usd": 0.001,
        "segments": [{"start_s": 0.0, "end_s": 3.2, "text": "Hi, it's Ana."}], "model": "openrouter/google/gemini-3.5-flash",
    }
    route = api.post("/v1/ai/transcriptions").respond(json=transcript)
    words = nc.AI.transcribe("https://example.com/call.mp3", language="en")
    assert body(route.calls.last.request) == {"url": "https://example.com/call.mp3", "language": "en"}
    assert (str(words), words.language, words.duration_s) == ("Hi, it's Ana.", "en", 3.2)
    assert words.segments == [nc.TranscriptSegment(0.0, 3.2, "Hi, it's Ana.")]

    nc.AI.transcribe(b"ID3\x00audio", model="openrouter/google/gemini-3.5-flash")
    request = route.calls.last.request
    assert request.content == b"ID3\x00audio"
    assert request.headers["Content-Type"] == "application/octet-stream"
    assert dict(request.url.params) == {"model": "openrouter/google/gemini-3.5-flash"}


def test_models_read_the_catalog_for_the_acting_user(api, client):
    route = api.get("/v1/ai/models").respond(json=listing(
        {"id": MODEL, "name": "Claude Sonnet 4.6", "kind": "chat", "context_length": 200000,
         "input_usd_per_token": 0.000003, "output_usd_per_token": 0.000015, "usd_per_minute": None,
         "parameters": ["max_tokens", "reasoning_effort", "tool_choice", "tools"],
         "reasoning": {"mandatory": True, "efforts": ["high", "medium", "low"], "default_effort": "high"}},
        {"id": "agent:support", "name": "support", "kind": "agent", "owned_by": "noclick-agent", "agent_id": "a_1"}))
    with nc.as_user("user_42"):
        model, agent = nc.AI.models()
    # Agents are the acting user's, so the user rides along.
    assert route.calls.last.request.headers["NoClick-User"] == "user_42"
    assert (model.id, model.kind, model.context_length, model.output_usd_per_token) == (MODEL, "chat", 200000, 0.000015)
    # What the model takes, and how it reasons: always, so ``none`` isn't among its efforts.
    assert model.parameters == ["max_tokens", "reasoning_effort", "tool_choice", "tools"]
    assert model.reasoning == nc.AIReasoning(mandatory=True, efforts=["high", "medium", "low"], default_effort="high")
    assert (agent.id, agent.kind, agent.input_usd_per_token, agent.raw["agent_id"]) == ("agent:support", "agent", None, "a_1")
    assert (agent.parameters, agent.reasoning) == (None, None)
    nc.AI.models(kind="agent")
    assert route.calls.last.request.url.params["kind"] == "agent"
    # One model's price without reading the whole catalog: by part of its id or name, or by its id.
    nc.AI.models(q="sonnet")
    assert dict(route.calls.last.request.url.params) == {"q": "sonnet"}
    nc.AI.models(model=MODEL)
    assert dict(route.calls.last.request.url.params) == {"model": MODEL}
    assert (model.frame_images, agent.frame_images) == (None, None)
    route.respond(json=listing({"id": "openrouter/google/veo-3.1-fast", "kind": "video", "usd_per_second": 0.15,
                                "frame_images": ["first_frame", "last_frame"]}))
    [veo] = nc.AI.models(kind="video")
    assert (veo.kind, veo.usd_per_second, veo.input_usd_per_token) == ("video", 0.15, None)
    assert veo.frame_images == ["first_frame", "last_frame"]


def test_feedback_reaches_the_team_from_the_account(api, client):
    route = api.post("/v1/feedback").respond(201, json={"object": "feedback", "kind": "idea", "received": True})
    with nc.as_user("user_42"):
        assert nc.feedback("Agent.list could filter by workflow.", kind="idea") is None
    request = route.calls.last.request
    assert body(request) == {"message": "Agent.list could filter by workflow.", "kind": "idea"}
    assert "NoClick-User" not in request.headers
    with pytest.raises(ValueError):
        nc.feedback("x", kind="praise")


def test_base_url_follows_the_default_client(client):
    assert nc.AI.base_url == "https://api.test/v1/ai"
