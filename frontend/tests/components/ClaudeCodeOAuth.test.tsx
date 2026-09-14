// @vitest-environment jsdom
// Exercise sign-in recovery through the same component both transports render.
// A consumed code must never be resubmitted through the old authorization session.
import React from 'react';
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ClaudeCodeOAuth } from '~/components/workflow/ClaudeCodeOAuth';

vi.mock('~/hooks/useAgentOAuthAnalytics', () => ({
    useAgentOAuthAnalytics: () => ({ started: vi.fn(), completed: vi.fn(), failed: vi.fn() }),
}));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('shows the real failure and starts with a fresh session and empty code', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    const send = vi.fn()
        .mockResolvedValueOnce({ success: true, auth_url: 'https://example.test/auth', auth_session_id: 'first' })
        .mockResolvedValueOnce({ success: false, message: 'Credential limit reached', restart_required: true })
        .mockResolvedValueOnce({ success: true, auth_url: 'https://example.test/auth', auth_session_id: 'second' })
        .mockResolvedValueOnce({ success: true, credential_id: 'new' });
    const onChange = vi.fn();
    render(<ClaudeCodeOAuth credentialIds={{}} onCredentialIdsChange={onChange} onCredentialCreated={async () => {}} sendEvent={send} />);
    fireEvent.click(screen.getByRole('button', { name: 'Connect with Claude account' }));
    fireEvent.change(await screen.findByPlaceholderText('Paste code here...'), { target: { value: 'old-code' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Token' }));
    await screen.findByText('Credential limit reached');
    expect(screen.queryByPlaceholderText('Paste code here...')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    fireEvent.click(screen.getByRole('button', { name: 'Connect with Claude account' }));
    const input = await screen.findByPlaceholderText('Paste code here...') as HTMLInputElement;
    expect(input.value).toBe('');
    fireEvent.change(input, { target: { value: 'fresh-code' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Token' }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith({ agent_claude_code_oauth: 'new' }));
    expect(send.mock.calls[3][0]).toMatchObject({ auth_session_id: 'second', authorization_code: 'fresh-code' });
});

it('binds reconnect to the selected credential and retains the credential ID', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    const send = vi.fn()
        .mockResolvedValueOnce({ success: true, auth_url: 'https://example.test/auth', auth_session_id: 'reconnect' })
        .mockResolvedValueOnce({ success: true, credential_id: 'saved', message: 'Claude connection refreshed' });
    const onChange = vi.fn();
    render(<ClaudeCodeOAuth credentialIds={{ agent_claude_code_oauth: 'saved' }} onCredentialIdsChange={onChange} onCredentialCreated={async () => {}} sendEvent={send} />);
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect selected Claude account' }));
    fireEvent.change(await screen.findByPlaceholderText('Paste code here...'), { target: { value: 'new-code' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Token' }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith({ agent_claude_code_oauth: 'saved' }));
    expect(send.mock.calls.map(([request]) => request.credential_id)).toEqual(['saved', 'saved']);
});
