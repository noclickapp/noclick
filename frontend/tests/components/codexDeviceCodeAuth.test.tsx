// @vitest-environment happy-dom
// A ChatGPT plan's device-code sign-in, as the connect step and a plan link's page show it (the page passes its
// link's transport into the same component). OpenAI refuses the approval after the account is picked when the
// account hasn't turned on device code login, and its device poll can't tell that apart from waiting (it answers
// 403 while it waits), so the line saying what to turn on sits under the code from the start.
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { CodexDeviceCodeAuth } from '~/components/workflow/CodexDeviceCodeAuth';
import { DeviceCodePanel } from '~/components/workflow/DeviceCodePanel';

beforeEach(() => {
    vi.spyOn(window, 'open').mockImplementation(() => null);
});
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

const started = {
    success: true,
    verification_url: 'https://auth.openai.com/codex/device',
    user_code: 'AVJE-VI605',
    device_auth_id: 'dev-1',
    interval: 5,
};

async function showCode() {
    const sendEvent = vi.fn(async (event: { event_name: string }) => (event.event_name === 'codex:auth:start' ? started : { success: true, status: 'pending' }));
    render(<CodexDeviceCodeAuth credentialIds={{}} onCredentialIdsChange={() => {}} onCredentialCreated={async () => {}} sendEvent={sendEvent} />);
    fireEvent.click(screen.getByRole('button', { name: /Connect with ChatGPT account/ }));
    await screen.findByText('AVJE-VI605');
    return sendEvent;
}

it('says under the code what to turn on when OpenAI refuses the approval', async () => {
    await showCode();
    const hint = screen.getByTestId('device-code-hint');
    expect(hint.textContent).toBe(
        'If OpenAI shows an error after you choose your account, turn on device code login in ChatGPT → Settings → Security (a workspace’s admin turns it on for the workspace), then try again.'
    );
    const link = screen.getByRole('link', { name: 'device code login' });
    expect(link.getAttribute('href')).toBe('https://learn.chatgpt.com/docs/auth');
    expect(link.getAttribute('target')).toBe('_blank');
});

it('keeps saying it while the poll waits', async () => {
    const sendEvent = await showCode();
    fireEvent.click(screen.getByRole('button', { name: /I’ve approved it/ }));
    await vi.waitFor(() => expect(sendEvent).toHaveBeenCalledWith(expect.objectContaining({ event_name: 'codex:auth:poll' })));
    expect(await screen.findByTestId('device-code-hint')).toBeTruthy();
});

it('says nothing of the kind for a provider that has no such setting', () => {
    render(<DeviceCodePanel provider="GitHub" userCode="ABCD-1234" polling={false} onCancel={() => {}} onApproved={() => {}} />);
    expect(screen.queryByTestId('device-code-hint')).toBeNull();
});
