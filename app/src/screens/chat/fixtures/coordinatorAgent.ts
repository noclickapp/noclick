// A fake /v1 for the Chat page on the coordinator agent: the agent, its one session (`owner`), its history, notes and live
// events (the moments the stream keeps, replayed to a watch that asks), a send answered by the turn a test or the
// preview scripts, attachments and the account's files, memory and operations. The real
// platform client runs over it (the fixtures' client, holding no key), so the chat is exercised through the SDK as it is
// in the app.
import type { NoClick } from 'noclick';
import { workFixtureClient } from '@/screens/work/fixtures/client';

type Json = Record<string, unknown>;

export const AGENT_ID = '8d6f1d3a-0c4e-4d55-9a5b-1f6f2c7b9e01';
export const AGENT = { object: 'agent', id: AGENT_ID, name: 'coordinator', user_id: null, status: 'active', origin: 'api', timezone: 'Europe/London', noclick: true };

/** One live event, as the conversation's stream sends it (`type` is its SSE event name). */
export type LiveEvent = Json & { type: string };

/** What a sent message's turn does: its moments (given its operation's id), then its reply or its error. */
/** A turn's script: what it streams, then its reply, or its failure (`errorType` the platform's error type, `internal` by
 *  default: one with no reason a person can act on). */
export type Turn = (turn: string, body: Json) => { events?: LiveEvent[]; reply?: string; error?: string; errorType?: string; hold?: boolean };

