// @vitest-environment happy-dom
// A workflow's Test Run where no host fills its slot, over the platform API: the list the workflow offers (with the
// runs it keeps in its settings), a run of one (its steps when it ends, what it would have sent, the agent's closing
// words; a run that fails says why), the screen's changes to the workflow's test runs written before a run plays
// them, what still needs connecting, nothing shared; and the bench's canned runs, which reach no API at all.
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { NoClick } from 'noclick';
import type { ReactNode } from 'react';
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { fill, standing } from '@/slots';
import { WORKFLOW } from '../graph/fixtures';
import { FRAME_PARTS, TEST_RUN } from '../slots';
import { forgetAuthoring } from './authoring';
import { AUTHORING, REHEARSAL, SAMPLE, testRunFetch, type TestRunFetchOptions } from './fixtures';
import { applyProgressFrame, deriveArtifacts, readableStep, toReplayRows, type LiveRow } from './liveRows';
import { triggersOfStaged } from './staged';
import { forgetTestRuns, keep, rowsOfTranscript, stagedOfTestRuns } from './standards';
import { FRAMES } from './frameParts';
import { TestRunScreen } from './TestRunScreen';

type Json = Record<string, unknown>;

// The standards' SDK and the Markdown the frames draw load with their first use: once here.
beforeAll(async () => {
    await Promise.all([import('../standardsSdk'), import('@/screens/resources/CodeView')]);
});

afterEach(() => {
    cleanup();
    forgetAuthoring();
    forgetTestRuns();
});

/** A client over the fixtures, every call kept as `METHOD path` with its body. */
function world(options: TestRunFetchOptions = {}) {
    const sent: { line: string; body: Json }[] = [];
    const answers = testRunFetch(options);
    const client = new NoClick({
        apiKey: 'held-by-this-app-server',
        baseUrl: 'https://api.test',
        maxRetries: 0,
        fetch: async (input, init) => {
            const url = new URL(String(input instanceof Request ? input.url : input));
            sent.push({ line: `${init?.method ?? 'GET'} ${decodeURIComponent(url.pathname)}`, body: init?.body ? (JSON.parse(String(init.body)) as Json) : {} });
            return answers(input, init);
        },
    });
    const Around = ({ children }: { children: ReactNode }) => <ClientProvider client={client}>{children}</ClientProvider>;
    return { client, sent, lines: () => sent.map((call) => call.line), Around };
}

const button = (text: string) => screen.getAllByRole('button').find((b) => b.textContent?.trim() === text) as HTMLButtonElement;
const path = `/v1/workflows/${WORKFLOW}`;

