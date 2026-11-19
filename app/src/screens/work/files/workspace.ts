// An agent's one /workspace as Work reads it (`agent.workspace(session)`, its active session's, though every session
// shares the folder), and where each file in it came from, read from its path alone: WhatsApp's inbox writer keeps a
// chat's files at `inbox/<chat-folder>/…` (backend `utils/agent_inbox.py`), the Files view uploads into `added/`, and
// everything else is the agent's own work. Nothing else records it.
import type { NoClick } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import type { FileEntry } from '@/screens/resources/files';
import { fileKindOf } from '@/lib/embedKind';
import { listedAgent, useWorkV1 } from '../agents/reads';
import { useWorkFrames } from '@/sdk/live';
import { useActiveSession } from '../conversation/sessions';

/** Where the Files view puts what you upload. */
export const ADDED = 'added';
const INBOX = 'inbox';
/** A chat's folder: its name or number made safe for a shell, then six hex of the chat's id (`asha-3f9c2a`). */
const CHAT_FOLDER = /^(.+)-[0-9a-f]{6}$/;
/** A file someone sent: in the inbox, or in an earlier per-chat workspace the one-session cutover kept under `earlier/<chat>/`. */
const SENT = /^(?:earlier\/[^/]+\/)?inbox\/([^/]+)\/[^/]+$/;

export const workspaceKey = (agentId: string) => `work:agent:${agentId}:workspace`;

/** Every file in the agent's workspace, newest first, each with its signed link. */
export async function readWorkspace(client: NoClick, agentId: string, session: string): Promise<FileEntry[]> {
    const files = await listedAgent(client, agentId).workspace(session).files();
    return files
        .map((f) => ({ path: f.path, size: f.sizeBytes, mtime: (f.modifiedAt ?? new Date(0)).toISOString(), kind: fileKindOf(f.path), url: f.url }))
        .sort((a, b) => b.mtime.localeCompare(a.mtime));
}

/** The agent's workspace, read again as each of its turns moves (a turn writes files, and a file someone sends wakes one). */
export function useAgentWorkspace(agentId: string) {
    const session = useActiveSession(agentId);
    useWorkFrames('platform:agent', (frame) => {
        if (frame.agent_id === agentId && frame.change === 'turn') invalidateV1(workspaceKey(agentId));
    });
    return useWorkV1(session ? workspaceKey(agentId) : null, (client) => readWorkspace(client, agentId, session!));
}

/** A chat's name from its folder: the part before its id, as words ("book-club-07d1e4" → "Book Club"), a number with its +. */
export function chatName(folder: string): string {
    const named = CHAT_FOLDER.exec(folder)?.[1] ?? folder;
    if (/^\d+$/.test(named)) return `+${named}`;
    return named
        .split(/[-_.]+/)
        .filter(Boolean)
        .map((w) => w[0].toUpperCase() + w.slice(1))
        .join(' ');
}

/** What a folder is called, by its path (`inbox/asha-3f9c2a`): the inbox, a chat in it by the chat's name, what you added; the rest as named. */
export function folderLabel(path: string): string {
    const parts = path.replace(/\/$/, '').split('/');
    const name = parts[parts.length - 1];
    if (name === INBOX) return 'Inbox';
    if (parts.length === 1 && name === ADDED) return 'Added by you';
    if (parts[parts.length - 2] === INBOX) return chatName(name);
    return name;
}

export type FileOrigin = { by: 'whatsapp'; chat: string } | { by: 'you' } | { by: 'agent' };

export function originOf(path: string): FileOrigin {
    const sent = SENT.exec(path);
    if (sent) return { by: 'whatsapp', chat: chatName(sent[1]) };
    return path.startsWith(`${ADDED}/`) ? { by: 'you' } : { by: 'agent' };
}

/** Where a file came from, in a sentence; `short` for a row, where a sent file's mark says the app. */
export function originLine(origin: FileOrigin, agentName: string, short = false): string {
    if (origin.by === 'whatsapp') return short ? origin.chat : `Sent on WhatsApp in ${origin.chat}`;
    return origin.by === 'you' ? 'Added in NoClick' : `Made by ${agentName}`;
}
