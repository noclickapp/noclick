/**
 * AI: models paid from your NoClick balance, for code that isn't an agent, and
 * your agents as models.
 *
 *     const reply = await AI.chat("Summarize this in one line: ...");
 *     const { vectors } = await AI.embed(["first", "second"]);
 *     const image = await AI.image("A lighthouse at dusk, watercolor");
 *     const clip = await (await AI.video("Waves rolling under a lighthouse at dusk")).wait();
 *     const words = await AI.transcribe("https://example.com/call.mp3");
 *     const answer = await AI.chat("Where's my refund?", { model: "agent:support" });
 *
 * Every call is charged in US dollars to your account; inside `asUser` it is
 * attributed to that user and counts against its spend cap. `AI.baseUrl` serves
 * chat completions, responses, embeddings and the model list to any OpenAI client.
 */

import { defaultClient, resolveClient } from "./client.ts";
import { asList, asObject, compact, num, parseTime, str } from "./object.ts";
import type { CallOptions, JsonObject } from "./object.ts";
import { Operation, registerResult } from "./operation.ts";
import { USER_HEADER, resolveScope, userIdOf } from "./scope.ts";

/** A large image or a long recording takes a while. */
const IMAGE_TIMEOUT_MS = 180_000;
const TRANSCRIBE_TIMEOUT_MS = 180_000;

/** One message of a conversation, in the OpenAI shape (`tool_calls` and `tool_call_id` included). */
export type AIChatMessage = { role: string; content?: unknown } & JsonObject;

export interface AIChatOptions extends CallOptions {
  /** An OpenRouter id with the `openrouter/` prefix, or `agent:<name>` for one of your agents; NoClick's default when omitted. */
  model?: string;
  maxTokens?: number;
  temperature?: number;
  /** Ask for JSON: `{ type: "json_schema", json_schema: ... }`. */
  responseFormat?: JsonObject;
  /** OpenAI-format tool definitions, such as `await toolkit.definitions({ format: "openai" })`. An agent takes none. */
  tools?: JsonObject[];
  /**
   * Which of `tools` the model calls: `auto` (its choice), `none`, `required` (one of them), or one by name,
   * `{ type: "function", function: { name: "submit" } }`. A model may refuse to be made to (`AIReasoning.mandatory`).
   */
  toolChoice?: "auto" | "none" | "required" | JsonObject;
  /**
   * How hard a model that reasons thinks first, among its `reasoning.efforts` (`AI.models`): its reasoning counts
   * toward `maxTokens`, so a lower effort leaves more of them for the answer, and `none` turns it off where the model
   * can stop.
   */
  reasoningEffort?: string;
  /** An agent's conversation to continue (`reply.conversation`); only the messages after the last assistant message are sent. */
  conversation?: string;
  signal?: AbortSignal;
}

/** A model's (or an agent's) answer: `text`, and the whole `message` to append to the conversation. */
export interface ChatReply {
  /** The answer as text (empty when the model only called tools). */
  text: string;
  /** The assistant message as the API sent it (`role`, `content`, `tool_calls`). */
  message: AIChatMessage;
  /** The tools the model asked to call (empty if none), in the shape `toolkit.handleOpenAI` runs. An agent runs its own. */
  toolCalls: JsonObject[];
  /** An agent's conversation this reply is part of: pass it as `conversation` to continue it. */
  conversation: string | null;
  model: string | null;
  /**
   * `stop`, `length` (`maxTokens` reached, reasoning included: a model that spends them all reasoning answers with an
   * empty `text`) or `tool_calls`.
   */
  finishReason: string | null;
  /** What the model thought before it answered, where its provider returns it (null otherwise). */
  reasoning: string | null;
  /**
   * `prompt_tokens`, `completion_tokens`, `total_tokens`, and `reasoning_tokens`, the part of `completion_tokens`
   * spent reasoning, where the model reports it (none for an agent).
   */
  usage: Record<string, number>;
  /** What the call cost, in US dollars. */
  costUsd: number | null;
  raw: JsonObject;
}

