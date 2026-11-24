// A stand-in for the dashboard's /v1 client under the Automations page's store (`setWorkflowBrowserClient`): each
// call waits until the test answers it, so a test decides the order answers land in.
import { setWorkflowBrowserClient } from './workflowBrowserStore';

export interface PendingCall {
    method: string;
    path: string;
    query: Record<string, unknown>;
    json: Record<string, unknown> | undefined;
    answer: (body: unknown) => void;
    fail: (message: string) => void;
}

export function installFakeBrowserClient() {
    const calls: PendingCall[] = [];
    const client = {
        request: (method: string, path: string, options: { query?: Record<string, unknown>; json?: Record<string, unknown> } = {}) =>
            new Promise((resolve, reject) =>
                calls.push({
                    method,
                    path,
                    query: options.query ?? {},
                    json: options.json,
                    answer: resolve,
                    fail: (message) => reject(new Error(message)),
                }),
            ),
    };
    setWorkflowBrowserClient(client as never);
    /** The newest call to `path` (by method too), whose query holds every key of `query`. */
    const last = (method: string, path: string, query: Record<string, unknown> = {}) => {
        const found = [...calls]
            .reverse()
            .find((c) => c.method === method && c.path === path && Object.entries(query).every(([k, v]) => c.query[k] === v));
        if (!found) throw new Error(`no ${method} ${path} ${JSON.stringify(query)} among ${calls.map((c) => `${c.method} ${c.path}`).join(', ')}`);
        return found;
    };
    return { calls, last, teardown: () => setWorkflowBrowserClient(null) };
}

/** Let what an answer set going settle (the store's `.then`s). */
export const settle = async () => {
    for (let i = 0; i < 5; i++) await Promise.resolve();
};

/** A workflow as `GET /v1/workflows` lists one. */
export const listed = (id: string, name: string, access = 'owner', extra: Record<string, unknown> = {}) => ({
    object: 'workflow', id, name, description: null, access, owner: access === 'owner' ? null : { name: 'Ada' },
    updated_at: '2026-11-20T10:00:00Z', created_at: '2026-11-20T10:00:00Z', ...extra,
});

export const listing = (data: unknown[], extra: Record<string, unknown> = {}) => ({ object: 'list', data, next_cursor: null, ...extra });