describe('the Test Run on the platform API', () => {
    it('lists what the workflow offers with the runs it keeps, and plays one', async () => {
        const { Around, lines, sent } = world();
        const { container } = render(<TestRunScreen icons={{}} live={{ workflowId: WORKFLOW }} />, { wrapper: Around });
        expect(container.textContent).toContain('Looking at your workflow');
        await screen.findByText('Sample event', { selector: 'span' });
        // The offered situation and the run the workflow added, read from its settings.
        fireEvent.click(container.querySelector('button.group.py-2')!);
        expect([...container.querySelectorAll('.group\\/row')].map((row) => row.textContent?.trim())).toEqual(['Sample event', 'A late order']);
        fireEvent.click(container.querySelector('button[aria-label="Close"]')!);
        expect(container.textContent).toContain(SAMPLE.body);
        expect(lines()).toEqual(expect.arrayContaining([`GET ${path}/test_runs`, `GET ${path}/graph`, `GET ${path}`]));
        // What it still needs connected, from the workflow's own steps and the catalog's name for the type.
        await waitFor(() => expect(container.textContent).toContain("Without Tell the team, your agent can't act."));

        fireEvent.click(button('Test Run'));
        await waitFor(() => expect(container.textContent).toContain('What it would have sent'));
        const run = sent.find((call) => call.line === `POST ${path}/rehearsals`)!;
        expect(run.body).toEqual({ test_run: 'generic:trigger-webhook' });
        // Each step at once: the agent's words, the call with what it would have sent, the search.
        expect(container.textContent).toContain('A new order: tell the team.');
        expect(container.textContent).toContain('Send message');
        expect(container.textContent).toContain('Web search');
        expect(container.textContent).toContain('Order ord_81 came in: 42.50, paid.');
        // Nothing is shared from here.
        expect(button('Share this run')).toBeUndefined();
        expect(lines().filter((line) => line.startsWith('POST'))).toEqual([`POST ${path}/rehearsals`]);
    });

    it('writes the screen’s changes to the workflow’s test runs before a run plays them', async () => {
        const authoring = { held: structuredClone(AUTHORING) as Json | null };
        const { Around, sent } = world({ authoring });
        const { container } = render(<TestRunScreen icons={{}} live={{ workflowId: WORKFLOW }} />, { wrapper: Around });
        await screen.findByText('Sample event', { selector: 'span' });
        // A new run copies the one on screen, asks its name, and is played at once: its write lands first.
        fireEvent.click(container.querySelector('[title^="New test run"]')!);
        const name = container.querySelector('input[placeholder="Name this test run"]') as HTMLInputElement;
        fireEvent.keyDown(name, { key: 'Enter', target: Object.assign(name, { value: 'A refund' }) });
        fireEvent.click(button('Test Run'));
        await waitFor(() => expect(sent.some((call) => call.line === `POST ${path}/rehearsals`)).toBe(true));
        const order = sent.filter((call) => call.line.startsWith('POST')).map((call) => call.line);
        expect(order).toEqual([`POST ${path}/edits`, `POST ${path}/rehearsals`]);
        const edit = sent.find((call) => call.line === `POST ${path}/edits`)!;
        const written = ((edit.body.ops as Json[])[0].settings as Json).rehearsal_authoring as { runs: Record<string, { slug: string }[]>; names: Record<string, string> };
        const added = written.runs['trigger-webhook'].at(-1)!;
        expect((edit.body.ops as Json[])[0].op).toBe('update_workflow');
        expect(written.names[`trigger-webhook:${added.slug}`]).toBe('A refund');
        // The run plays the added run by its own name among the workflow's test runs.
        expect(sent.find((call) => call.line === `POST ${path}/rehearsals`)!.body).toEqual({ test_run: added.slug });
        expect(authoring.held).toEqual(written);
    });

    it('says why a run failed, and why the list couldn’t be read', async () => {
        const failing = world({ played: () => ({ error: { type: 'payment_required', message: 'The account is out of funds.' } }) });
        const first = render(<TestRunScreen icons={{}} live={{ workflowId: WORKFLOW }} />, { wrapper: failing.Around });
        await screen.findByText('Sample event', { selector: 'span' });
        fireEvent.click(button('Test Run'));
        await waitFor(() => expect(first.container.textContent).toContain('The test didn’t finish'));
        expect(first.container.textContent).toContain('out of funds');
        cleanup();

        const refused = world({ listRefused: 'This key can’t read workflows.' });
        const second = render(<TestRunScreen icons={{}} live={{ workflowId: WORKFLOW }} />, { wrapper: refused.Around });
        await waitFor(() => expect(second.container.textContent).toContain('Nothing to stage yet'));
        expect(second.container.textContent).toContain('This key can’t read workflows.');
    });

    it('starts a run asked for from elsewhere, once', async () => {
        const { Around, sent } = world();
        keep(`autorun-${WORKFLOW}`, { trigger: 'trigger-webhook', run: 'run-late' });
        const drawn = render(<TestRunScreen icons={{}} live={{ workflowId: WORKFLOW }} />, { wrapper: Around });
        await waitFor(() => expect(sent.some((call) => call.line === `POST ${path}/rehearsals`)).toBe(true));
        expect(sent.find((call) => call.line === `POST ${path}/rehearsals`)!.body).toEqual({ test_run: 'run-late' });
        await waitFor(() => expect(drawn.container.textContent).toContain('What it would have sent'));
        drawn.rerender(<TestRunScreen icons={{}} live={{ workflowId: WORKFLOW }} />);
        await act(async () => undefined);
        expect(sent.filter((call) => call.line === `POST ${path}/rehearsals`)).toHaveLength(1);
    });
});

describe('the bench’s canned runs', () => {
    it('reach no API, and play to their end', async () => {
        const { Around, lines } = world();
        const { container } = render(<TestRunScreen icons={{}} bench />, { wrapper: Around });
        fireEvent.click(button('end'));
        fireEvent.click(button('Test Run'));
        await waitFor(() => expect(container.textContent).toContain('What it would have sent'));
        expect(lines()).toEqual([]);
    });

    it('draw with no client above them at all', () => {
        const { container } = render(<TestRunScreen icons={{}} bench />);
        expect(container.textContent).toContain('Rehearsal views');
        expect(button('Test Run')).toBeDefined();
    });
});

