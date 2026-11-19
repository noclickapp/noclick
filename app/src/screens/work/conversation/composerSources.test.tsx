// @vitest-environment happy-dom
// The box's "+" reads what a message can point at through the platform API: every automation the account can open,
// the most recently changed first, in the mark of what it's made of; and the account's own accounts that are
// connected, named connections and those connected in the app alike, the most recently connected first, each named as
// the host names accounts. A named connection is pointed at by its connection's id, one connected in the app by its
// credential's. In a team workspace the accounts are read there, where those shared with the team are too, and each is
// pointed at with the workspace it was read in.
import { cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { composeMessage, readMessage } from '@/lib/agentThread/messages';
import { fill } from '@/slots';
import { WorkClientContext } from '../client';
import { workFixtureClient } from '../fixtures/client';
import { TEAM_WORKSPACE } from '../slots';
import { COMPOSER_SOURCES } from './composerSources';

afterEach(() => {
    cleanup();
    fill(TEAM_WORKSPACE, () => null);
});

const WORKFLOWS = [
    { object: 'workflow', id: 'wf-digest', name: 'Morning brief', step_types: ['trigger-cron', 'agent:codex'], updated_at: '2026-11-09T08:00:00Z' },
    { object: 'workflow', id: 'wf-orders', name: 'Bakery orders', step_types: [], updated_at: '2026-11-11T16:20:00Z' },
];
const CONNECTIONS = [
    { object: 'connection', id: 'conn-4', name: 'notion', integration: 'notion', credential_type: 'notion_oauth', status: 'connected', origin: 'api', account: 'maya@notion.test', created_at: '2026-10-01T09:00:00Z', connected_at: '2026-10-03T09:00:00Z' },
    { object: 'connection', id: 'credential:cred-gmail', name: 'Gmail', integration: 'gmail', credential_type: 'google_gmail_oauth', status: 'connected', origin: 'app', account: 'maya@bakery.test', created_at: '2026-10-02T09:00:00Z', connected_at: '2026-10-02T09:00:00Z' },
    { object: 'connection', id: 'credential:cred-slack', name: 'Slack', integration: 'slack', credential_type: 'slack_oauth', status: 'connected', origin: 'app', account: null, created_at: '2026-09-20T09:00:00Z', connected_at: '2026-09-20T09:00:00Z' },
    { object: 'connection', id: 'credential:cred-old', name: 'Gmail', integration: 'gmail', credential_type: 'google_gmail_oauth', status: 'disconnected', origin: 'app', account: 'old@bakery.test', created_at: '2026-11-01T09:00:00Z', connected_at: '2026-11-01T09:00:00Z' },
    { object: 'connection', id: 'conn-5', name: 'linear', integration: 'linear', credential_type: 'linear_oauth', status: 'pending', origin: 'api', account: null, created_at: '2026-11-02T09:00:00Z', connected_at: null },
];

const TEAM = 'org-bakery-team';
const TEAM_SHARED = { object: 'connection', id: 'credential:cred-docs', name: 'Docs', integration: 'google_docs', credential_type: 'google_docs_oauth', status: 'connected', origin: 'app', access: 'view', organization_id: TEAM, account: 'team@bakery.test', created_at: '2026-11-05T09:00:00Z', connected_at: '2026-11-05T09:00:00Z' };

const asked: string[] = [];
const client = workFixtureClient(async (input) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
    asked.push(`${url.pathname}${url.search}`);
    const team = url.searchParams.get('organization_id');
    const data =
        url.pathname === '/v1/workflows' ? WORKFLOWS : url.pathname === '/v1/connections' ? (team ? CONNECTIONS.map((c) => (c.origin === 'app' ? { ...c, organization_id: team } : c)).concat(TEAM_SHARED) : CONNECTIONS) : null;
    return data ? Response.json({ object: 'list', data, next_cursor: null }) : Response.json({ error: { type: 'not_found', message: 'No route' } }, { status: 404 });
});
const wrapper = ({ children }: { children: ReactNode }) => <WorkClientContext.Provider value={client}>{children}</WorkClientContext.Provider>;

describe('what the "+" can point at', () => {
    it('lists every automation, the most recently changed first, marked by what it is made of', async () => {
        const { result } = renderHook(() => COMPOSER_SOURCES.useAutomations(), { wrapper });
        await waitFor(() => expect(result.current.loading).toBe(false));
        expect(result.current.automations.map((a) => [a.id, a.name, a.updatedAt, Boolean(a.mark)])).toEqual([
            ['wf-orders', 'Bakery orders', '2026-11-11T16:20:00.000Z', false],
            ['wf-digest', 'Morning brief', '2026-11-09T08:00:00.000Z', true],
        ]);
        expect(asked).toContain('/v1/workflows');
    });

    it('lists the accounts that are connected, both kinds, the most recently connected first, each named and pointed at', async () => {
        const { result } = renderHook(() => COMPOSER_SOURCES.useAccounts(), { wrapper });
        await waitFor(() => expect(result.current.loaded).toBe(true));
        const accounts = result.current.accounts;
        expect(accounts.map((a) => [a.id, a.line])).toEqual([
            ['connection:conn-4', 'maya@notion.test'],
            ['cred-gmail', 'maya@bakery.test'],
            // Named after its app, it says when it was connected.
            ['cred-slack', 'Added Sep 20, 2026'],
        ]);
        // Every connection the account's own scope holds, not only those connected in the app.
        expect(asked).toContain('/v1/connections');
        const [named, mail, slack] = accounts.map((a) => a.reference);
        expect(slack.label).toBe(accounts[2].app);
        expect(composeMessage('Use these', [named, mail], false)).toBe(
            `Use these\n\n(About the account “${named.label}” (connection conn-4) and the account “${mail.label}” (credential:cred-gmail).)`
        );
    });

    it('in a team workspace, lists its accounts there too and points at each with the workspace', async () => {
        fill(TEAM_WORKSPACE, () => TEAM);
        const { result } = renderHook(() => COMPOSER_SOURCES.useAccounts(), { wrapper });
        await waitFor(() => expect(result.current.loaded).toBe(true));
        expect(asked).toContain(`/v1/connections?organization_id=${TEAM}`);
        const accounts = result.current.accounts;
        expect(accounts.map((a) => [a.id, a.reference.organizationId])).toEqual([
            ['cred-docs', TEAM],
            ['connection:conn-4', undefined],
            ['cred-gmail', TEAM],
            ['cred-slack', TEAM],
        ]);
        const docs = accounts[0].reference;
        const message = composeMessage('Summarise the plan', [docs], false);
        expect(message).toBe(`Summarise the plan\n\n(About the account “${docs.label}” (credential:cred-docs, organization_id ${TEAM}).)`);
        expect(readMessage(message)).toEqual({ text: 'Summarise the plan', references: [docs] });
    });
});