/** One vector per input, in the order you passed them. */
export interface Embeddings {
  vectors: number[][];
  /** The length of each vector. */
  dimensions: number;
  model: string | null;
  usage: Record<string, number>;
  costUsd: number | null;
  raw: JsonObject;
}

/** An image a model made, kept as one of your account's files. */
export interface GeneratedImage {
  /** A link to the image that keeps working. */
  url: string;
  /** The file in your account's files. */
  fileId: string | null;
  width: number | null;
  height: number | null;
  model: string | null;
  costUsd: number | null;
  /** When `url` stops working: null, since the file is kept. */
  expiresAt: Date | null;
  raw: JsonObject;
}

/** A video a model made, kept as one of your account's files. */
export interface GeneratedVideo {
  /** A link to the video that keeps working. */
  url: string;
  /** The file in your account's files. */
  fileId: string | null;
  mimeType: string | null;
  seconds: number | null;
  resolution: string | null;
  model: string | null;
  costUsd: number | null;
  raw: JsonObject;
}

export interface VideoOptions extends CallOptions {
  model?: string;
  /** Among the lengths the model makes; about 8 when omitted. */
  seconds?: number;
  /** `720p`, `1080p`, as the model makes them; 720p where it can when omitted. */
  resolution?: string;
  /** `16:9`, `9:16`, as the model makes them. */
  aspectRatio?: string;
  /** Sound, where the model makes it (default true). */
  audio?: boolean;
  /**
   * A picture the video starts from, to bring a photo to life: one of your account's files by its id, or a JPEG,
   * PNG or WebP image's https URL, up to 10 MB, on a model whose `frameImages` list `first_frame`.
   */
  firstFrame?: string;
}

/** A stretch of speech: what was said between `startS` and `endS`, and by whom when you asked for `speakers`. */
export interface TranscriptSegment {
  startS: number;
  endS: number;
  text: string;
  /**
   * Who said it: one of the names you gave `speakers`, or `speaker_1`,
   * `speaker_2`, ... in the order the voices first speak (absent unless you asked).
   */
  speaker?: string;
}

/** What was said in a recording, as one `text` and as timed `segments`. */
export interface Transcript {
  text: string;
  /**
   * The spoken language as an ISO 639-1 code (`en`), detected unless you passed one; ISO 639-3 (`yue`) for a
   * language with no two-letter code.
   */
  language: string | null;
  durationS: number | null;
  segments: TranscriptSegment[];
  model: string | null;
  costUsd: number | null;
  raw: JsonObject;
}

/** A recording: an `https` URL to it, or its bytes. */
export type TranscribeAudio = string | Uint8Array | ArrayBuffer | Blob;

export interface TranscribeOptions extends CallOptions {
  model?: string;
  language?: string;
  /** `true`, or a name per voice. */
  speakers?: boolean | string[];
  /** Return an `Operation` at once instead of waiting. */
  background?: boolean;
}

export type AIModelKind = "chat" | "embedding" | "image" | "transcription" | "video" | "agent";

/**
 * A model you can call, and what it costs in US dollars (its provider's own price). Only the
 * prices for its `kind` are set: per token for chat and embedding models, per token of the image an
 * image model makes, per minute of audio for transcription ones, per second for video ones, none for
 * an agent.
 */
export interface AIModel {
  /** The id to pass as `model`, like `openrouter/anthropic/claude-sonnet-4.6` or `agent:support`. */
  id: string;
  name: string | null;
  kind: AIModelKind;
  /** The most tokens a request can hold (chat and embedding models). */
  contextLength: number | null;
  inputUsdPerToken: number | null;
  outputUsdPerToken: number | null;
  usdPerMinute: number | null;
  /** What a minute of audio costs with `speakers`; null for a model of another kind. */
  usdPerMinuteWithSpeakers: number | null;
  /** What a second of video costs, for the clip a call naming no length or resolution makes. */
  usdPerSecond: number | null;
  /**
   * The request fields a chat model takes, as its provider lists them (`tools`, `tool_choice`, `reasoning_effort`,
   * `temperature`, ...): one it doesn't list has no effect. Null for other kinds.
   */
  parameters: string[] | null;
  /** How a chat model reasons; null for one that doesn't. */
  reasoning: AIReasoning | null;
  /**
   * The frames a video model can start or end on a picture (`first_frame`, `last_frame`): one listing
   * `first_frame` takes `AI.video(prompt, { firstFrame })`. Null for other kinds.
   */
  frameImages: string[] | null;
  raw: JsonObject;
}

