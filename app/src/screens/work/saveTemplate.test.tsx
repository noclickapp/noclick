// @vitest-environment happy-dom
// Save as template, over a stand-in /v1: the dialog reads what would go in first (a dry run) and says it, with what
// never goes in and what stays behind; saving writes the repository under the name it shows, and with Make it public on,
// makes it public and shows the address anyone clones it from. A refusal to make it public leaves it saved, saying why.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { workFixtureClient } from './fixtures/client';
import { SaveTemplateDialog, containsLine } from './SaveTemplateDialog';
import type { WorkSpace } from './spaces';

afterEach(cleanup);

const SPACE: WorkSpace = { id: 'ws_1', workspaceId: 'ws_1', name: 'Social media', own: true, role: 'owner' };
const ORIGIN = 'https://api.noclick.com/v1/public/git/pub_1.git';
const SAID = {
    object: 'space_template', name: 'Social media', repo_name: 'social-media-template', repo: null, commit: null,
    contains: { name: 'Social media', channels: ['ideas', 'drafts'], agents: ['Writer', 'Scheduler'], skills: ['brand-voice'], memories: ['brand'], automations: ['Monday plan'], stores: [], app: true },
    asks: { connections: [{ integration: 'instagram', for: ['Scheduler'] }], secrets: [{ name: 'unsplash', keys: ['UNSPLASH_ACCESS_KEY'], for: ['Writer'] }] },
    files: 12, left_out: [{ what: "Writer's tools: a person", why: 'a template names no one but whoever adds it' }],
    never: ['messages, and the files and data its channels and stores hold', 'the people in the space'], summary: '',
};

function standIn(publicAnswer: { status: number; body: unknown }) {
    const sent: { path: string; body: Record<string, unknown> }[] = [];
    const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
        const body = init?.body ? JSON.parse(String(init.body)) : {};
        sent.push({ path: url.pathname, body });
        const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'content-type': 'application/json' } });
        if (url.pathname === '/v1/workspaces/ws_1/template') {
            if (body.dry_run) return json(SAID);
            return json({ ...SAID, repo_name: body.repo_name, repo: { object: 'repo', id: 'repo_1', name: body.repo_name, default_branch: 'main' }, commit: { sha: 'abc' } }, 201);
        }
        if (url.pathname === '/v1/repos/repo_1/public') return json(publicAnswer.body, publicAnswer.status);
        return json({ error: { type: 'not_found', message: 'No such thing.' } }, 404);
    });
    return { client: workFixtureClient(fetch as unknown as typeof window.fetch, { maxRetries: 0 }), sent };
}

it('says what goes in and never does, then saves it public and shows its address', async () => {
    const { client, sent } = standIn({ status: 200, body: { object: 'public_app', kind: 'template', public: true, clone_url: ORIGIN, origin_url: ORIGIN } });
    render(<SaveTemplateDialog space={SPACE} client={client} onClose={() => {}} />);

    expect((await screen.findByTestId('template-contains')).textContent).toBe(
        '2 channels, 2 agents and their instructions, a skill, a memory, an automation and its app’s code.'
    );
    expect(screen.getByTestId('save-template').textContent).toContain('It asks whoever adds it to connect instagram and for a secret (unsplash).');
    expect(screen.getByTestId('template-never').textContent).toBe('Messages, and the files and data its channels and stores hold; the people in the space.');
    expect(screen.getByText('1 more thing stays behind')).toBeTruthy();
    const name = screen.getByDisplayValue('social-media-template');
    fireEvent.change(name, { target: { value: 'lumen-social' } });
    fireEvent.click(screen.getByRole('switch', { name: 'Make it public' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save template' }));

    expect((await screen.findByTestId('template-link')).textContent).toBe(ORIGIN);
    expect(screen.getByTestId('template-saved').textContent).toContain('Saved as the repository lumen-social. Anyone can clone it from its address:');
    expect(sent.map((s) => s.path)).toEqual(['/v1/workspaces/ws_1/template', '/v1/workspaces/ws_1/template', '/v1/repos/repo_1/public']);
    expect(sent[1].body).toEqual({ repo_name: 'lumen-social' });
});

it('keeps it saved and private when making it public is refused, saying why', async () => {
    const { client, sent } = standIn({ status: 403, body: { error: { type: 'permission_denied', message: 'This key lacks the projects:publish scope.', scope: 'projects:publish' } } });
    render(<SaveTemplateDialog space={SPACE} client={client} onClose={() => {}} />);
    await screen.findByTestId('template-contains');
    fireEvent.click(screen.getByRole('switch', { name: 'Make it public' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save template' }));

    await waitFor(() => expect(screen.getByTestId('template-saved').textContent).toContain('It’s saved, but private: This key lacks the projects:publish scope.'));
    expect(screen.queryByTestId('template-link')).toBeNull();
    expect(sent.filter((s) => s.path.endsWith('/public'))).toHaveLength(1);
});

it('names a template’s parts in plain words', () => {
    expect(containsLine({ agents: ['Writer'] })).toBe('an agent and its instructions');
    expect(containsLine({ channels: ['ideas'], app: true })).toBe('a channel and its app’s code');
});