export interface FakeCoordinatorAgent {
    client: NoClick;
    /** What answers the client: a lab answers the browser's fetch to the platform with it too. */
    fetch: typeof window.fetch;
    /** Every request the client sent. */
    requests: { method: string; path: string; query: URLSearchParams; body: unknown }[];
    /** The conversation's stored messages, as history returns them. */
    history: Json[];
    /** The account's files, as GET /v1/attachments lists them. */
    files: Json[];
    /** The agent as GET reads it and PATCH changes it. */
    agent: Json;
    memories: Map<string, Json>;
    operations: Map<string, Json>;
    /** Send events to every open stream of the conversation. */
    emit: (...events: LiveEvent[]) => void;
    /** The moments the stream keeps (every event but a message, which the conversation keeps), oldest first: what a
     *  watch with `replay` hears first. */
    streamed: LiveEvent[];
    /** End every open stream, as a dropped connection does. */
    drop: () => void;
    /** Settle an operation (a followed long action) and answer whoever waits on it. */
    settle: (id: string, status: string, extra?: Json) => void;
    /** How many streams are open. */
    watching: () => number;
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
/** The calls a turn's moments made, as its reply keeps them: each call with the result that answered it. */
function callsOf(events: readonly LiveEvent[]): Json[] {
    return events.flatMap((e, i) => {
        if (e.type !== 'tool_call') return [];
        const answer = events.slice(i + 1).find((r) => r.type === 'tool_result' && r.tool === e.tool);
        return [{ tool: e.tool, arguments: e.arguments ?? {}, result: answer?.result ?? null, is_error: false }];
    });
}

const notFound = (message: string) => json({ error: { type: 'not_found', message } }, 404);
const TERMINAL = new Set(['succeeded', 'failed', 'canceled', 'expired']);

/** More of /v1 than the coordinator's own: answers a request it knows, else undefined (`signal`: the request's own,
 *  aborted when its reader stops, as a stream's is). */
export type ExtraRoutes = (method: string, path: string, query: URLSearchParams, body: unknown, signal?: AbortSignal | null) => Response | Promise<Response> | undefined;

export function fakeCoordinatorAgent(
    options: {
        exists?: boolean;
        agent?: Json;
        history?: Json[];
        /** Moments the stream already keeps when the page opens (turns of the last hour, one maybe still at work). */
        streamed?: LiveEvent[];
        files?: Json[];
        memories?: Json[];
        operations?: Json[];
        turn?: Turn;
        at?: () => string;
        routes?: ExtraRoutes;
    } = {}
): FakeCoordinatorAgent {
    const at = options.at ?? (() => new Date().toISOString());
    const agent: Json = { ...AGENT, ...options.agent };
    const history = [...(options.history ?? [])];
    const streamed = [...(options.streamed ?? [])];
    const files = [...(options.files ?? [])];
    const noted = new Set<string>();
    const memories = new Map<string, Json>((options.memories ?? []).map((m) => [String(m.name), { version: 1, updated_by: 'console', updated_at: at(), ...m }]));
    const operations = new Map<string, Json>((options.operations ?? []).map((op) => [String(op.id), op]));
    const waiting = new Map<string, (() => void)[]>();
    const streams = new Set<ReadableStreamDefaultController<Uint8Array>>();
    const requests: FakeCoordinatorAgent['requests'] = [];
    const encoder = new TextEncoder();
    let made = 0;

    const frame = ({ type, ...data }: LiveEvent) => encoder.encode(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
    const emit = (...events: LiveEvent[]) => {
        for (const event of events) {
            if (event.type !== 'message') streamed.push(event);
            for (const stream of streams) stream.enqueue(frame(event));
        }
    };
    const settle = (id: string, status: string, extra: Json = {}) => {
        operations.set(id, { ...operations.get(id), status, updated_at: at(), ...extra });
        for (const wake of waiting.get(id) ?? []) wake();
        waiting.delete(id);
    };

    const routes = async (method: string, path: string, query: URLSearchParams, body: unknown, signal?: AbortSignal | null): Promise<Response> => {
        const agentPath = `/v1/agents/${AGENT_ID}`;
        const extra = options.routes?.(method, path, query, body, signal);
        if (extra) return extra;
        if (method === 'GET' && path === '/v1/agents') return json({ object: 'list', data: options.exists === false ? [] : [agent] });
        // Its one session, `owner`, listed by the agent's name or its id (by name, a new account's is none: a 404).
        const sessions = { object: 'list', data: [{ object: 'agent_conversation', conversation: 'owner', title: null, preview: null, active: true, archived: false, people: [] }], next_cursor: null };
        if (method === 'GET' && (path === `/v1/agents/${encodeURIComponent('agent:coordinator')}/conversations` || path === `/v1/agents/${AGENT_ID}/conversations`))
            return options.exists === false && path !== `/v1/agents/${AGENT_ID}/conversations` ? notFound('No such agent.') : json(sessions);
        // The owner conversation read by the agent's name, as /v1 reads an `agent:<name>` ref (no ensure: none, a 404).
        if (method === 'GET' && path === `/v1/agents/${encodeURIComponent('agent:coordinator')}/conversations/owner`)
            return options.exists === false ? notFound('No such agent.') : json({ object: 'conversation', id: 'owner', agent_id: AGENT_ID, messages: history });
        if (method === 'GET' && path === '/v1/attachments') {
            const q = query.get('query')?.toLowerCase();
            return json({ object: 'list', data: files.filter((f) => !q || String(f.name).toLowerCase().includes(q)), next_cursor: null });
        }
        if (!path.startsWith(agentPath) && !path.startsWith('/v1/operations/')) return notFound(`No route for ${method} ${path}`);
        if (method === 'GET' && path === agentPath) return json(agent);
        if (method === 'PATCH' && path === agentPath) return json(Object.assign(agent, body as Json));
        if (method === 'GET' && path === `${agentPath}/conversations/owner`) return json({ object: 'conversation', id: 'owner', agent_id: AGENT_ID, messages: history });
        // What its harness asks a person, and its commands: NoClick's own harness asks nothing and offers none.
        if (method === 'GET' && path === `${agentPath}/conversations/owner/requests`) return json({ object: 'list', data: [] });
        if (method === 'GET' && path === `${agentPath}/conversations/owner/commands`) return json({ harness: 'sdk', commands: [] });
        if (method === 'GET' && path === `${agentPath}/conversations/owner/events`) {
            let mine: ReadableStreamDefaultController<Uint8Array>;
            const stream = new ReadableStream<Uint8Array>({
                start: (controller) => {
                    mine = controller;
                    if (query.get('replay') === '1') for (const event of streamed) controller.enqueue(frame(event));
                    streams.add(controller);
                },
                cancel: () => {
                    streams.delete(mine);
                },
            });
            signal?.addEventListener('abort', () => {
                if (streams.delete(mine)) mine.close();
            });
            return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
        }
        if (method === 'POST' && path === `${agentPath}/messages`) {
            const sent = body as Json;
            // Words that join the turn at work (steer) go into it, as the person's, and start nothing; with no turn
            // at work they're an ordinary message.
            const atWork = [...operations.values()].find((o) => o.kind === 'agent.message' && !TERMINAL.has(String(o.status)));
            if (sent.delivery === 'steer' && atWork) {
                const joined = { object: 'operation', id: `op-ask-${++made}`, kind: 'agent.ask', status: 'succeeded', created_at: at(), updated_at: at() };
                history.push({ role: 'user', text: sent.text, created_at: at(), operation_id: atWork.id });
                setTimeout(() => emit({ type: 'message', role: 'user', text: sent.text as string, operation_id: atWork.id as string }), 0);
                return json(joined, 202);
            }
            const id = `op-turn-${++made}`;
            const operation = { object: 'operation', id, kind: 'agent.message', status: 'running', created_at: at(), updated_at: at() };
            operations.set(id, operation);
            const files = (sent.attachments as string[] | undefined) ?? [];
            history.push({ role: 'user', text: sent.text, created_at: at(), operation_id: id, ...(files.length ? { files: files.map((f) => ({ id: f, name: f, mime_type: 'application/pdf', url: `https://files.test/${f}` })) } : {}) });
            const script = options.turn?.(id, sent) ?? { reply: 'Done.' };
            // The turn runs once the send has answered, as it does on the server.
            setTimeout(() => {
                emit({ type: 'message', role: 'user', text: sent.text as string, operation_id: id });
                emit(...(script.events ?? []));
                // Held at work: the test ends it (settle), or it's stopped.
                if (script.hold) return;
                if (script.error) {
                    settle(id, 'failed', { error: { type: script.errorType ?? 'internal', message: script.error } });
                    return;
                }
                // Its reply carries the calls it made, in the conversation, on the stream and in its operation's result.
                const calls = callsOf(script.events ?? []);
                const made = calls.length ? { tool_calls: calls } : {};
                history.push({ role: 'assistant', text: script.reply ?? '', created_at: at(), operation_id: id, ...made });
                emit({ type: 'message', role: 'assistant', text: script.reply ?? '', operation_id: id, ...made });
                settle(id, 'succeeded', { result: { text: script.reply ?? '', conversation: 'owner', tool_calls: calls, operation_id: id } });
            }, 0);
            return json(operation, 202);
        }
        if (method === 'POST' && path === `${agentPath}/conversations/owner/notes`) {
            const note = body as Json;
            const key = String(note.key ?? `note-${++made}`);
            const added = !noted.has(key);
            if (added) {
                noted.add(key);
                history.push({ role: 'note', text: note.text, created_at: at(), ...(note.data ? { data: note.data } : {}) });
                emit({ type: 'message', role: 'note', text: note.text as string, ...(note.data ? { data: note.data as Json } : {}), operation_id: null });
            }
            return json({ object: 'note', agent_id: AGENT_ID, conversation: 'owner', key, text: note.text, added }, 201);
        }
        if (method === 'POST' && path === `${agentPath}/attachments`) {
            const name = query.get('name') ?? 'file';
            const mime = query.get('mime_type') ?? 'application/octet-stream';
            return json({ object: 'attachment', id: `att-${++made}`, name, mime_type: mime, size_bytes: 12, url: `https://files.test/${name}` }, 201);
        }
        const memoryName = path.startsWith(`${agentPath}/memory/`) ? decodeURIComponent(path.slice(`${agentPath}/memory/`.length)) : null;
        if (method === 'GET' && path === `${agentPath}/memory`) {
            const q = query.get('q')?.toLowerCase();
            const rows = [...memories.values()].filter((m) => !q || JSON.stringify(m).toLowerCase().includes(q));
            return json({ object: 'list', data: rows.map((m) => (q ? m : { ...m, content: null })) });
        }
        if (memoryName && method === 'GET') return memories.has(memoryName) ? json(memories.get(memoryName)) : notFound(`No memory is named ${memoryName}.`);
        if (memoryName && method === 'PUT') {
            const write = body as Json;
            const current = memories.get(memoryName);
            if (write.version !== undefined && Number(current?.version) !== write.version) return json({ error: { type: 'conflict', message: 'It changed.' } }, 409);
            const saved = { name: memoryName, description: write.description ?? current?.description ?? '', content: write.content, version: Number(current?.version ?? 0) + 1, updated_by: 'console', updated_at: at(), conversation: null };
            memories.set(memoryName, saved);
            return json(saved);
        }
        if (memoryName && method === 'DELETE') {
            if (!memories.delete(memoryName)) return notFound(`No memory is named ${memoryName}.`);
            return new Response(null, { status: 204 });
        }
        const canceled = path.match(/^\/v1\/operations\/([^/]+)\/cancel$/);
        if (canceled && method === 'POST') {
            if (!operations.has(canceled[1])) return notFound(`No operation ${canceled[1]}.`);
            settle(canceled[1], 'canceled', { error: { type: 'operation_canceled', message: 'Canceled.' } });
            return json(operations.get(canceled[1]));
        }
        const operationId = path.match(/^\/v1\/operations\/([^/]+)(\/wait)?$/);
        if (operationId && method === 'GET') {
            const [, id, wait] = operationId;
            if (!operations.has(id)) return notFound(`No operation ${id}.`);
            if (wait && !TERMINAL.has(String(operations.get(id)!.status))) {
                await new Promise<void>((resolve) => {
                    waiting.set(id, [...(waiting.get(id) ?? []), resolve]);
                    signal?.addEventListener('abort', () => resolve());
                });
            }
            return json(operations.get(id));
        }
        return notFound(`No route for ${method} ${path}`);
    };

    const fetch: typeof window.fetch = async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
        const method = (init?.method ?? 'GET').toUpperCase();
        const raw = init?.body;
        const body = typeof raw === 'string' ? JSON.parse(raw) : raw;
        requests.push({ method, path: url.pathname, query: url.searchParams, body });
        return routes(method, url.pathname, url.searchParams, body, init?.signal);
    };

    return {
        client: workFixtureClient(fetch),
        fetch,
        requests,
        history,
        files,
        agent,
        memories,
        operations,
        emit,
        streamed,
        drop: () => {
            for (const stream of streams) stream.close();
            streams.clear();
        },
        settle,
        watching: () => streams.size,
    };
}
