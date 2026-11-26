// Whose word an agent's call acted on, where its turn carried several people's words and it cited one of them
// (NoClick's `authorized_by`: the tool's result says so as `authority`). The step's row reads it as "on Ana's word".

/** The person a call acted for, their words it quoted, and the agent's own why. */
export interface CitedWord {
    author: string;
    quote: string;
    why: string;
}

function read(result: unknown): Record<string, unknown> | null {
    if (typeof result === 'string') {
        try {
            return read(JSON.parse(result));
        } catch {
            return null;
        }
    }
    return result && typeof result === 'object' && !Array.isArray(result) ? (result as Record<string, unknown>) : null;
}

/** The word a call acted on, read from its result; null where it acted as its turn does. */
export function citedWord(result: unknown): CitedWord | null {
    const authority = read(read(result)?.authority);
    if (authority?.basis !== 'cited' || typeof authority.author !== 'string' || typeof authority.quote !== 'string') return null;
    return { author: authority.author, quote: authority.quote, why: typeof authority.why === 'string' ? authority.why : '' };
}
