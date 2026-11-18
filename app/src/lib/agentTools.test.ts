// What an agent can use, read from its stored `tools`: everything on the account as one row holding what it already
// gives, beside what it doesn't (people, a browser, resources, another scope's connection); a list turned back into
// everything (its rules then saying what's on) keeps the rest, and adding it back keeps what was chosen.
import { describe, expect, it } from 'vitest';
import { EVERYTHING, holds, toEverything, toolRows, withAll, type ToolEntry } from '@/lib/agentTools';

const OWNER = { human: { owner: true }, tools: ['notify', 'ask'] };

describe('toolRows', () => {
    it('reads an agent made with no tools as everything and its owner', () => {
        const rows = toolRows([EVERYTHING, OWNER], []);
        expect(rows.map((r) => r.kind)).toEqual(['everything', 'person']);
        expect(rows[0]).toMatchObject({ key: EVERYTHING, entries: [EVERYTHING], noclick: null });
        expect(rows[1]).toMatchObject({ title: 'You', line: 'It can tell and ask them' });
    });

    it('holds what everything gives in its row, and lists what it doesn’t on its own', () => {
        const tools: ToolEntry[] = ['gmail.send_email', EVERYTHING, 'search', 'credential:c1', 'exa', 'browser', 'connection:k9', 'database:db1', 'code', OWNER];
        const rows = toolRows(tools, []);
        expect(rows.map((r) => r.key)).toEqual([EVERYTHING, 'app:connection:k9', 'noclick:browser', 'resource:database:db1', `person:${JSON.stringify(OWNER.human)}`]);
        expect(rows[0].entries).toEqual(['gmail.send_email', EVERYTHING, 'search', 'credential:c1', 'exa']);
    });

    it('says what NoClick is narrowed to beside everything, and all of it once one names it whole', () => {
        const [narrowed] = toolRows([EVERYTHING, 'noclick.read', 'noclick.build'], []);
        expect(narrowed).toMatchObject({ kind: 'everything', noclick: ['read', 'build'] });
        const [whole] = toolRows([EVERYTHING, 'noclick.read', 'noclick'], []);
        expect(whole).toMatchObject({ kind: 'everything', noclick: null });
    });

    it('reads an explicit list as it always did', () => {
        const rows = toolRows(['gmail', 'gmail.send_email', 'noclick.read', 'search'], []);
        expect(rows.map((r) => r.key)).toEqual(['app:gmail', 'noclick:noclick', 'noclick:search']);
        expect(rows[1]).toMatchObject({ line: 'Only read' });
    });
});

describe('a list turned into everything', () => {
    it('drops what everything covers and keeps people, a browser, resources, another scope’s connection and its shell', () => {
        const tools: ToolEntry[] = ['credential:c1', 'gmail.send_email', 'search', 'noclick.read', 'noclick.domains', 'browser', 'connection:k9', 'database:db1', 'code', OWNER];
        expect(toEverything(tools)).toEqual([EVERYTHING, 'noclick.domains', 'browser', 'connection:k9', 'database:db1', 'code', OWNER]);
    });

    it('keeps an operation with its arguments bound', () => {
        const bound = { tool: 'gmail.send_email', bind: { to: 'a@b.c' } };
        expect(toEverything(['gmail', bound, 'noclick'])).toEqual([EVERYTHING, bound]);
    });

    it('goes back to everything beside what was chosen', () => {
        const chosen: ToolEntry[] = ['credential:c1', 'search', OWNER];
        const back = withAll(chosen, EVERYTHING);
        expect(back).toEqual([...chosen, EVERYTHING]);
        expect(toolRows(back, []).map((r) => r.kind)).toEqual(['everything', 'person']);
    });
});

describe('holds', () => {
    it('counts what everything gives as held, and not what it doesn’t', () => {
        const tools: ToolEntry[] = [EVERYTHING, OWNER];
        for (const ref of ['gmail', 'credential:c1', 'search', 'fetch', 'noclick', EVERYTHING]) expect(holds(tools, ref)).toBe(true);
        for (const ref of ['browser', 'agents', 'connection:k9']) expect(holds(tools, ref)).toBe(false);
        expect(holds(['gmail'], EVERYTHING)).toBe(false);
    });
});
