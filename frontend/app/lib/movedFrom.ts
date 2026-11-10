// What an agent's move from a computer stamps on everything it carried over (a model key's connection, a secret, a
// tool server's sign-in): the computer, the folder its session ran in, when, and where the copy puts it. Every page
// that lists one says so the same way, so people can tell what came over and take its access away.

/** Where the copy puts it: an environment variable, a file, the agent's model key, or a tool server's sign-in. */
export interface MovedTo {
    env?: string;
    file?: string;
    mode?: string;
    model?: string;
    toolServer?: string;
}

export interface MovedFrom {
    /** The move that carried it (`GET /v1/agents/moves/{id}` while the move is kept). */
    moveId: string | null;
    /** The computer it came from, by host name. */
    host: string | null;
    /** The folder its session ran in there. */
    folder: string | null;
    at: string | null;
    to: MovedTo | null;
}

const text = (v: unknown) => (typeof v === 'string' && v ? v : null);

/** A `moved_from` as the API or a credential's metadata holds it, or null when it wasn't moved. */
export function movedFrom(raw: unknown): MovedFrom | null {
    if (!raw || typeof raw !== 'object') return null;
    const m = raw as Record<string, unknown>;
    const to = m.to && typeof m.to === 'object' ? (m.to as Record<string, unknown>) : null;
    return {
        moveId: text(m.move_id),
        host: text(m.host),
        folder: text(m.folder),
        at: text(m.at),
        to: to ? { env: text(to.env) ?? undefined, file: text(to.file) ?? undefined, mode: text(to.mode) ?? undefined, model: text(to.model) ?? undefined, toolServer: text(to.tool_server) ?? undefined } : null,
    };
}

/** "Nov 9", or "Nov 9, 2025" outside this year. */
export function movedDate(at: string, now = new Date()): string {
    const d = new Date(at);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', ...(d.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }) });
}

/** "Moved from studio-mbp · Nov 9". */
export function movedLine(m: MovedFrom): string {
    return [`Moved from ${m.host ?? 'a computer'}`, m.at ? movedDate(m.at) : null].filter(Boolean).join(' · ');
}

/** Its facts on a page: the computer, the folder and when. */
export function movedFacts(m: MovedFrom): [string, string][] {
    return [
        ['Moved from', m.host ?? 'A computer'],
        ...((m.folder ? [['Folder there', m.folder]] : []) as [string, string][]),
        ...((m.at ? [['Moved', movedDate(m.at)]] : []) as [string, string][]),
    ];
}
