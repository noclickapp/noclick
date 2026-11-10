// @vitest-environment happy-dom
// Connections' AI company dialog, the one place an AI account connects from: it offers the company's sign-ins (or the
// ones its host names) and its key, and tells its host which account landed, a plan by its sign-in and a key as saved.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { registerAgentOAuthComponent, type AgentOAuthComponentProps } from '~/components/workflow/AgentOAuthConnect';
import type { AiCompany } from './aiAccounts';
import { AiProviderDialog } from './AiProviderDialog';

// The key's save goes over the app's socket; it lands as the credential the app made.
vi.mock('~/hooks/useAgentApiKey', async (original) => ({
    ...(await original<object>()),
    createAgentKey: vi.fn(async () => ({ success: true, credential: { id: 'cred-key', name: 'Anthropic API key', credential_type: 'agent_anthropic' } })),
}));

// The sign-in's own flow runs in another tab; this one lands as the real one does: created, then its id reported.
registerAgentOAuthComponent('agent_claude_code_oauth', function SignedIn({ credentialIds, onCredentialIdsChange, onCredentialCreated, renderStart }: AgentOAuthComponentProps) {
    const start = async () => {
        await onCredentialCreated();
        onCredentialIdsChange({ ...credentialIds, agent_claude_code_oauth: 'cred-plan' });
    };
    return <>{renderStart?.(() => void start(), 'Opens Claude in a new tab.')}</>;
});

const ANTHROPIC = {
    id: 'anthropic',
    title: 'Anthropic',
    members: ['anthropic'],
    keys: ['anthropic'],
    signIns: ['agent_claude_code_oauth'],
    credentialTypes: ['agent_anthropic', 'agent_claude_code_oauth'],
    line: '',
    uses: 'Claude models for your agents.',
} as unknown as AiCompany;

afterEach(cleanup);

function show(props: Partial<Parameters<typeof AiProviderDialog>[0]> = {}) {
    const onConnected = vi.fn();
    const onOpenChange = vi.fn();
    render(<AiProviderDialog company={ANTHROPIC} onOpenChange={onOpenChange} onConnected={onConnected} {...props} />);
    return { onConnected, onOpenChange };
}

describe('the AI company dialog', () => {
    it('tells its host which plan a sign-in landed, and closes', async () => {
        const { onConnected, onOpenChange } = show();
        fireEvent.click(await screen.findByRole('button', { name: 'Sign in with Claude' }));
        await waitFor(() => expect(onConnected).toHaveBeenCalledWith('cred-plan'));
        expect(onOpenChange).toHaveBeenCalledWith(false);
    });

    it('offers only the sign-ins its host names, and tells it which key was saved', async () => {
        const { onConnected, onOpenChange } = show({ signIns: [] });
        await screen.findByTestId('connect-app');
        expect(screen.queryByRole('button', { name: 'Sign in with Claude' })).toBeNull();
        expect(screen.queryByRole('tablist')).toBeNull();
        fireEvent.change(screen.getByLabelText(/Anthropic API key|API key/i), { target: { value: 'sk-ant-0123456789' } });
        fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        await waitFor(() => expect(onConnected).toHaveBeenCalledWith('cred-key'));
        expect(onOpenChange).toHaveBeenCalledWith(false);
    });
});
