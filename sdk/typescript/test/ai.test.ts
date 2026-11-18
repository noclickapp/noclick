// AI over the mock API: chat streams from /v1/ai/chat/completions and adds up to one reply (tool calls,
// usage, cost, an agent's conversation), OpenAI-shaped errors throw the matching NoClickError, and the
// other calls send what the API takes.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, listing, setup } from "./helpers.ts";

const MODEL = "openrouter/anthropic/claude-sonnet-4.6";

function stream(chunks: unknown[], head = ": keepalive\n\n"): Response {
  const text = head + chunks.map((c) => `data: ${JSON.stringify(c)}\n\n`).join("") + "data: [DONE]\n\n";
  return new Response(text, { headers: { "content-type": "text/event-stream" } });
}

function chunk(delta: Record<string, unknown> = {}, finish: string | null = null, extra: Record<string, unknown> = {}) {
  return { id: "gen_1", object: "chat.completion.chunk", created: 1790000000, model: MODEL, choices: [{ index: 0, delta, finish_reason: finish }], ...extra };
}

const USAGE = { id: "gen_1", object: "chat.completion.chunk", model: MODEL, choices: [], usage: { prompt_tokens: 24, completion_tokens: 7, total_tokens: 31 }, cost_usd: 0.00018 };

test("AI.chat streams and adds up to one reply", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/ai/chat/completions", () =>
    stream([chunk({ role: "assistant", content: "" }), chunk({ content: "Moved to Friday, " }), chunk({ content: "3pm." }), chunk({}, "stop"), USAGE]));
  const reply = await nc.asUser("user_42", () => nc.AI.chat("Summarize: the meeting moved to Friday.", { model: MODEL, maxTokens: 200 }));
  assert.deepEqual(route.last.body, {
    model: MODEL, max_tokens: 200, messages: [{ role: "user", content: "Summarize: the meeting moved to Friday." }],
    stream: true, stream_options: { include_usage: true },
  });
  assert.equal(route.last.headers.get("NoClick-User"), "user_42");
  assert.equal(route.last.headers.get("Accept"), "text/event-stream");
  assert.deepEqual([reply.text, reply.finishReason, reply.costUsd, reply.usage.total_tokens, reply.model], ["Moved to Friday, 3pm.", "stop", 0.00018, 31, MODEL]);
  assert.deepEqual([reply.toolCalls, reply.conversation, reply.message], [[], null, { role: "assistant", content: "Moved to Friday, 3pm." }]);
});

test("AI.chat adds up streamed tool calls", async () => {
  const { api } = setup();
  const parts = [
    { index: 0, id: "call_1", type: "function", function: { name: "search", arguments: "" } },
    { index: 0, function: { arguments: '{"query": ' } }, { index: 0, function: { arguments: '"refunds"}' } },
  ];
  const route = api.on("POST", "/v1/ai/chat/completions", () => stream([...parts.map((p) => chunk({ tool_calls: [p] })), chunk({}, "tool_calls"), USAGE]));
  const tools = [{ type: "function", function: { name: "search" } }];
  const reply = await nc.AI.chat([{ role: "system", content: "Be brief." }, "Hi"], { tools, responseFormat: { type: "json_object" } });
  const call = { id: "call_1", type: "function", function: { name: "search", arguments: '{"query": "refunds"}' } };
  assert.deepEqual([reply.text, reply.toolCalls, reply.finishReason], ["", [call], "tool_calls"]);
  assert.deepEqual(reply.message, { role: "assistant", content: null, tool_calls: [call] });
  assert.deepEqual((route.last.body as Record<string, unknown>).messages, [{ role: "system", content: "Be brief." }, { role: "user", content: "Hi" }]);
});

