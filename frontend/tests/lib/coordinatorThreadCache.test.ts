// The coordinator's thread as this browser keeps it: per account the page acts as and per kind of chat, the settled
// turns' words and calls without their files, pictures or live-only parts, dropped when its shape changes, and storage
// that's missing, slow or throwing reads as no copy.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentChatMessage } from '~/hooks/useAgentChat';

const stored = new Map<string, unknown>();
const storage = {
    get: vi.fn(async (key: string) => stored.get(key) ?? null),
    set: vi.fn(async (key: string, value: unknown) => void stored.set(key, value)),
    delete: vi.fn(async (key: string) => void stored.delete(key)),
};
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: (k: string) => storage.get(k), set: (k: string, v: unknown) => storage.set(k, v), delete: (k: string) => storage.delete(k) } }));

import { CACHED_THREAD_VERSION, cachedThreadKey, readCachedThread, writeCachedThread } from '~/lib/coordinatorThreadCache';

const said = (text: string, extra: Partial<AgentChatMessage> = {}): AgentChatMessage => ({ isUser: false, text, isComplete: true, ...extra });
const flush = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
    stored.clear();
    vi.clearAllMocks();
});
afterEach(() => vi.useRealTimers());

describe('the coordinator thread this browser keeps', () => {
    it('keys it by the account and the kind of chat: neither reads another’s', async () => {
        writeCachedThread('customer-9', 'owner', [said('the customer’s')], 'agent');
        writeCachedThread('staff-1', 'owner', [said('the staff member’s')], 'agent');
        writeCachedThread('customer-9', 'conv-1', [said('the socket chat’s')]);
        await flush();
        expect([...stored.keys()].sort()).toEqual([cachedThreadKey('customer-9'), cachedThreadKey('customer-9', 'agent'), cachedThreadKey('staff-1', 'agent')].sort());
        expect((await readCachedThread('customer-9', 'agent'))?.messages.map((m) => m.text)).toEqual(['the customer’s']);
        expect((await readCachedThread('staff-1', 'agent'))?.messages.map((m) => m.text)).toEqual(['the staff member’s']);
        expect(await readCachedThread('someone-else', 'agent')).toBeNull();
    });

    it('keeps the settled turns’ words and calls, never their files, pictures or what only streamed live', async () => {
        writeCachedThread('acct', 'owner', [
            said('Here it is.', {
                attachments: [{ name: 'plan.pdf', url: 'https://api.test/f/sealed-token/plan.pdf' }],
                content: [{ type: 'image_url', image_url: { url: 'https://api.test/f/sealed-token/pic.png' } }],
                thoughts: [{ text: 'thinking', at: 1 }],
                status: 'Working…',
                steps: [{ id: 's1', kind: 'tool', label: 'api_call' } as unknown as NonNullable<AgentChatMessage['steps']>[number]],
            }),
            said('still writing', { isComplete: false }),
        ], 'agent');
        await flush();
        const copy = (await readCachedThread('acct', 'agent'))!;
        expect(copy.messages).toHaveLength(1);
        expect(copy.messages[0]).toMatchObject({ text: 'Here it is.', steps: [{ id: 's1' }] });
        expect(copy.messages[0]).not.toHaveProperty('attachments');
        expect(copy.messages[0]).not.toHaveProperty('content');
        expect(copy.messages[0]).not.toHaveProperty('thoughts');
        expect(copy.messages[0]).not.toHaveProperty('status');
        expect(JSON.stringify(stored.get(cachedThreadKey('acct', 'agent')))).not.toMatch(/sealed-token/);
    });

    it('drops a copy of another shape', async () => {
        stored.set(cachedThreadKey('acct', 'agent'), { version: CACHED_THREAD_VERSION - 1, conversationId: 'owner', messages: [said('old')] });
        expect(await readCachedThread('acct', 'agent')).toBeNull();
        expect(stored.has(cachedThreadKey('acct', 'agent'))).toBe(false);
    });

    it('reads as no copy when storage throws or hangs, and writes nothing when it refuses', async () => {
        storage.get.mockRejectedValueOnce(new Error('private mode'));
        expect(await readCachedThread('acct', 'agent')).toBeNull();
        vi.useFakeTimers();
        storage.get.mockReturnValueOnce(new Promise(() => undefined));
        const waiting = readCachedThread('acct', 'agent');
        await vi.advanceTimersByTimeAsync(300);
        expect(await waiting).toBeNull();
        vi.useRealTimers();
        storage.set.mockRejectedValueOnce(new Error('quota'));
        expect(() => writeCachedThread('acct', 'owner', [said('x')], 'agent')).not.toThrow();
        await flush();
    });
});
