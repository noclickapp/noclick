// A resource the account owns moved: a `platform:resource` frame says which (sdk/frames.ts), and every read showing
// it is read again, whichever screen made the read (keys are namespaced by screen: `resources:…`, `work:…`). Screens
// keep only a slow re-read as the backstop. The frames come from whoever renders the screens (sdk/live.ts).
import type { PlatformResourceEvent } from '@/sdk/frames';

/** How often a page showing something still settling reads it again when no frame came. */
export const BACKSTOP_POLL_MS = 60_000;

/** The reads (by key prefix) a frame makes stale. */
export function staleReads(frame: Pick<PlatformResourceEvent, 'kind' | 'id' | 'parent_id'>): string[] {
    switch (frame.kind) {
        case 'domain':
            // Its apps too: an app's URL and the names it's live at move with its domains.
            return ['domains?', `domains/${frame.id}`, 'projects?', 'resources:domains', 'resources:projects', 'account'];
        case 'deployment':
            // A release going live gives its app's Durable Objects its code and migrations: their classes move too.
            return [
                'projects?',
                ...(frame.parent_id ? [`projects/${frame.parent_id}/deployments`, `projects/${frame.parent_id}/durable_objects`] : []),
                `deployments/${frame.id}`,
                'resources:projects',
            ];
        case 'repo':
            // Its list rows, everything its drawer reads (files, commits, branches) and Resources' list, whose re-read gives its page a new reader.
            return ['repos?', `repos/${frame.id}`, 'resources:repos', 'account'];
        case 'mcp_server':
            // A client reached it: its list rows, its own read and its clients.
            return ['mcp_servers?', `mcp_servers/${frame.id}`];
        case 'phone_call':
            // Picked up, a turn said, ended: its number's calls and its own read.
            return [...(frame.parent_id ? [`phone_numbers/${frame.parent_id}/calls`] : []), `phone_numbers/calls/${frame.id}`];
        case 'durable_object_class':
            // Stopped, started, into the trash or out of it: its app's classes in either surface, and Resources' trash.
            return frame.parent_id ? [`projects/${frame.parent_id}/durable_objects`, `resources:projects/${frame.parent_id}/durable_objects`, 'resources:trash'] : [];
        case 'workflow':
            // Its graph was written: its list rows and everything read under it (its graph, its versions).
            return ['workflows?', `workflows/${frame.id}`];
        case 'machine':
            // A status move (your own server online or offline, a code used, a removal): its rows and its own read, and
            // what runs where (Resources' machines, a space's).
            return ['machines?', `machines/${frame.id}`, 'resources:machines', 'resources:compute'];
        case 'sandbox':
            // An agent's sandbox came up or went down.
            return ['resources:compute'];
        case 'skill':
            // Saved, attached, detached or deleted: its list, and the agents whose links moved.
            return ['resources:skills', 'work:agents'];
        case 'memory':
            return ['resources:memories', 'work:agents'];
        default:
            return [];
    }
}