/**
 * How a chat model reasons before it answers. Its reasoning counts toward `maxTokens`, so a short budget can go
 * entirely on reasoning and leave the answer empty (`finishReason` `length`).
 */
export interface AIReasoning {
  /**
   * It always reasons, whatever `reasoningEffort` says. Anthropic's models refuse a forced tool (`toolChoice`
   * `required` or naming a function) while they reason, so on one of theirs that always does, only `auto` and `none` work.
   */
  mandatory: boolean;
  /** The `reasoningEffort` values it takes (`none` among them where it can stop reasoning). */
  efforts: string[];
  /** Its effort when a call names none. */
  defaultEffort: string | null;
}

function counts(value: unknown): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, n] of Object.entries(asObject(value))) if (typeof n === "number") out[key] = n;
  return out;
}

/** A completion's token counts, with the reasoning share of `completion_tokens` lifted out of its details. */
function chatUsage(value: unknown): Record<string, number> {
  const usage = counts(value);
  const reasoned = asObject(asObject(value).completion_tokens_details).reasoning_tokens;
  if (typeof reasoned === "number") usage.reasoning_tokens = reasoned;
  return usage;
}

/** A streamed chat completion as the whole completion it adds up to. */
function assembled(chunks: readonly JsonObject[]): JsonObject {
  let text = "";
  let thought = "";
  let finish: unknown = null;
  let usage: unknown = null;
  const calls = new Map<number, { id: unknown; type: "function"; function: { name: string; arguments: string } }>();
  const head: JsonObject = {};
  const extra: JsonObject = {};
  for (const chunk of chunks) {
    for (const key of ["id", "created", "model"]) if (chunk[key] != null) head[key] = chunk[key];
    for (const choice of Array.isArray(chunk.choices) ? (chunk.choices as JsonObject[]) : []) {
      const delta = asObject(choice.delta);
      text += str(delta.content) ?? "";
      thought += str(delta.reasoning) ?? "";
      for (const call of Array.isArray(delta.tool_calls) ? (delta.tool_calls as JsonObject[]) : []) {
        const index = num(call.index) ?? 0;
        const slot = calls.get(index) ?? { id: null, type: "function" as const, function: { name: "", arguments: "" } };
        const fn = asObject(call.function);
        slot.id = call.id ?? slot.id;
        slot.function.name += str(fn.name) ?? "";
        slot.function.arguments += str(fn.arguments) ?? "";
        calls.set(index, slot);
      }
      finish = choice.finish_reason ?? finish;
    }
    usage = chunk.usage ?? usage;
    for (const key of ["cost_usd", "metadata", "noclick"]) if (key in chunk) extra[key] = chunk[key];
  }
  const message: JsonObject = { role: "assistant", content: text || !calls.size ? text : null };
  if (calls.size) message.tool_calls = [...calls.keys()].sort((a, b) => a - b).map((i) => calls.get(i));
  if (thought) message.reasoning = thought;
  return { ...head, object: "chat.completion", usage, choices: [{ index: 0, message, finish_reason: finish }], ...extra };
}

function toChatReply(value: unknown): ChatReply {
  const raw = asObject(value);
  const choice = asObject(Array.isArray(raw.choices) ? raw.choices[0] : undefined);
  const message = asObject(choice.message) as AIChatMessage;
  return {
    text: str(message.content) ?? "",
    message,
    toolCalls: Array.isArray(message.tool_calls) ? (message.tool_calls as JsonObject[]) : [],
    conversation: str(asObject(raw.metadata).conversation),
    model: str(raw.model),
    finishReason: str(choice.finish_reason),
    reasoning: str(message.reasoning) || null,
    usage: chatUsage(raw.usage),
    costUsd: num(raw.cost_usd),
    raw,
  };
}

