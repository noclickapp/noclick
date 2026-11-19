// Skills and memories: two skills and a named memory the account's agents share, each skill with its files and
// versions and the memory with its entries. Populated, they're there; empty and first-run, there are none yet.
import { AGENTS, DAY, HOUR, ago, apiError, list, ok, pageList, type FixtureReply, type FixtureRequest, type FixtureRoute } from '../core';

type Json = Record<string, unknown>;

const [SUPPORT, CONCIERGE] = AGENTS;
const by = (agent: { id: string; name: string }) => ({ type: 'agent', agent_id: agent.id, agent_name: agent.name });

const REFUNDS_MD = `---
name: refunds
description: How to refund an order, and when to ask first
---

Refund the full amount when the order is under $500 and was placed in the last 30 days.

Anything larger, or older, goes to a person: say what the customer asked for and why.
`;

const TONE_MD = `---
name: support-tone
description: How replies to customers read
---

Answer in two or three short sentences. Name what you did, then what happens next.
`;

/** Each skill's files at its latest version, by path. */
const FILES: Record<string, Record<string, string>> = {
    sk_refunds: { 'SKILL.md': REFUNDS_MD, 'scripts/refund.py': 'import sys\n\nprint(f"Refunding order {sys.argv[1]}")\n' },
    sk_tone: { 'SKILL.md': TONE_MD },
};

const files = (id: string) => Object.entries(FILES[id] ?? {}).map(([path, content]) => ({ path, size: content.length, sha256: `${id}-${path}` }));
const size = (id: string) => files(id).reduce((sum, f) => sum + f.size, 0);

export const SKILLS: Json[] = [
    {
        object: 'skill',
        id: 'sk_refunds',
        name: 'refunds',
        description: 'How to refund an order, and when to ask first',
        always: false,
        version: 2,
        file_count: files('sk_refunds').length,
        size: size('sk_refunds'),
        attached_to: [
            { id: SUPPORT.id, name: SUPPORT.name, pin: null },
            { id: CONCIERGE.id, name: CONCIERGE.name, pin: 1 },
        ],
        user_id: null,
        created_at: ago(12 * DAY),
        updated_at: ago(2 * DAY),
    },
    {
        object: 'skill',
        id: 'sk_tone',
        name: 'support-tone',
        description: 'How replies to customers read',
        always: true,
        version: 1,
        file_count: files('sk_tone').length,
        size: size('sk_tone'),
        attached_to: [{ id: SUPPORT.id, name: SUPPORT.name, pin: null }],
        user_id: null,
        created_at: ago(20 * DAY),
        updated_at: ago(20 * DAY),
    },
];

/** A skill's versions, newest first: each one's files as they are now (the fixtures keep no older text). */
const versions = (skill: Json): Json[] =>
    Array.from({ length: Number(skill.version) }, (_, i) => Number(skill.version) - i).map((version) => ({
        object: 'skill_version',
        version,
        digest: `${skill.id}-v${version}`,
        name: skill.name,
        description: skill.description,
        always: skill.always,
        files: files(String(skill.id)),
        size: skill.size,
        created_by: version === 1 ? { type: 'console' } : by(SUPPORT),
        created_at: version === Number(skill.version) ? skill.updated_at : skill.created_at,
    }));

const ENTRIES: Json[] = [
    {
        object: 'memory_entry',
        name: 'holiday-hours',
        description: 'When the support line is open over the holidays',
        content: 'Closed on the 25th and the 1st; open 9 to 1 on the 24th and the 31st.',
        version: 1,
        updated_at: ago(3 * DAY),
        written_by: { type: 'console' },
    },
    {
        object: 'memory_entry',
        name: 'vip-customers',
        description: 'Who gets a reply within the hour',
        content: 'Orders over $2,000 in the last year, and anyone a person marked VIP in the CRM.',
        version: 3,
        updated_at: ago(5 * HOUR),
        written_by: { ...by(SUPPORT), conversation: 'main' },
    },
];

export const MEMORIES: Json[] = [
    {
        object: 'memory',
        id: 'mem_team',
        name: 'team',
        description: 'What the support team agreed',
        agent_id: null,
        attached_to: [
            { id: SUPPORT.id, name: SUPPORT.name, writes: true },
            { id: CONCIERGE.id, name: CONCIERGE.name, writes: false },
        ],
        entry_count: ENTRIES.length,
        user_id: null,
        created_at: ago(30 * DAY),
        updated_at: ago(5 * HOUR),
    },
];

/** The populated set's row `r.params.id`, answered by `reply`; the API's 404 where there's none. */
function withRow(r: FixtureRequest, rows: Json[], noun: string, reply: (row: Json) => FixtureReply): FixtureReply {
    const row = r.set === 'populated' ? rows.find((x) => x.id === r.params.id) : undefined;
    return row ? reply(row) : apiError(404, 'not_found', `No ${noun} ${r.params.id}.`);
}

export const routes: readonly FixtureRoute[] = [
    { method: 'GET', path: '/v1/skills', reply: (r) => pageList(r, SKILLS) },
    { method: 'GET', path: '/v1/skills/:id', reply: (r) => withRow(r, SKILLS, 'skill', ok) },
    { method: 'GET', path: '/v1/skills/:id/versions', reply: (r) => withRow(r, SKILLS, 'skill', (skill) => list(versions(skill))) },
    {
        method: 'GET',
        path: '/v1/skills/:id/files',
        reply: (r) =>
            withRow(r, SKILLS, 'skill', (skill) => {
                const path = r.query.get('path');
                if (!path) return list(files(String(skill.id)));
                const content = FILES[String(skill.id)][path];
                if (content === undefined) return apiError(404, 'not_found', `No file ${path} in ${skill.name}.`);
                return ok({ path, version: skill.version, size: content.length, sha256: `${skill.id}-${path}`, content, encoding: 'utf-8' });
            }),
    },
    { method: 'GET', path: '/v1/memories', reply: (r) => pageList(r, MEMORIES) },
    { method: 'GET', path: '/v1/memories/:id', reply: (r) => withRow(r, MEMORIES, 'memory', ok) },
    // A list leaves each entry's content out, as the API's does; an entry read alone carries it.
    { method: 'GET', path: '/v1/memories/:id/entries', reply: (r) => withRow(r, MEMORIES, 'memory', () => list(ENTRIES.map(({ content: _, ...entry }) => entry))) },
    {
        method: 'GET',
        path: '/v1/memories/:id/entries/:name',
        reply: (r) =>
            withRow(r, MEMORIES, 'memory', () => {
                const entry = ENTRIES.find((e) => e.name === r.params.name);
                return entry ? ok(entry) : apiError(404, 'not_found', `No entry ${r.params.name}.`);
            }),
    },
];