test("AI.chat forces a tool and sets the reasoning effort; a reply that spent maxTokens reasoning says so", async () => {
  const { api } = setup();
  const usage = { prompt_tokens: 30, completion_tokens: 50, total_tokens: 80, completion_tokens_details: { reasoning_tokens: 50 } };
  const route = api.on("POST", "/v1/ai/chat/completions", () => stream([
    chunk({ role: "assistant", content: "", reasoning: "The user wants " }), chunk({ reasoning: "one number, so" }),
    chunk({}, "length"), { ...USAGE, usage },
  ]));
  const submit = { type: "function", function: { name: "submit" } };
  const reply = await nc.AI.chat("Pick a number.", { maxTokens: 50, tools: [submit], toolChoice: submit, reasoningEffort: "low" });
  const sent = route.last.body as Record<string, unknown>;
  assert.deepEqual([sent.tool_choice, sent.reasoning_effort, sent.max_tokens], [submit, "low", 50]);
  // All 50 tokens went on reasoning: no answer, and the reply shows why.
  assert.deepEqual([reply.text, reply.finishReason, reply.reasoning], ["", "length", "The user wants one number, so"]);
  assert.deepEqual([reply.usage.reasoning_tokens, reply.usage.completion_tokens], [50, 50]);
  assert.equal(reply.message.reasoning, "The user wants one number, so");

  api.on("POST", "/v1/ai/chat/completions", () => stream([chunk({ content: "4" }), chunk({}, "stop"), USAGE]));
  const plain = await nc.AI.chat("Pick a number.");
  assert.deepEqual([plain.reasoning, plain.usage.reasoning_tokens, plain.message], [null, undefined, { role: "assistant", content: "4" }]);
});

test("AI.chat with an agent carries its conversation", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/ai/chat/completions", () => stream([
    chunk({ role: "assistant", content: "" }), chunk({ content: "It's on its way." }),
    chunk({}, "stop", { cost_usd: 0.004, metadata: { conversation: "c_1" }, noclick: { agent_id: "a_1", tool_calls: [{ tool: "shopify__get_order" }] } }),
  ], ": keepalive\n\n: keepalive\n\n"));
  const reply = await nc.AI.chat("Where's my refund?", { model: "agent:support" });
  assert.deepEqual([reply.text, reply.conversation, reply.costUsd, reply.toolCalls], ["It's on its way.", "c_1", 0.004, []]);
  assert.equal((reply.raw.noclick as { agent_id: string }).agent_id, "a_1");
  await nc.AI.chat("And when?", { model: "agent:support", conversation: reply.conversation! });
  assert.deepEqual((route.last.body as Record<string, unknown>).metadata, { conversation: "c_1" });
});

test("AI.chat: OpenAI-shaped errors throw the matching error; a rate limit is retried before the stream starts", async () => {
  const { api, sleeps } = setup();
  api.on("POST", "/v1/ai/chat/completions", json({ error: {
    message: "No agent 'nobody' here.", type: "invalid_request_error", param: "model", code: "invalid_request", next_step: "List them." } }, { status: 400 }));
  await assert.rejects(nc.AI.chat("hi", { model: "agent:nobody" }), (err: nc.NoClickError) =>
    err instanceof nc.InvalidRequest && err.type === "invalid_request" && err.details.param === "model" && err.nextStep === "List them.");

  api.on("POST", "/v1/ai/chat/completions",
    json({ error: { message: "slow down", type: "rate_limit_error", code: "rate_limited" } }, { status: 429, headers: { "retry-after": "2" } }),
    () => stream([chunk({ content: "ok" }), chunk({}, "stop")]));
  assert.equal((await nc.AI.chat("hi")).text, "ok");
  assert.deepEqual(sleeps, [2000]);

  api.on("POST", "/v1/ai/chat/completions", () => stream([chunk({ content: "Fri" }), { error: {
    message: "The model's provider failed (502): provider hung up", type: "server_error", code: "upstream_error" } }]));
  await assert.rejects(nc.AI.chat("hi"), nc.UpstreamError);

  // A timeout answers 503 (the edge swaps a 504's body for its own page); the code decides either way.
  for (const status of [503, 504]) {
    const embed = api.on("POST", "/v1/ai/embeddings", json({ error: {
      message: "Too slow.", type: "server_error", code: "request_timeout", operation_id: "op_1" } }, { status }));
    await assert.rejects(nc.AI.embed("x"), (err: nc.NoClickError) =>
      err instanceof nc.RequestTimeout && err.status === status && err.details.operation_id === "op_1");
    assert.equal(embed.count, 1);
  }
});

test("AI.embed keeps the input order", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/ai/embeddings", json({
    object: "list", model: "openrouter/openai/text-embedding-3-small", usage: { prompt_tokens: 6 }, cost_usd: 0.0000001,
    data: [{ index: 1, embedding: [0.3, 0.4] }, { index: 0, embedding: [0.1, 0.2] }],
  }));
  const result = await nc.AI.embed(["first", "second"], { dimensions: 2 });
  assert.deepEqual(route.last.body, { input: ["first", "second"], dimensions: 2 });
  assert.deepEqual([result.vectors, result.dimensions, result.costUsd], [[[0.1, 0.2], [0.3, 0.4]], 2, 0.0000001]);
  await nc.AI.embed("one");
  assert.deepEqual(route.last.body, { input: ["one"] });
});

