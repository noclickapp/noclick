// The operation grammar is authored against the REAL x-is-trigger inventory
// in the generated node schemas. Two ratchets: every table key must be a real
// operation (a typo'd key silently renders the fallback), and every themed
// app's real trigger operation must resolve to a rendering (table or generic
// lexicon) — so a newly added trigger op can't quietly fall back to a wrong
// default like the green Open pill (2026-08-10 report).

import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import {
    APP_OP_RENDERS,
    resolveOpRender,
} from '~/components/design/rehearsal/opGrammar';

const SCHEMA_DIR = join(__dirname, '../../app/schemas/nodes');

/** grammar slug → schema file basename */
const SCHEMA_FOR_SLUG: Record<string, string> = {
    github: 'github-rest',
    gitlab: 'gitlab',
    linear: 'linear',
    jira: 'jira',
    sentry: 'sentry',
    datadog: 'datadog',
    pagerduty: 'pagerduty',
    firestore: 'firestore',
    stripe: 'stripe',
    shopify: 'shopify',
    zoom: 'zoom',
    calendly: 'calendly',
    cal_com: 'cal-com',
    google_calendar: 'google-calendar',
    mailgun: 'mailgun',
    zendesk: 'zendesk',
    intercom: 'intercom',
    hubspot: 'hubspot',
    pipedrive: 'pipedrive',
    salesforce: 'salesforce',
    notion: 'notion',
    monday: 'monday',
    clickup: 'clickup',
    trello: 'trello',
    asana: 'asana',
    webflow: 'webflow',
    google_drive: 'google-drive',
    google_sheets: 'google-sheets',
    typeform: 'typeform',
    google_forms: 'google-forms',
    slack: 'slack',
    discord: 'discord',
    microsoft_teams: 'microsoft-teams',
    facebook: 'facebook',
    whatsapp: 'whatsapp',
};

/** Plain incoming messages render as the message itself — deliberately no
    grammar entry, and no lexicon hit required. */
const PLAIN_MESSAGE_OPS = new Set([
    'slack:on_channel_message',
    'microsoft_teams:on_channel_message',
    'microsoft_teams:on_chat_message',
    'whatsapp:receive_message',
    'facebook:on_messages',
]);

function triggerOpsFromSchema(basename: string): string[] {
    const raw = JSON.parse(
        readFileSync(join(SCHEMA_DIR, `${basename}.json`), 'utf8')
    );
    const ops: string[] = [];
    const walk = (o: unknown): void => {
        if (Array.isArray(o)) return o.forEach(walk);
        if (!o || typeof o !== 'object') return;
        const rec = o as Record<string, unknown>;
        const op = rec.operation as Record<string, unknown> | undefined;
        if (op && op['x-is-trigger'] === true && typeof op.const === 'string') {
            ops.push(op.const);
        }
        Object.values(rec).forEach(walk);
    };
    walk(raw.$defs ?? {});
    return ops;
}

describe('opGrammar', () => {
    it('every table key is a real trigger operation for its app', () => {
        for (const [slug, table] of Object.entries(APP_OP_RENDERS)) {
            const schema = SCHEMA_FOR_SLUG[slug];
            expect(schema, `no schema mapping for grammar slug '${slug}'`).toBeTruthy();
            const real = new Set(triggerOpsFromSchema(schema));
            for (const key of Object.keys(table)) {
                expect(real.has(key), `${slug}.${key} is not a real trigger operation`).toBe(true);
            }
        }
    });

    it('every real trigger operation of a themed app resolves to a rendering', () => {
        for (const [slug, schema] of Object.entries(SCHEMA_FOR_SLUG)) {
            for (const op of triggerOpsFromSchema(schema)) {
                if (PLAIN_MESSAGE_OPS.has(`${slug}:${op}`)) {
                    expect(
                        APP_OP_RENDERS[slug]?.[op],
                        `${slug}.${op} is a plain message and must NOT have an entry`
                    ).toBeUndefined();
                    continue;
                }
                const r = resolveOpRender(slug, op);
                expect(r, `${slug}.${op} resolves to nothing — it will render a wrong default`).toBeTruthy();
            }
        }
    });

    it('bylines are well-formed', () => {
        for (const [slug, table] of Object.entries(APP_OP_RENDERS)) {
            for (const [key, r] of Object.entries(table)) {
                if (r.byline) {
                    const count = (r.byline.match(/\{author\}/g) ?? []).length;
                    expect(count, `${slug}.${key} byline uses {author} ${count}×`).toBeLessThanOrEqual(1);
                    expect(r.byline.endsWith('.'), `${slug}.${key} byline has trailing punctuation`).toBe(false);
                }
                if (r.pill) expect(r.pill.label.trim(), `${slug}.${key} empty pill`).toBeTruthy();
            }
        }
    });

    it('renders the states the 2026-08-10 review called out', () => {
        expect(resolveOpRender('github', 'on_issue_pinned')?.byline).toBe('pinned by {author}');
        expect(resolveOpRender('github', 'on_issue_milestoned')?.icon).toBe('milestone');
        expect(resolveOpRender('github', 'on_pull_request_closed')?.pill).toEqual({ label: 'Closed', tone: 'bad' });
        expect(resolveOpRender('github', 'on_pull_request_merged')?.pill?.label).toBe('Merged');
        expect(resolveOpRender('stripe', 'on_invoice_payment_failed')?.pill?.label).toBe('Past due');
        expect(resolveOpRender('calendly', 'on_invitee_no_show_created')?.pill?.label).toBe('No-show');
        expect(resolveOpRender('zendesk', 'on_ticket_merged')?.pill?.label).toBe('Merged');
        expect(resolveOpRender('zoom', 'on_meeting_participant_joined')?.byline).toBe('{author} joined the meeting');
        // Unknown-app op with a recognisable action still resolves via the lexicon.
        expect(resolveOpRender('someday-app', 'on_widget_unpinned')?.byline).toBe('unpinned by {author}');
    });
});
