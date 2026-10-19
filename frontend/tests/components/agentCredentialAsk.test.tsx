// @vitest-environment jsdom
// The builder asking for an agent's account, as the chat's build card and Setup draw it: headed by whose account it
// is and what it's for, the account connected through the flow every app uses (a sign-in before a key, the key as
// get-it-then-paste-it), and answered only by an account that runs the agent's model. An agent switched from OpenCode
// to Claude Code still held its OpenCode key, which read as answered (a green tick, Continue enabled) while the form
// showed nothing chosen (2026-10-17).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { InputRequest } from '~/components/workflow/workflowGeneratorMock';

const { sendEventAsync } = vi.hoisted(() => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync, sendEvent: vi.fn() }));
vi.mock('~/hooks/useModels', () => ({
    useModels: () => ({ getModelById: (id: string) => (id === 'claude-code' ? { id, provider: 'claude_code' } : undefined) }),
}));
vi.mock('~/hooks/useInstanceCapabilities', () => ({
    useInstanceCapabilities: () => ({ agentSignIns: { claude_code: 'agent_claude_code_oauth' } }),
}));

import { AgentCredentialsForm } from '~/components/workflow/AgentCredentialsForm';
import { BuilderInputDrawer } from '~/components/chat/drawer/BuilderInputDrawer';
import { storedVerdictLine } from '~/components/credential/ConnectionVerdict';

afterEach(() => {
    cleanup();
    sendEventAsync.mockReset();
});

const CLAUDE_CODE = { model: 'claude-code', opencode_model: 'opencode/big-pickle' };
const credential = (id: string, credential_type: string, name: string) => ({ id, credential_type, name, created_at: '2026-10-01', updated_at: '2026-10-01' });

function serve(credentials: ReturnType<typeof credential>[]) {
    sendEventAsync.mockImplementation(async (req: { event_name: string; credential_type?: string; name?: string }) => {
        if (req.event_name === 'credential:list') return { credentials };
        // A key saves: the new account joins the list the form reads next.
        if (req.event_name === 'credential:create') {
            const made = credential('new', req.credential_type!, req.name || 'New key');
            credentials.push(made);
            return { success: true, credential: made, verification: null };
        }
        return {};
    });
}

async function connectAKey() {
    fireEvent.mouseDown(await screen.findByRole('tab', { name: 'API key' }));
    fireEvent.change(await screen.findByLabelText('API key', { selector: 'input' }), { target: { value: 'sk-ant-test' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
}

describe('an agent’s account in a compact host', () => {
    it('takes an account that runs the model, dropping the key left from another harness', async () => {
        serve([credential('oc', 'agent_opencode', 'OpenCode key'), credential('ak', 'agent_anthropic', 'Work key')]);
        const onChange = vi.fn();
        render(<AgentCredentialsForm nodeData={{ config: CLAUDE_CODE }} credentialIds={{ agent_opencode: 'oc' }} onCredentialIdsChange={onChange} compact />);
        await waitFor(() => expect(onChange).toHaveBeenCalledWith({ agent_claude_code: 'ak' }));
        // No raw form chrome: no provider heading, no billing aside, no Advanced while there are no env vars.
        expect(screen.queryByText(/Credentials$/)).toBeNull();
        expect(screen.queryByText(/prepaid credits/)).toBeNull();
        expect(screen.queryByText('Advanced')).toBeNull();
    });

    it('offers picking or connecting the account, never sharing or deleting it', async () => {
        serve([credential('ak', 'agent_anthropic', 'Work key')]);
        render(<AgentCredentialsForm nodeData={{ config: CLAUDE_CODE }} credentialIds={{ agent_claude_code: 'ak' }} onCredentialIdsChange={vi.fn()} compact />);
        expect((await screen.findByTestId('agent-credential-dropdown')).textContent).toContain('Work key');
        expect(screen.queryByRole('button', { name: /^(Share|Delete) / })).toBeNull();
    });

    it('with no account that runs it, opens the connect flow: the Claude sign-in first, then the key', async () => {
        serve([credential('oc', 'agent_opencode', 'OpenCode key')]);
        render(<AgentCredentialsForm nodeData={{ config: CLAUDE_CODE }} credentialIds={{ agent_opencode: 'oc' }} onCredentialIdsChange={vi.fn()} compact />);
        await waitFor(() => expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual(['Sign in', 'API key']));
        expect(screen.getByRole('button', { name: 'Sign in with Claude' })).toBeTruthy();
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'API key' }));
        expect(await screen.findByText('Paste it here')).toBeTruthy();
        // Asking someone else belongs to the host (the chat's Copy link), not to a compact form.
        expect(screen.queryByText(/Ask someone who can/)).toBeNull();
    });
});

