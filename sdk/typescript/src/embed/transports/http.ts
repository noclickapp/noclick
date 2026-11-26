// HTTP transport: the bridge's calls made on the platform API (`/v1`) with the page's key, through the SDK's own
// client; what changes while the page is open comes as room frames (`Room`), never by reading again: its pages' room
// (`page:{workflow}`) for State changes, and each run's own (`run:{operation}`) for its steps. Published pages use it,
// and it's what an apiKey with no transport picks.

import { NoClick } from '../../client.ts';
import { Room } from '../../room.ts';
import type { RoomEvent } from '../../room.ts';
import type { Transport } from '../core/transport.js';

export interface HttpTransportOptions {
  /** The platform API (`https://api.noclick.com` by default). */
  url?: string;
  /** The page's key. */
  apiKey: string;
  /** The workflow the page is of. */
  workflowId: string;
}

type Json = Record<string, any>;
type Params = Record<string, unknown>;
type Handler = (msg: Record<string, unknown>) => void;

const ENDED = new Set(['completed', 'error', 'skipped']);
const NO_CONNECTIONS = "A published app's page doesn't reach the account's connections: pre-configure them in the workflow editor.";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export class HttpTransport implements Transport {
  readonly client: NoClick;
  private readonly workflowId: string;
  private readonly handlers = new Set<Handler>();
  /** The runs this page started that are still going, by run id. */
  private readonly running = new Set<string>();
  private readonly rooms = new Set<Room>();

  constructor(options: HttpTransportOptions) {
    this.client = new NoClick({ apiKey: options.apiKey, baseUrl: options.url ?? 'https://api.noclick.com' });
    this.workflowId = options.workflowId;
  }

  /** Join its pages' room, whose `state:changed` frames reach the page; without one the page reads state as it asks. */
  async connect(): Promise<void> {
    try {
      const room = await Room.join(`page:${this.workflowId}`, { client: this.client });
      this.rooms.add(room);
      room.on('event', (event) => {
        if (event.event === 'state:changed') this.emit({ type: 'noclick:event', event: 'state:changed', data: event.data });
      });
    } catch (e) {
      console.warn('[NoClick SDK] live state changes are off:', message(e));
    }
  }

  send(msg: Record<string, unknown>): void {
    const method = msg.method as string;
    const params = (msg.params ?? {}) as Params;
    if (msg.type === 'noclick:fire') {
      if (method === 'execution.runNodesInBackground') this.start(params).catch((e) => console.error('[NoClick SDK]', message(e)));
      return;
    }
    if (msg.type !== 'noclick:request') return;
    const id = msg.id as string;
    if (method === 'execution.runNodesAndGetOutput') {
      this.follow(id, params);
      return;
    }
    const call = this.calls[method];
    if (!call) {
      this.emit({ type: 'noclick:response', id, error: `Method '${method}' isn't available to a published app.` });
      return;
    }
    call(params).then(
      (result) => this.emit({ type: 'noclick:response', id, result }),
      (e) => this.emit({ type: 'noclick:response', id, error: message(e) }),
    );
  }

  onMessage(handler: Handler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  destroy(): void {
    for (const room of this.rooms) room.leave();
    this.rooms.clear();
    this.handlers.clear();
  }

  private emit(msg: Record<string, unknown>): void {
    this.handlers.forEach((fn) => fn(msg));
  }

  private get path(): string {
    return `/v1/workflows/${this.workflowId}`;
  }

  private api<T = Json>(method: string, path: string, options: { json?: unknown; query?: Record<string, any> } = {}): Promise<T> {
    return this.client.request<T>(method, path, { ...options, user: null } as any);
  }

  private stateQuery(params: Params) {
    return params.node ? { step_id: params.node as string } : {};
  }

  private readonly calls: Record<string, (p: Params) => Promise<unknown>> = {
    'workflow.getInfo': async () => {
      const read = await this.api('GET', `${this.path}/graph`);
      return { id: this.workflowId, name: read.name, nodeCount: (read.graph?.nodes ?? []).length };
    },
    'nodes.list': async () => {
      const [read, latest] = await Promise.all([
        this.api('GET', `${this.path}/graph`),
        this.api('GET', `${this.path}/outputs`).catch(() => ({ outputs: {} })),
      ]);
      const outputs = latest.outputs ?? {};
      return (read.graph?.nodes ?? [])
        .filter((n: Json) => n.type && !String(n.type).startsWith('collaborator'))
        .map((n: Json) => ({ id: n.id, type: n.type, label: n.config?.label || n.type, hasOutput: n.id in outputs }));
    },
    'nodes.getOutput': async (p) => {
      const latest = await this.api('GET', `${this.path}/outputs`, { query: { steps: p.nodeId, full: true } });
      return latest.outputs?.[p.nodeId as string] ?? null;
    },
    'nodes.getConfig': async (p) => (await this.api('GET', `${this.path}/steps/${p.nodeId}`)).step?.config ?? {},
    'nodes.setConfig': async (p) => {
      await this.api('POST', `${this.path}/edits`, { json: { ops: [{ op: 'update_step', id: p.nodeId, settings: p.config }] } });
      return null;
    },
    'execution.stop': async () => {
      await Promise.all([...this.running].map((run) => this.api('POST', `${this.path}/runs/${run}/stop`).catch(() => null)));
      return null;
    },
    'state.get': async (p) => (await this.api('GET', `${this.path}/state`, { query: this.stateQuery(p) })).values?.[p.key as string],
    'state.keys': async (p) => Object.keys((await this.api('GET', `${this.path}/state`, { query: this.stateQuery(p) })).values ?? {}),
    'state.set': async (p) => this.setState(p.key as string, p.value ?? null, p.node as string | undefined),
    'state.delete': async (p) => this.setState(p.key as string, null, p.node as string | undefined),
    'auth.listCredentials': async () => {
      throw new Error(NO_CONNECTIONS);
    },
    'auth.hasCredential': async () => {
      throw new Error(NO_CONNECTIONS);
    },
    'auth.createCredential': async () => {
      throw new Error(NO_CONNECTIONS);
    },
    'auth.requestCredential': async () => {
      throw new Error('auth.requestCredential (OAuth flow) is not supported in published apps. Use auth.createCredential for API key credentials, or pre-configure OAuth credentials in the workflow editor.');
    },
    'resources.list': async (p) => {
      const files = await this.list('/v1/workflows/files');
      return files
        .filter((f) => !p.resourceType || f.type === p.resourceType)
        .map((f) => ({ id: f.id, name: f.name, resourceType: f.type, mimeType: f.mime_type ?? null, sizeBytes: f.size_bytes ?? null }));
    },
    'resources.upload': async (p) => {
      const made = await this.api('POST', `${this.path}/files`, {
        json: { name: p.name, mime_type: p.mimeType, size_bytes: p.sizeBytes, ...(p.resourceType && p.resourceType !== 'file' ? { type: p.resourceType } : {}) },
      });
      return { resourceId: made.id, uploadUrl: made.upload_url };
    },
    'resources.getUrl': async (p) => (await this.api('GET', `/v1/workflows/files/${p.resourceId}`)).url,
    'resources.remove': async (p) => {
      await this.api('DELETE', `/v1/workflows/files/${p.resourceId}`);
      return null;
    },
    'dataset.list': async () =>
      (await this.list('/v1/workflows/tables')).map((t) => ({ id: t.id, name: t.name, rowCount: t.row_count ?? 0 })),
    'dataset.create': async (p) => (await this.api('POST', `${this.path}/tables`, { json: { name: p.name } })).id,
    'dataset.getRows': async (p) => {
      const offset = Number(p.offset ?? 0);
      const page = await this.api('GET', `/v1/workflows/tables/${p.resourceId}/rows`, {
        query: { limit: p.limit ?? 100, ...(offset ? { cursor: String(offset) } : {}) },
      });
      return {
        rows: (page.data ?? []).map((r: Json) => ({ id: r.id, row_index: r.index, data: r.data, created_at: r.created_at })),
        totalCount: page.total_count ?? 0,
      };
    },
    'dataset.appendRows': async (p) => {
      const added = await this.api('POST', `/v1/workflows/tables/${p.resourceId}/rows`, { json: { rows: p.rows } });
      return { insertedCount: added.added };
    },
    'dataset.updateRow': async (p) => {
      await this.api('PATCH', `/v1/workflows/tables/${p.resourceId}/rows/${p.rowId}`, { json: { data: p.data } });
      return null;
    },
    'dataset.deleteRows': async (p) => {
      const removed = await this.api('POST', `/v1/workflows/tables/${p.resourceId}/rows/remove`, { json: { row_ids: p.rowIds } });
      return { deletedCount: removed.removed };
    },
  };

  private async setState(key: string, value: unknown, node?: string): Promise<null> {
    await this.api('PUT', `${this.path}/state/${encodeURIComponent(key)}`, { json: { value, ...(node ? { step_id: node } : {}) } });
    // This page hears its own write at once; the others hear it through the room.
    this.emit({ type: 'noclick:event', event: 'state:changed', data: { key, value: value ?? undefined } });
    return null;
  }

  private async list(path: string): Promise<Json[]> {
    const found: Json[] = [];
    let cursor: string | undefined;
    do {
      const page = await this.api('GET', path, {
        query: { workflow_id: this.workflowId, limit: 100, ...(cursor ? { cursor } : {}) },
      });
      found.push(...(page.data ?? []));
      cursor = page.next_cursor ?? undefined;
    } while (cursor);
    return found;
  }

  /** Start a run from the first of `runNodes`, their inline configs laid over for this run alone: its operation. */
  private async start(params: Params): Promise<Json> {
    const runNodes = (params.runNodes ?? []) as Array<{ id: string; config?: Record<string, unknown> }>;
    const settings: Record<string, Record<string, unknown>> = {};
    for (const ref of runNodes) if (ref.config) settings[ref.id] = ref.config;
    return await this.api('POST', `${this.path}/runs`, {
      json: {
        ...(runNodes[0] ? { from_step: runNodes[0].id } : {}),
        manual: { background: true, ...(Object.keys(settings).length ? { settings } : {}) },
      },
    });
  }

  /**
   * Run, then follow it in its own room (joined as it starts; what it said before is read once from the room's history,
   * as it is again after a reconnect), telling the page each step's state and output, and at its end the targets'
   * whole outputs, read once each.
   */
  private follow(id: string, params: Params): void {
    const targets = (params.targetNodes ?? []) as string[];
    const stream = (event: string, nodeId?: string, data?: unknown) =>
      this.emit({ type: 'noclick:stream', id, event, ...(nodeId ? { nodeId } : {}), ...(data !== undefined ? { data } : {}) });
    const fail = (error: string) => stream('error', targets[0] ?? 'unknown', error);
    (async () => {
      const op = await this.start(params);
      const room = await Room.join(`run:${op.id}`, { client: this.client });
      this.rooms.add(room);
      const heard = new Set<string>();
      const states: Record<string, string> = {};
      let runId: string | null = null;
      let over = false;
      const end = () => {
        over = true;
        if (runId) this.running.delete(runId);
        room.leave();
        this.rooms.delete(room);
      };
      const finish = async (frame: Json) => {
        end();
        const failed = targets.find((t) => states[t] === 'error');
        if (failed) return stream('error', failed, `Node ${failed} failed`);
        if (frame.status !== 'succeeded' && !targets.every((t) => ENDED.has(states[t]))) {
          return fail(frame.error || 'The run failed.');
        }
        for (const t of targets.filter((t) => states[t] === 'completed')) {
          const whole = await this.api('GET', `${this.path}/steps/${t}/outputs/${frame.run_id ?? runId}`);
          stream('output', t, whole.output);
        }
        stream('done');
      };
      const hear = (event: RoomEvent) => {
        if (over || heard.has(event.id)) return;
        heard.add(event.id);
        const frame = (event.data ?? {}) as Json;
        if (frame.run_id && !runId) {
          runId = frame.run_id as string;
          this.running.add(runId);
        }
        if (event.event === 'workflow:node:state') {
          states[frame.node_id] = frame.state;
          this.emit({ type: 'noclick:event', event: 'node:state', data: { nodeId: frame.node_id, state: frame.state } });
          if (frame.state === 'error' && targets.includes(frame.node_id)) {
            end();
            stream('error', frame.node_id, frame.error || `Node ${frame.node_id} failed`);
          }
        } else if (event.event === 'workflow:node:output') {
          this.emit({ type: 'noclick:event', event: 'node:output', data: { nodeId: frame.node_id, output: frame.output } });
        } else if (event.event === 'workflow:complete' && frame.status !== 'running') {
          finish(frame).catch((e) => fail(message(e)));
        }
      };
      const catchUp = async () => (await room.history()).events.forEach(hear);
      let away = false;
      room.on('event', hear);
      room.on('status', (status) => {
        if (status === 'reconnecting') away = true;
        if (status === 'live' && away) {
          away = false;
          catchUp().catch((e) => console.warn('[NoClick SDK]', message(e)));
        }
      });
      await catchUp();
    })().catch((e) => fail(message(e)));
  }
}