test("AI.image and AI.models", async () => {
  const { api } = setup();
  const image = api.on("POST", "/v1/ai/images", json({
    object: "image", url: "https://assets.test/img_1.png", file_id: "f_1", width: 1024, height: 1536, cost_usd: 0.04, expires_at: null,
  }));
  const made = await nc.AI.image("A lighthouse at dusk, watercolor", { size: "1024x1536" });
  assert.deepEqual(image.last.body, { prompt: "A lighthouse at dusk, watercolor", size: "1024x1536" });
  assert.deepEqual([made.url, made.fileId, made.width, made.height, made.costUsd, made.expiresAt],
    ["https://assets.test/img_1.png", "f_1", 1024, 1536, 0.04, null]);
  await nc.AI.image("Make it night", { images: [made.url] });
  assert.deepEqual(image.last.body, { prompt: "Make it night", images: ["https://assets.test/img_1.png"] });

  const models = api.on("GET", "/v1/ai/models", json(listing([
    { id: MODEL, name: "Claude Sonnet 4.6", kind: "chat", context_length: 200000, input_usd_per_token: 0.000003, output_usd_per_token: 0.000015,
      parameters: ["max_tokens", "reasoning_effort", "tool_choice", "tools"],
      reasoning: { mandatory: true, efforts: ["high", "medium", "low"], default_effort: "high" } },
    { id: "agent:support", name: "support", kind: "agent", owned_by: "noclick-agent", agent_id: "a_1" },
  ])));
  const [model, agent] = await nc.asUser("user_42", () => nc.AI.models());
  // Agents are the acting user's, so the user rides along.
  assert.equal(models.last.headers.get("NoClick-User"), "user_42");
  assert.deepEqual([model.id, model.contextLength, model.outputUsdPerToken, model.usdPerMinute], [MODEL, 200000, 0.000015, null]);
  // What the model takes, and how it reasons: always, so `none` isn't among its efforts.
  assert.deepEqual([model.parameters, model.reasoning], [
    ["max_tokens", "reasoning_effort", "tool_choice", "tools"], { mandatory: true, efforts: ["high", "medium", "low"], defaultEffort: "high" }]);
  assert.deepEqual([agent.id, agent.kind, agent.raw.agent_id, agent.parameters, agent.reasoning], ["agent:support", "agent", "a_1", null, null]);
  await nc.AI.models({ kind: "agent" });
  assert.equal(models.last.query.get("kind"), "agent");
  // One model's price without reading the whole catalog: by part of its id or name, or by its id.
  await nc.AI.models({ q: "sonnet" });
  assert.deepEqual([...models.last.query.entries()], [["q", "sonnet"]]);
  await nc.AI.models({ model: MODEL });
  assert.deepEqual([...models.last.query.entries()], [["model", MODEL]]);
});

test("AI.video is an operation that ends in the file; a video model is priced per second", async () => {
  const { api } = setup();
  const started = { object: "operation", id: "op_v", kind: "ai.video", status: "running" };
  const route = api.on("POST", "/v1/ai/videos", json(started, { status: 202 }));
  api.on("GET", "/v1/operations/op_v/wait", json({ ...started, status: "succeeded", result: {
    object: "video", url: "https://assets.test/v.mp4", file_id: "f_v", mime_type: "video/mp4", seconds: 8, resolution: "720p",
    model: "openrouter/google/veo-3.1-fast", cost_usd: 1.2,
  } }));
  const job = await nc.asUser("user_42", () => nc.AI.video("Waves under a lighthouse", { seconds: 8, aspectRatio: "9:16" }));
  assert.deepEqual(route.last.body, { prompt: "Waves under a lighthouse", seconds: 8, aspect_ratio: "9:16", audio: true });
  assert.equal(route.last.headers.get("NoClick-User"), "user_42");
  const clip = await job.wait();
  assert.deepEqual([clip.url, clip.fileId, clip.seconds, clip.resolution, clip.costUsd], ["https://assets.test/v.mp4", "f_v", 8, "720p", 1.2]);
  // A photo brought to life: the picture it starts from, by a file's id or a URL.
  await nc.AI.video("She turns and waves", { firstFrame: "f_photo" });
  assert.deepEqual(route.last.body, { prompt: "She turns and waves", audio: true, first_frame: "f_photo" });

  api.on("GET", "/v1/ai/models", json(listing([{ id: "openrouter/google/veo-3.1-fast", kind: "video", usd_per_second: 0.15,
    frame_images: ["first_frame", "last_frame"] }, { id: "openrouter/openai/gpt-image-2.5-sunburst", kind: "image" }])));
  const [veo, image] = await nc.AI.models({ kind: "video" });
  assert.deepEqual([veo.kind, veo.usdPerSecond, veo.inputUsdPerToken], ["video", 0.15, null]);
  assert.deepEqual([veo.frameImages, image.frameImages], [["first_frame", "last_frame"], null]);
});

