// @vitest-environment jsdom
// A shared link for an AI account draws Connections' own connect flow (AiConnect): the company's name, a plan's
// sign-in before its key, the key as get-it-then-paste-it steps with its console's link, and each saved over the
// link's own calls (2026-11-12: the link offered a bare "Anthropic API key" field first, under "Agent Anthropic").
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { appNameForCredentialType, CredentialProvideFlow, type ProvideRequestDetails } from '~/components/credential/CredentialProvideFlow';
import type { ProvideCredentialMethod } from '~/components/credential/CredentialMethodConnect';

const keyMethod = (credential_type: string, env: string, label: string): ProvideCredentialMethod => ({
    credential_type,
    label,
    description: '',
    credential_url: null,
    instructions: null,
    is_oauth: false,
    method_kind: 'api_key',
    agent_oauth_kind: null,
    credential_fields: [{ name: env, label, type: 'password', required: true }],
});

// As the backend lists a plan's sign-in on a link: its flow kind, not its credential type.
const signInMethod = (credential_type: string, label: string, kind: string): ProvideCredentialMethod => ({
    credential_type,
    label,
    is_oauth: true,
    method_kind: 'agent_oauth',
    agent_oauth_kind: kind,
    credential_fields: [],
});

const request = (overrides: Partial<ProvideRequestDetails>): ProvideRequestDetails => ({
    credential_type: 'agent_anthropic',
    requester_name: 'Maya',
    requester_email: null,
    is_oauth: false,
    requires_pkce: false,
    credential_fields: [],
    available_methods: [
        keyMethod('agent_anthropic', 'ANTHROPIC_API_KEY', 'Anthropic API Key'),
        signInMethod('agent_claude_code_oauth', 'Sign in with Claude', 'pkce'),
    ],
    status: 'pending',
    expires_at: '',
    ...overrides,
});

const calls: { url: string; body: Record<string, unknown> | null }[] = [];
let provideReply: () => Response;

beforeEach(() => {
    calls.length = 0;
    provideReply = () => new Response(JSON.stringify({ status: 'success', credential_id: 'c1', verification: { success: true, reachable: true } }));
    vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string, init?: RequestInit) => {
            calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
            if (url.endsWith('/instance-status')) return new Response(JSON.stringify({ capabilities: {} }));
            if (url.endsWith('/provide')) return provideReply();
            if (url.endsWith('/agent-oauth/start')) return new Response(JSON.stringify({ display: { authorize_url: 'https://claude.ai/oauth' }, poll: { auth_session_id: 's1' } }));
            if (url.endsWith('/agent-oauth/complete')) return new Response(JSON.stringify({ status: 'success', credential_id: 'c2' }));
            return new Response('{}', { status: 404 });
        })
    );
    vi.spyOn(window, 'open').mockReturnValue(null);
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

const tabs = () => screen.getAllByRole('tab').map((tab) => tab.textContent);

it('names an AI account by its company, never its credential type', () => {
    expect(appNameForCredentialType('agent_anthropic')).toBe('Anthropic');
    expect(appNameForCredentialType('agent_claude_code_oauth')).toBe('Anthropic');
    expect(appNameForCredentialType('agent_gemini')).toBe('Google Gemini');
});

it('offers the plan sign-in first, as Connections does, and starts it over the link', async () => {
    const onProvided = vi.fn();
    render(<CredentialProvideFlow token="t" apiBase="https://api.test" held={request({})} onProvided={onProvided} />);
    expect(tabs()).toEqual(['Sign in', 'API key']);
    fireEvent.click(screen.getByRole('button', { name: 'Sign in with Claude' }));
    expect(await screen.findByPlaceholderText('Paste the code')).toBeTruthy();
    expect(calls.find((c) => c.url === 'https://api.test/api/credential-request/t/agent-oauth/start')?.body).toEqual({ credential_type: 'agent_claude_code_oauth' });

    fireEvent.change(screen.getByPlaceholderText('Paste the code'), { target: { value: 'code#state' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(onProvided).toHaveBeenCalledWith());
    expect(calls.some((c) => c.url.endsWith('/agent-oauth/complete'))).toBe(true);
});

it('draws the key as numbered steps with its console, and saves it as the request names it', async () => {
    const onProvided = vi.fn();
    render(<CredentialProvideFlow token="t" apiBase="https://api.test" held={request({})} onProvided={onProvided} />);
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'API key' }));
    expect(screen.getByText('Get an API key')).toBeTruthy();
    expect(screen.getByRole('link', { name: /Open console\.anthropic\.com/ })).toBeTruthy();
    expect(screen.getByText('Paste it here')).toBeTruthy();
    expect(screen.getByText('It’s encrypted as soon as you send it.')).toBeTruthy();

    // The provider's refusal lands under the field it names, and nothing is provided.
    provideReply = () => new Response(JSON.stringify({ detail: { message: 'invalid x-api-key', field_errors: { ANTHROPIC_API_KEY: 'Refused.' }, hint: null, reachable: false } }), { status: 400 });
    const input = document.querySelector<HTMLInputElement>('input[type="password"]')!;
    fireEvent.change(input, { target: { value: 'sk-ant-bad' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    expect(await screen.findByText('Refused.')).toBeTruthy();
    expect(screen.getByText('invalid x-api-key')).toBeTruthy();
    expect(onProvided).not.toHaveBeenCalled();

    provideReply = () => new Response(JSON.stringify({ status: 'success', credential_id: 'c1', verification: { success: true, reachable: true } }));
    fireEvent.change(input, { target: { value: 'sk-ant-good' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    await waitFor(() => expect(onProvided).toHaveBeenCalledWith({ success: true, reachable: true }));
    expect(calls.filter((c) => c.url.endsWith('/provide')).at(-1)?.body).toEqual({
        credential_type: 'agent_anthropic',
        credential_data: { ANTHROPIC_API_KEY: 'sk-ant-good' },
    });
});

it('offers only the ways in the link can finish', () => {
    render(
        <CredentialProvideFlow
            token="t"
            apiBase=""
            held={request({ credential_type: 'agent_gemini', available_methods: [keyMethod('agent_gemini', 'GEMINI_API_KEY', 'Gemini API Key')] })}
            onProvided={() => {}}
        />
    );
    expect(screen.queryAllByRole('tab')).toHaveLength(0);
    expect(screen.getByRole('link', { name: /Open aistudio\.google\.com/ })).toBeTruthy();
});

it('orders an app’s ways in as Connections does: a sign-in first', () => {
    render(
        <CredentialProvideFlow
            token="t"
            apiBase=""
            held={request({
                credential_type: 'airtable_pat',
                available_methods: [
                    { ...keyMethod('airtable_pat', 'personal_access_token', 'AirtablePAT'), credential_url: 'https://airtable.com/create/tokens' },
                    { credential_type: 'airtable_oauth', label: 'AirtableOAuth', is_oauth: true, method_kind: 'oauth', oauth_provider: 'airtable', credential_fields: [] },
                ],
            })}
            onProvided={() => {}}
        />
    );
    expect(tabs()).toEqual(['Sign in', 'Personal access token']);
});
