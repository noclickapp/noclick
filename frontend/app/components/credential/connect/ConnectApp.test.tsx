// @vitest-environment jsdom
// The shipped connect flow: a switch between the ways in, a key as numbered steps (get it, with the button that
// opens where it comes from, paste it, then the form's Connect as the last), one line that swaps in asking someone who can, and what connecting
// proved. Four ways in sit two to a row with the app's own name left off a sign-in's.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ConnectApp, connectDialogHeader } from './ConnectApp';
import type { ProvideCredentialMethod } from '~/components/credential/CredentialMethodConnect';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';

afterEach(cleanup);

const signIn = (credential_type: string, label: string, oauth_provider = 'notion'): ProvideCredentialMethod => ({
    credential_type,
    label,
    method_kind: 'oauth',
    is_oauth: true,
    oauth_provider,
    credential_fields: [],
});

const token: ProvideCredentialMethod = {
    credential_type: 'notion_integration_token',
    label: 'Notion Integration Token',
    method_kind: 'api_key',
    is_oauth: false,
    credential_url: 'https://www.notion.so/my-integrations',
    description:
        'Internal Integration Token credential for Notion.\n\nCreate an internal integration at: https://www.notion.so/my-integrations\nThen share the desired pages/databases with your integration.',
    credential_fields: [{ name: 'integration_token', label: 'Internal Integration Token', type: 'password', required: true }],
};

const renderMethod = (method: ProvideCredentialMethod) => <div data-testid={`form-${method.credential_type}`} />;

describe('ConnectApp', () => {
    it('switches between the ways in, and shows a key as get it, then paste it', async () => {
        render(<ConnectApp app="Notion" methods={[signIn('notion_oauth', 'NotionOAuth'), token]} renderMethod={renderMethod} />);
        const tabs = screen.getAllByRole('tab').map((t) => t.textContent);
        expect(tabs).toEqual(['Sign in', 'Integration token']);
        expect(screen.getByTestId('form-notion_oauth')).toBeTruthy();

        // Real tabs: arrow keys move between the ways in, and each way is its own panel.
        const signInTab = screen.getByRole('tab', { name: 'Sign in' });
        signInTab.focus();
        fireEvent.keyDown(signInTab, { key: 'ArrowRight' });
        // Radix moves focus on the next tick.
        await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
        expect(document.activeElement).toBe(screen.getByRole('tab', { name: 'Integration token' }));
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'Integration token' }), { button: 0 });
        expect(screen.getByRole('tabpanel')).toBeTruthy();
        expect(screen.getByText('Get an internal integration token')).toBeTruthy();
        expect(screen.getByText('Create an internal integration. Then share the desired pages/databases with your integration.')).toBeTruthy();
        expect(screen.getByRole('link', { name: /Open notion\.so/ }).getAttribute('href')).toBe('https://www.notion.so/my-integrations');
        expect(screen.getByText('Paste it here')).toBeTruthy();
        expect(screen.getByTestId('form-notion_integration_token')).toBeTruthy();
    });

    it('ends a key’s steps on the form’s own Connect, numbered 3', () => {
        const form = (method: ProvideCredentialMethod) => (
            <CredentialCreatePanel app="Notion" fields={method.credential_fields} onSave={async () => null} showSources={false} />
        );
        render(<ConnectApp app="Notion" methods={[token]} renderMethod={form} />);
        const connect = screen.getByRole('button', { name: 'Connect' });
        expect(connect.closest('form')).toBeTruthy();
        const row = connect.parentElement!.parentElement!.parentElement!;
        expect(row.firstElementChild!.textContent).toBe('3');
        expect(row.firstElementChild!.getAttribute('aria-hidden')).toBe('true');
        cleanup();
        // The same form outside the steps keeps its button alone.
        render(form(token));
        expect(screen.getByRole('button', { name: 'Connect' }).parentElement!.parentElement!.tagName).toBe('FORM');
    });

    it('swaps in asking someone who can, and back', () => {
        const onStage = vi.fn();
        render(
            <ConnectApp
                app="Notion"
                methods={[token]}
                renderMethod={renderMethod}
                ask={{ credentialType: 'notion_integration_token', send: vi.fn() }}
                onStage={onStage}
            />
        );
        expect(screen.queryByRole('tablist')).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'Ask someone who can' }));
        expect(onStage).toHaveBeenLastCalledWith('ask', undefined);
        expect(screen.getByRole('button', { name: 'Send request' })).toBeTruthy();
        // Focus moves into the new stage instead of dropping to the dialog.
        expect(document.activeElement?.tagName).toBe('INPUT');
        expect(screen.queryByTestId('form-notion_integration_token')).toBeNull();

        fireEvent.click(screen.getByRole('button', { name: 'Connect it yourself instead' }));
        expect(onStage).toHaveBeenLastCalledWith('connect', undefined);
        expect(screen.getByTestId('form-notion_integration_token')).toBeTruthy();
    });

    it('names a second sign-in by what it goes through, two ways to a row', () => {
        const methods = [
            signIn('instagram_login', 'Instagram Login', 'instagram'),
            signIn('instagram_oauth', 'Instagram with Facebook Login', 'facebook'),
            { ...token, credential_type: 'instagram_system_user', label: 'System User Token', description: null, credential_url: null },
            { ...token, credential_type: 'instagram_page_token', label: 'Page Access Token', description: null, credential_url: null },
        ];
        render(<ConnectApp app="Instagram" methods={methods} renderMethod={renderMethod} />);
        const names = screen.getAllByRole('tab').map((t) => t.textContent);
        expect(names.slice(0, 2)).toEqual(['Instagram Login', 'Facebook Login']);
        expect(screen.getByRole('tablist').className).toContain('grid-cols-2');
    });

    it('ends on what connecting proved', () => {
        const onDone = vi.fn();
        const proved = { kind: 'api_key' as const, verification: { reachable: true, noun: 'pages', samples: [{ label: 'Roadmap' }] } };
        render(<ConnectApp app="Notion" methods={[token]} renderMethod={renderMethod} initial={{ stage: 'done', result: proved }} onDone={onDone} />);
        expect(screen.getByText('Your pages')).toBeTruthy();
        expect(screen.getByText('Roadmap')).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Done' }));
        expect(onDone).toHaveBeenCalled();

        expect(connectDialogHeader('Notion', 'done', proved).title).toBe('Notion is connected');
        expect(connectDialogHeader('Notion', 'done', { kind: 'api_key', verification: { reachable: null } }).title).toBe('Notion is saved');
        // A sign-in the provider didn't refuse is connected; one it refused is not.
        expect(connectDialogHeader('Notion', 'done', { kind: 'oauth', verification: null }).title).toBe('Notion is connected');
        expect(connectDialogHeader('Notion', 'done', { kind: 'oauth', verification: { reachable: false } }).title).toBe('Notion is saved');
    });
});