test("a refusal for money carries its offers, each a payment operation", async () => {
  const { api } = setup();
  const offer = { kind: "plan", label: "the Plus plan, billed monthly", price_usd: 25, url: "https://noclick.com/pay/j_1",
    expires_at: "2026-10-17T09:00:00Z", operation_id: "op_pay" };
  api.on("POST", "/v1/ai/images", json({ error: { message: "The account's balance can't cover this.", type: "invalid_request_error",
    code: "payment_required", required_usd: 0.04, balance_usd: 0, offers: [offer] } }, { status: 402 }));
  api.on("GET", "/v1/operations/op_pay/wait", json({ object: "operation", id: "op_pay", kind: "payment", status: "succeeded",
    result: { object: "payment", kind: "plan", what: "the Plus plan, billed monthly", price_usd: 25 } }));
  const refused = await nc.AI.image("A lighthouse").then(() => null, (err: unknown) => err);
  assert.ok(refused instanceof nc.PaymentRequired);
  const [made] = refused.offers;
  assert.deepEqual([made.kind, made.label, made.priceUsd, made.url, made.expiresAt?.toISOString()],
    ["plan", "the Plus plan, billed monthly", 25, "https://noclick.com/pay/j_1", "2026-10-17T09:00:00.000Z"]);
  assert.equal(made.operation.id, "op_pay");
  assert.equal((await made.operation.wait()).what, "the Plus plan, billed monthly");
  assert.deepEqual(new nc.PlanRequired("No phone numbers on Free.").offers, []);
});

test("feedback reaches the team from the account", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/feedback", json({ object: "feedback", kind: "idea", received: true }, { status: 201 }));
  await nc.asUser("user_42", () => nc.feedback("Agent.list could filter by workflow.", { kind: "idea" }));
  assert.deepEqual(route.last.body, { message: "Agent.list could filter by workflow.", kind: "idea" });
  assert.equal(route.last.headers.get("NoClick-User"), null);
  await assert.rejects(nc.feedback("x", { kind: "praise" as nc.FeedbackKind }), TypeError);
});

test("AI.transcribe takes a URL as JSON or bytes as the body", async () => {
  const { api } = setup();
  const route = api.on("POST", "/v1/ai/transcriptions", json({
    object: "transcript", text: "Hi, it's Ana.", language: "en", duration_s: 3.2, segments: [{ start_s: 0, end_s: 3.2, text: "Hi, it's Ana." }],
  }));
  const words = await nc.AI.transcribe("https://example.com/call.mp3", { language: "en" });
  assert.deepEqual(route.last.body, { url: "https://example.com/call.mp3", language: "en" });
  assert.deepEqual([words.text, words.durationS, words.segments], ["Hi, it's Ana.", 3.2, [{ startS: 0, endS: 3.2, text: "Hi, it's Ana." }]]);

  await nc.AI.transcribe(new Uint8Array([73, 68, 51]), { model: "openrouter/google/gemini-3.5-flash" });
  assert.equal(route.last.headers.get("Content-Type"), "application/octet-stream");
  assert.deepEqual([...(route.calls[1].body as Uint8Array)], [73, 68, 51]);
  assert.equal(route.last.query.get("model"), "openrouter/google/gemini-3.5-flash");
  assert.equal(route.last.query.get("language"), null);
});

test("AI.baseUrl follows the default client", () => {
  setup();
  assert.equal(nc.AI.baseUrl, "https://api.test/v1/ai");
});