function toEmbeddings(value: unknown): Embeddings {
  const raw = asObject(value);
  const rows = (asList(raw) as JsonObject[]).slice().sort((a, b) => (num(a.index) ?? 0) - (num(b.index) ?? 0));
  const vectors = rows.map((row) => (Array.isArray(row.embedding) ? (row.embedding as number[]) : []));
  return { vectors, dimensions: vectors[0]?.length ?? 0, model: str(raw.model), usage: counts(raw.usage), costUsd: num(raw.cost_usd), raw };
}

function toImage(value: unknown): GeneratedImage {
  const raw = asObject(value);
  return {
    url: str(raw.url) ?? "",
    fileId: str(raw.file_id),
    width: num(raw.width),
    height: num(raw.height),
    model: str(raw.model),
    costUsd: num(raw.cost_usd),
    expiresAt: parseTime(raw.expires_at),
    raw,
  };
}

function toVideo(value: unknown): GeneratedVideo {
  const raw = asObject(value);
  return {
    url: str(raw.url) ?? "",
    fileId: str(raw.file_id),
    mimeType: str(raw.mime_type),
    seconds: num(raw.seconds),
    resolution: str(raw.resolution),
    model: str(raw.model),
    costUsd: num(raw.cost_usd),
    raw,
  };
}

registerResult("ai.video", toVideo);

function toTranscript(value: unknown): Transcript {
  const raw = asObject(value);
  const segments = (Array.isArray(raw.segments) ? (raw.segments as JsonObject[]) : []).map((s) => ({
    startS: num(s.start_s) ?? 0, endS: num(s.end_s) ?? 0, text: str(s.text) ?? "",
    ...(str(s.speaker) ? { speaker: String(s.speaker) } : {}),
  }));
  return {
    text: str(raw.text) ?? "",
    language: str(raw.language),
    durationS: num(raw.duration_s),
    segments,
    model: str(raw.model),
    costUsd: num(raw.cost_usd),
    raw,
  };
}

registerResult("ai.transcription", toTranscript);

function toModel(value: unknown): AIModel {
  const raw = asObject(value);
  return {
    id: String(raw.id),
    name: str(raw.name),
    kind: String(raw.kind) as AIModelKind,
    contextLength: num(raw.context_length),
    inputUsdPerToken: num(raw.input_usd_per_token),
    outputUsdPerToken: num(raw.output_usd_per_token),
    usdPerMinute: num(raw.usd_per_minute),
    usdPerMinuteWithSpeakers: num(raw.usd_per_minute_with_speakers),
    usdPerSecond: num(raw.usd_per_second),
    parameters: Array.isArray(raw.parameters) ? raw.parameters.map(String) : null,
    reasoning: toReasoning(raw.reasoning),
    frameImages: Array.isArray(raw.frame_images) ? raw.frame_images.map(String) : null,
    raw,
  };
}

function toReasoning(value: unknown): AIReasoning | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as JsonObject;
  return {
    mandatory: raw.mandatory === true,
    efforts: Array.isArray(raw.efforts) ? raw.efforts.map(String) : [],
    defaultEffort: str(raw.default_effort),
  };
}

/**
 * Models paid from your NoClick balance, for code that isn't an agent: chat, embeddings, images,
 * videos and transcription; and your agents as `agent:<name>` models. Model ids are OpenRouter ids with the
 * `openrouter/` prefix, except transcription's, NoClick's own `noclick/transcribe-1`; leave `model` out for
 * NoClick's default of each kind.
 */
export class AI {
  /**
   * The OpenAI-compatible endpoint (`https://api.noclick.com/v1/ai` on the hosted API): point any OpenAI
   * client at it with your NoClick key for chat completions, responses, embeddings and the model list.
   */
  static get baseUrl(): string {
    return `${defaultClient().baseUrl}/v1/ai`;
  }

