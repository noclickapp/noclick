// Regression tests for reference remapping when pasting a NoClick workflow.
// On paste, node ids are regenerated; references inside configs must be rewritten
// to the new ids — for BOTH the `$('id')` accessor form and the legacy `{{id.path}}`
// form — or the pasted workflow's references break.

import { describe, it, expect } from 'vitest';
import { noClickParser } from './noclick-parser';

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
                    // new converged `$()` accessor form
                    body: "Stories: {{ $('hn_old').stories.map(s => s.title).join(', ') }}",
                    // legacy dotted form
                    subject: '{{hn_old.count}} stories',
                    // double-quoted accessor variant
                    note: 'Top: {{ $("hn_old").stories[0].title }}',
                },
            },
        ],
        edges: [{ id: 'e1', source: 'hn_old', target: 'email_old' }],
    });
}

describe('noClickParser — reference remapping on paste', () => {
    it('remaps $() accessor AND legacy references to the new node ids', () => {
        const result = noClickParser.parse(clipboard());
        expect(result).not.toBeNull();

        const hnNew = result!.nodes[0].id;
        const emailNew = result!.nodes[1].id;
        // ids were actually regenerated (not the originals)
        expect(hnNew).not.toBe('hn_old');
        expect(emailNew).not.toBe('email_old');

        const cfg = (result!.nodes[1].data as { config: Record<string, string> }).config;

        // $() accessor refs must point to the NEW id, with no trace of the old id
        expect(cfg.body).toContain(`$('${hnNew}')`);
        expect(cfg.body).not.toContain('hn_old');
        expect(cfg.note).toContain(`$("${hnNew}")`);
        expect(cfg.note).not.toContain('hn_old');

        // legacy form is remapped too
        expect(cfg.subject).toBe(`{{${hnNew}.count}} stories`);
    });

    it('leaves references to nodes outside the pasted selection untouched', () => {
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
        // external_node isn't in the paste -> kept verbatim
        expect(cfg.body).toBe("{{ $('external_node').data }} and {{external_node.x}}");
    });
});