describe('the builder’s question for an agent’s account', () => {
    const ask = (extra: Partial<InputRequest> = {}): InputRequest => ({
        id: 'ask_0',
        nodeId: 'agent',
        type: 'credential',
        label: 'Choose a Claude Code-compatible Anthropic credential?',
        description: '',
        required: true,
        nodeType: 'agent',
        fieldKey: 'credential',
        credentialType: 'agent_claude_code',
        credentialIds: { agent_opencode: 'oc' },
        nodeConfig: CLAUDE_CODE,
        ...extra,
    });
    const continueButton = () => screen.getByRole('button', { name: /Continue/ }) as HTMLButtonElement;

    it('reads as whose account and what it’s for, and a key from another harness answers nothing', async () => {
        serve([credential('oc', 'agent_opencode', 'OpenCode key')]);
        render(<BuilderInputDrawer embedded inputs={[ask()]} onSubmit={vi.fn()} />);
        const heading = await screen.findByTestId('credential-ask-heading');
        expect(heading.textContent).toContain('Connect Anthropic');
        expect(heading.textContent).toContain('The AI this agent thinks with, on your own account.');
        expect(screen.queryByText('Choose a Claude Code-compatible Anthropic credential?')).toBeNull();
        expect(continueButton().disabled).toBe(true);
    });

    it('answers with the account the form picks, never the environment bundle beside it', async () => {
        serve([credential('ak', 'agent_anthropic', 'Work key')]);
        const onSubmit = vi.fn();
        render(<BuilderInputDrawer embedded inputs={[ask({ credentialIds: { agent_env: 'env', agent_opencode: 'oc' } })]} onSubmit={onSubmit} />);
        await waitFor(() => expect(continueButton().disabled).toBe(false));
        fireEvent.click(continueButton());
        expect(onSubmit).toHaveBeenCalledWith({ ask_0: 'ak' });
    });

    it('a lone question is answered the moment the person connects an account, with no second tap', async () => {
        serve([]);
        const onSubmit = vi.fn();
        render(<BuilderInputDrawer embedded inputs={[ask()]} onSubmit={onSubmit} />);
        await connectAKey();
        await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ ask_0: 'new' }));
    });

    it('with more questions to go, a connected account is only chosen', async () => {
        serve([]);
        const onSubmit = vi.fn();
        const next: InputRequest = { id: 'ask_1', nodeId: 'agent', type: 'text', label: 'What should it do first?', description: '', required: false };
        render(<BuilderInputDrawer embedded inputs={[ask(), next]} onSubmit={onSubmit} />);
        await connectAKey();
        await waitFor(() => expect((screen.getByRole('button', { name: /Next/ }) as HTMLButtonElement).disabled).toBe(false));
        expect(onSubmit).not.toHaveBeenCalled();
    });

    it('starts answered when the server says an attached account already runs the model', async () => {
        serve([]);
        const onSubmit = vi.fn();
        render(<BuilderInputDrawer embedded inputs={[ask({ credentialIds: { agent_anthropic: 'ak' }, defaultValue: 'ak' })]} onSubmit={onSubmit} />);
        fireEvent.click(continueButton());
        expect(onSubmit).toHaveBeenCalledWith({ ask_0: 'ak' });
    });
});

describe('what an account’s row remembers its check proved', () => {
    it('names who it is, else something it reached, else the sign-in’s email', () => {
        expect(storedVerdictLine({ verified_as: 'dhruv@acme.co' })).toBe('Verified as dhruv@acme.co');
        expect(storedVerdictLine({ verified_with: 'Sales' })).toBe('Verified, it can see Sales');
        expect(storedVerdictLine({ email: 'dhruv@acme.co' })).toBe('dhruv@acme.co');
        expect(storedVerdictLine({})).toBeNull();
    });
});