  /**
   * Send a conversation to a chat model: OpenAI-shaped messages, or a string as one user message.
   * `model: "agent:<name>"` talks to one of your agents instead: it brings its own tools and keeps the
   * conversation (`conversation: reply.conversation` continues it). The answer streams, so a long turn
   * never times out. A request with no conversation whose messages end in an assistant reply the agent
   * gave recently continues that reply's conversation, so a chat UI that resends the whole history
   * keeps one thread (invite-only beta).
   *
   *     const reply = await AI.chat("Summarize: the meeting moved to Friday at 3pm.", { maxTokens: 200 });
   *     console.log(reply.text, reply.costUsd);
   */
  static async chat(messages: string | readonly (AIChatMessage | string)[], options: AIChatOptions = {}): Promise<ChatReply> {
    const list = typeof messages === "string" ? [messages] : messages;
    const sent = list.map((m) => (typeof m === "string" ? { role: "user", content: m } : m));
    const events = resolveClient(options.client)._events("POST", "/v1/ai/chat/completions", {
      json: compact({
        model: options.model,
        messages: sent,
        max_tokens: options.maxTokens,
        temperature: options.temperature,
        response_format: options.responseFormat,
        tools: options.tools,
        tool_choice: options.toolChoice,
        reasoning_effort: options.reasoningEffort,
        metadata: options.conversation ? { conversation: options.conversation } : undefined,
        stream: true,
        stream_options: { include_usage: true },
      }),
      user: resolveScope(options.user),
      signal: options.signal,
    });
    const chunks: JsonObject[] = [];
    for await (const [, data] of events) chunks.push(data);
    return toChatReply(assembled(chunks));
  }

  /** Turn text into vectors: one string, or up to 2,048. `dimensions` shortens them, for models that allow it. */
  static async embed(texts: string | readonly string[], options: CallOptions & { model?: string; dimensions?: number } = {}): Promise<Embeddings> {
    const raw = await resolveClient(options.client).request("POST", "/v1/ai/embeddings", {
      json: compact({ model: options.model, input: typeof texts === "string" ? [texts] : [...texts], dimensions: options.dimensions }),
      user: resolveScope(options.user),
    });
    return toEmbeddings(raw);
  }

  /**
   * Make one image, kept as one of your account's files (its `url` keeps working); `size` is
   * `"WIDTHxHEIGHT"` in an aspect ratio the model makes (its own shape unless you say). `images` are
   * pictures (URLs, up to 8) to make it from: one to edit, the prompt saying what to change, or several to combine.
   */
  static async image(
    prompt: string,
    options: CallOptions & { model?: string; size?: string; images?: readonly string[] } = {},
  ): Promise<GeneratedImage> {
    const raw = await resolveClient(options.client).request("POST", "/v1/ai/images", {
      json: compact({ prompt, model: options.model, size: options.size, images: options.images?.length ? [...options.images] : undefined }),
      user: resolveScope(options.user),
      timeoutMs: IMAGE_TIMEOUT_MS,
    });
    return toImage(raw);
  }

  /**
   * Start one video. It takes minutes, so it runs as an `Operation` whose `wait()` resolves to the
   * `GeneratedVideo`, kept as one of your account's files. Its price is quoted before it starts
   * (`usdPerSecond` in `AI.models({ kind: "video" })`) and charged when it's done. `firstFrame` starts it
   * from a picture.
   *
   *     const job = await AI.video("Waves rolling under a lighthouse at dusk", { seconds: 8, aspectRatio: "9:16" });
   *     const clip = await job.wait({ timeoutS: 600 });
   *     console.log(clip.url, clip.seconds, clip.costUsd);
   *     const waving = await AI.video("She turns and waves", { firstFrame: "https://example.com/me.jpg" });
   */
  static async video(prompt: string, options: VideoOptions = {}): Promise<Operation<GeneratedVideo>> {
    const user = resolveScope(options.user);
    const raw = await resolveClient(options.client).request("POST", "/v1/ai/videos", {
      json: compact({
        prompt,
        model: options.model,
        seconds: options.seconds,
        resolution: options.resolution,
        aspect_ratio: options.aspectRatio,
        audio: options.audio ?? true,
        first_frame: options.firstFrame,
      }),
      user,
    });
    return Operation._fromPayload<GeneratedVideo>(raw, { client: options.client, user, kind: "ai.video", reader: toVideo });
  }

