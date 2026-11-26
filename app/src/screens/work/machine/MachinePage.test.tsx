// @vitest-environment happy-dom
// An agent's machine page over the fake /v1: each folder read as it opens (a checkout is too big to read whole), a
// .env's names shown and never its values, a value set into it without being shown, and a file the agent linked to
// that isn't there yet made on the page.
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { fakeWork, id } from '../agents/fixtures/workAgents';
import { WorkProviders } from '../agents/fixtures/providers';
import { MachinePage } from './MachinePage';

afterEach(cleanup);

function open(file?: string) {
    const fake = fakeWork();
    render(
        <WorkProviders client={fake.client}>
            <MachinePage agentId={id(1)} onBack={() => undefined} {...(file ? { file, onFile: vi.fn() } : {})} />
        </WorkProviders>
    );
    return fake;
}

const listed = (fake: ReturnType<typeof fakeWork>) => fake.requests.filter((r) => r.method === 'GET' && r.path.endsWith('/sandbox/files') && r.query.get('view') === 'list');

it('reads a folder as it opens, never every file at once', async () => {
    const fake = open();
    const tree = await screen.findByRole('list', { name: 'Its files' });
    // The folders holding what the agent changed open by themselves; nothing else is read.
    await within(tree).findByText('worker.py');
    expect(listed(fake).every((r) => !r.query.has('recursive'))).toBe(true);
    expect(new Set(listed(fake).map((r) => r.query.get('path')))).toEqual(new Set(['/workspace', '/workspace/repo', '/workspace/repo/app', '/workspace/repo/app/retries', '/workspace/repo/tests']));
});

it('shows a .env’s names, never its values, and sets one without showing it', async () => {
    const fake = open('/workspace/.env');
    const file = await screen.findByTestId('secrets-file');
    await within(file).findByText('WIREFERN_ADMIN_KEY');
    expect(within(file).getAllByText('Value hidden')).toHaveLength(2);

    fireEvent.click(within(file).getByRole('button', { name: 'Add a value' }));
    fireEvent.change(within(file).getByRole('textbox', { name: 'Name' }), { target: { value: 'OPENAI_API_KEY' } });
    fireEvent.change(within(file).getByLabelText('OPENAI_API_KEY value'), { target: { value: 'sk-live-123' } });
    fireEvent.click(within(file).getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(fake.requests.find((r) => r.method === 'PATCH')?.body).toEqual({ set: { OPENAI_API_KEY: 'sk-live-123' }, unset: [] }));
    await within(file).findByText('OPENAI_API_KEY');
    expect(within(file).getAllByText('Value hidden')).toHaveLength(3);
    expect(document.body.textContent).not.toContain('sk-live-123');
});

it('makes a file it links to that isn’t there yet', async () => {
    const fake = open('/workspace/todo.md');
    const text = await screen.findByRole('textbox', { name: 'todo.md’s text' });
    fireEvent.change(text, { target: { value: '# Ship it\n' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create it' }));

    await waitFor(() => expect(fake.requests.find((r) => r.method === 'PUT')?.query.get('path')).toBe('/workspace/todo.md'));
    // Read back from where it runs, as any file.
    expect(await screen.findByRole('heading', { name: 'Ship it' })).toBeTruthy();
});
