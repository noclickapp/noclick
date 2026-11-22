// A pasted workflow's steps get new ids, and the references between them (the `$('id')` accessor and the older
// `{{id.path}}`) must follow, or the pasted steps point at the ones they were copied from.
import { describe, expect, it } from 'vitest';
import { noClickParser } from './noclickFormat';

function clipboard() {
    return JSON.stringify({
        type: 'noclick-workflow',
        nodes: [
            {
                id: 'hn_old',
                type: 'automation-hackernews',
                position: { x: 0, y: 0 },
                config: { operation: 'fetch_top_stories' },
            },
            {
                id: 'email_old',
                type: 'automation-send-email',
                position: { x: 200, y: 0 },
                config: {
                    // the `$()` accessor
                    body: "Stories: {{ $('hn_old').stories.map(s => s.title).join(', ') }}",
                    // the older dotted form
                    subject: '{{hn_old.count}} stories',
                    // the accessor with double quotes
                    note: 'Top: {{ $("hn_old").stories[0].title }}',
                },
            },
        ],
        edges: [{ id: 'e1', source: 'hn_old', target: 'email_old' }],
    });
}

describe('the canvas’s own format, read back', () => {
    it('points each reference at its step’s new id, in both forms', () => {
        const result = noClickParser.parse(clipboard());
        expect(result).not.toBeNull();

        const hnNew = result!.nodes[0].id;
        const emailNew = result!.nodes[1].id;
        expect(hnNew).not.toBe('hn_old');
        expect(emailNew).not.toBe('email_old');

        const cfg = (result!.nodes[1].data as { config: Record<string, string> }).config;
        expect(cfg.body).toContain(`$('${hnNew}')`);
        expect(cfg.body).not.toContain('hn_old');
        expect(cfg.note).toContain(`$("${hnNew}")`);
        expect(cfg.note).not.toContain('hn_old');
        expect(cfg.subject).toBe(`{{${hnNew}.count}} stories`);
        // The connection follows its steps too.
        expect(result!.edges.map((edge) => [edge.source, edge.target])).toEqual([[hnNew, emailNew]]);
    });

    it('leaves a reference to a step that wasn’t pasted as it is', () => {
        const text = JSON.stringify({
            type: 'noclick-workflow',
            nodes: [
                {
                    id: 'only_old',
                    type: 'automation-send-email',
                    position: { x: 0, y: 0 },
                    config: { body: "{{ $('external_node').data }} and {{external_node.x}}" },
                },
            ],
            edges: [],
        });
        const cfg = (noClickParser.parse(text)!.nodes[0].data as { config: Record<string, string> }).config;
        expect(cfg.body).toBe("{{ $('external_node').data }} and {{external_node.x}}");
    });

    it('reads a saved file’s shape as it reads a copy’s, and nothing else', () => {
        const file = JSON.stringify({
            name: 'Orders',
            workflow_data: { nodes: [{ id: 'a', type: 'log', position: { x: 0, y: 0 }, config: { label: 'A' } }], edges: [] },
        });
        const read = noClickParser.parse(file);
        expect(read!.nodes).toHaveLength(1);
        expect(read!.nodes[0].type).toBe('log');
        expect(noClickParser.parse('{"hello":"world"}')).toBeNull();
        expect(noClickParser.parse('not json')).toBeNull();
        // A step with no settings isn't one this format wrote.
        expect(noClickParser.parse(JSON.stringify({ type: 'noclick-workflow', nodes: [{ id: 'a', type: 'log', position: { x: 0, y: 0 } }], edges: [] }))).toBeNull();
    });
});