  /**
   * Write down what is said in a recording: an `https` URL to it, or its bytes, up to 2 hours (25 MB as
   * bytes, 200 MB behind a URL), in MP3, WAV, M4A, MP4, OGG, WebM, AAC, FLAC or AIFF. `language` (ISO
   * 639-1) skips detection. It runs on `noclick/transcribe-1`, which takes the whole recording in one call
   * and gives a segment per sentence, priced per minute of audio as `usdPerMinute` in `AI.models`.
   *
   * `speakers` tells the voices apart, at the same price, each voice keeping its label from start to end,
   * and gives a segment per voice's turn. `true` labels each segment's `speaker` `speaker_1`, `speaker_2`,
   * ... in the order they first speak; a list of names (`["rep", "customer"]`) says how many voices there
   * are, and NoClick works out which is which from what they say, giving a voice it can't tell the next
   * unused name in speaking order.
   *
   * `{ background: true }` returns an `Operation` at once, whose `wait()` resolves to the transcript: for
   * a recording that may take longer than one request waits (90 seconds), as a very long one can (forty
   * minutes usually take about 20 seconds). A call that doesn't run in the background and passes 90 seconds
   * rejects with `RequestTimeout` naming its operation, which still finishes and holds the transcript.
   */
  static transcribe(audio: TranscribeAudio, options: TranscribeOptions & { background: true }): Promise<Operation<Transcript>>;
  static transcribe(audio: TranscribeAudio, options?: TranscribeOptions & { background?: false }): Promise<Transcript>;
  static async transcribe(audio: TranscribeAudio, options: TranscribeOptions = {}): Promise<Transcript | Operation<Transcript>> {
    const client = resolveClient(options.client);
    const user = resolveScope(options.user);
    const speakers = Array.isArray(options.speakers) ? [...options.speakers] : options.speakers ? true : undefined;
    const background = options.background ? true : undefined;
    const raw =
      typeof audio === "string"
        ? await client.request("POST", "/v1/ai/transcriptions", {
            json: compact({ url: audio, model: options.model, language: options.language, speakers, background }),
            user,
            timeoutMs: TRANSCRIBE_TIMEOUT_MS,
          })
        : await client.request("POST", "/v1/ai/transcriptions", {
            body: audio,
            query: {
              model: options.model,
              language: options.language,
              speakers: speakers === undefined ? undefined : speakers === true ? "true" : speakers.join(","),
              background: background ? "true" : undefined,
            },
            user,
            timeoutMs: TRANSCRIBE_TIMEOUT_MS,
          });
    if (background) {
      return Operation._fromPayload<Transcript>(raw, { client: options.client, user, kind: "ai.transcription", reader: toTranscript });
    }
    return toTranscript(raw);
  }

  /**
   * The headers a call to `AI.baseUrl` needs: your key as the bearer and, inside `asUser` (or with
   * `user`), the `NoClick-User` that attributes the call to that user and holds it to the user's spend
   * cap. Give them to an OpenAI client as `defaultHeaders`; without the user header the account pays.
   *
   *     const gpt = new OpenAI({ baseURL: AI.baseUrl, apiKey: "-", defaultHeaders: await AI.headers({ user: "user_42" }) });
   */
  static async headers(options: CallOptions = {}): Promise<Record<string, string>> {
    const client = resolveClient(options.client);
    const headers: Record<string, string> = { Authorization: `Bearer ${await client._bearer()}` };
    const user = await userIdOf(resolveScope(options.user));
    if (user) headers[USER_HEADER] = user;
    return headers;
  }

  /**
   * The models you can call, the default of each kind first, with their prices in US dollars; `agent`
   * lists the agents you (or the user you act for) can talk to as `agent:<name>`. `q` keeps those whose
   * id or name contains it (any case), `model` the one with that id (`openrouter/` may be left out).
   *
   *     const [sonnet] = await AI.models({ model: "anthropic/claude-sonnet-4.6" });
   */
  static async models(options: CallOptions & { kind?: AIModelKind; q?: string; model?: string } = {}): Promise<AIModel[]> {
    const raw = await resolveClient(options.client).request("GET", "/v1/ai/models", {
      query: { kind: options.kind, q: options.q, model: options.model },
      user: resolveScope(options.user),
    });
    return asList(raw).map(toModel);
  }
}