describe('what the standards and the frames are made of', () => {
    it('reads the API’s list as the screen’s staged list, an added run left to the workflow’s settings', () => {
        const { staged, names } = stagedOfTestRuns([
            { key: 'sales-inbound-lead', name: 'Big lead', custom: false, trigger: { type: 'automation-gmail', label: 'Gmail', operation: 'poll_for_new_emails' }, message: { title: 'Pricing', body: 'Forty seats?' } },
            { key: 'refund-request', name: 'Refund request', custom: true, trigger: { type: 'automation-gmail', label: 'Gmail', operation: 'poll_for_new_emails' }, message: { title: 'Refund', body: 'Please.' } },
            { key: 'generic:automation-calcom', name: 'Sample event', custom: false, trigger: { type: 'automation-calcom', label: 'Cal.com', operation: null }, message: { title: 'Sample event', body: '{}' } },
        ]);
        expect(staged.map((t) => [t.node_type, t.operation, t.situations?.map((s) => s.key)])).toEqual([
            ['automation-gmail', 'poll_for_new_emails', ['sales-inbound-lead']],
            ['automation-calcom', null, ['generic:automation-calcom']],
        ]);
        const triggers = triggersOfStaged(staged, (type) => names[type] ?? type);
        // Gmail draws natively; a type with no native frame keeps its own name and logo.
        expect(triggers.map((t) => [t.slug, t.provider, t.nodeName, t.iconSlug, t.triggerLabel])).toEqual([
            ['automation-gmail', 'gmail', 'Gmail', 'gmail', 'Staged email'],
            ['automation-calcom', 'generic', 'Cal.com', 'calcom', 'Staged event'],
        ]);
        expect(triggers[0].mocks[0]).toMatchObject({ slug: 'sales-inbound-lead', backendKey: 'sales-inbound-lead', name: 'Big lead' });
    });

    it('reads a finished run’s transcript as rows, its closing words left to the outcome', () => {
        const rows = rowsOfTranscript(REHEARSAL.transcript as Json[], String(REHEARSAL.reply), 1000);
        expect(rows.map((row) => [row.thought ?? row.tool, row.status, row.outbound])).toEqual([
            ['A new order: tell the team.', 'completed', undefined],
            ['slack__send_message', 'completed', 'Order ord_81 came in: 42.50, paid.'],
            ['web_search', 'completed', undefined],
        ]);
        expect(deriveArtifacts(rows)).toEqual([{ provider: 'slack', to: '#orders', subject: undefined, text: 'Order ord_81 came in: 42.50, paid.' }]);
        expect(toReplayRows(rows, 1000).map((row) => (row.kind === 'tool' ? [row.text, row.provider, row.glyph] : row.text))).toEqual([
            'A new order: tell the team.',
            ['Send message', 'slack', 'plug'],
            ['Web search', undefined, 'globe'],
        ]);
    });

    it('folds a run’s frames into rows as they arrive', () => {
        const rows: LiveRow[] = [];
        applyProgressFrame(rows, { kind: 'step', step_id: 's1', tool: 'gmail__send_email', status: 'in_progress', args: { to: 'ana@example.test' } });
        applyProgressFrame(rows, { kind: 'thought', step_id: 't1', text: 'Answer her.' });
        applyProgressFrame(rows, { kind: 'thought', step_id: 't1', text: 'Answer her.' });
        applyProgressFrame(rows, { kind: 'step', step_id: 's1', tool: 'gmail__send_email', status: 'completed', result: { id: 'm1' }, outbound: 'On its way.' });
        expect(rows.map((row) => [row.id, row.status, row.outbound ?? row.thought])).toEqual([['s1', 'completed', 'On its way.'], ['t1', 'completed', 'Answer her.']]);
        expect(rows[0].args).toEqual({ to: 'ana@example.test' });
        expect(readableStep('google_sheets__append_row')).toEqual({ label: 'Append row', provider: 'Google Sheets', tool: 'google_sheets__append_row' });
    });

    it('draws a reply’s Markdown and the working mark with whoever fills them', async () => {
        const standard = standing(FRAME_PARTS);
        const drawn = render(<standard.Markdown content={'A **bold** claim'} className="text-sm" />);
        await waitFor(() => expect(drawn.container.querySelector('strong')?.textContent).toBe('bold'));
        expect(render(<standard.Working size={18} />).container.querySelector('span')?.style.width).toBe('18px');
        try {
            fill(FRAME_PARTS, { Markdown: ({ content }) => <b>{content}</b>, Working: () => <i>busy</i> });
            const hosted = render(<TestRunScreen icons={{}} bench />);
            fireEvent.click(button('Test Run'));
            await waitFor(() => expect(hosted.container.querySelector('i')?.textContent).toBe('busy'));
        } finally {
            fill(FRAME_PARTS, standard);
        }
        expect(standing(TEST_RUN).runsSaved).toBe(true);
        // The frames read their slot by a handle of their own: the same place, by name.
        expect(FRAMES.name).toBe(FRAME_PARTS.name);
        expect(FRAMES.standard).toBe(FRAME_PARTS.standard);
    });
});
