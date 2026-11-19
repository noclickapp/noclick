// An agent's memory (agent.memory on /v1) as the memories panel reads and edits it: entries are named, so a name is
// an entry's id, and they have no kind. A rename saves the entry under its new name and forgets the old one at the
// version that was read; a new name never replaces an entry already called that.
import { NotFound, type Agent, type MemoryEntry as AgentMemoryEntry } from 'noclick';
import type { MemoryEntry, MemoryHeader, MemoryTransport } from './useMemories';

const PAGE = 40;

function header(entry: AgentMemoryEntry): MemoryHeader {
    const at = (entry.updatedAt ?? new Date(0)).toISOString();
    return {
        id: entry.name,
        name: entry.name,
        description: entry.description,
        // Unread where memories have no kind.
        memory_type: 'project',
        origin_conversation_id: entry.updatedBy === 'agent' ? (entry.conversation ?? '') : null,
        version: entry.version,
        created_at: at,
        updated_at: at,
    };
}

function full(entry: AgentMemoryEntry): MemoryEntry {
    return { ...header(entry), content: entry.content ?? '' };
}

async function taken(agent: Agent, name: string): Promise<boolean> {
    try {
        await agent.memory.read(name);
        return true;
    } catch (error) {
        if (error instanceof NotFound) return false;
        throw error;
    }
}

export function agentMemoryTransport(agent: Agent): MemoryTransport {
    return {
        kinds: false,
        names: { pattern: '[a-z0-9._\\-]{1,64}', maxLength: 64, hint: 'Lowercase letters, digits and . _ -' },
        list: async (query, offset) => {
            const words = query.trim();
            const entries = words ? await agent.memory.search(words, { limit: 100 }) : await agent.memory.list();
            return { memories: entries.slice(offset, offset + PAGE).map(header), has_more: entries.length > offset + PAGE };
        },
        get: async (name) => full(await agent.memory.read(name)),
        save: async ({ name, description, content, memory_id, expected_version }) => {
            const named = memory_id === name;
            if (!named && (await taken(agent, name))) throw new Error(`There’s already a memory called ${name}.`);
            const saved = await agent.memory.save(name, content, { description, ...(named && expected_version ? { version: expected_version } : {}) });
            if (memory_id && !named) await agent.memory.delete(memory_id, { version: expected_version ?? undefined });
            return full(saved);
        },
        forget: (name, version) => agent.memory.delete(name, { version }),
    };
}
