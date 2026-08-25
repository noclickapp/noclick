// @vitest-environment jsdom
// auth.requestCredential: success resolves the credential; CANCEL (popup closed)
// resolves null per the SDK contract instead of hanging until the 30s timeout.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Decouple from the real provider map + avoid loading the big node registry.
vi.mock('~/utils/oauthProviders', () => ({ getProviderKeyFromCredentialType: () => 'github' }));
vi.mock('~/utils/nodeSchemas', () => ({ NODE_SCHEMAS: {} }));

import { mountBridge } from './helpers/mountBridge';
import { installMockSocket, type MockSocket } from '../integration/helpers/mockSocket';

let h: ReturnType<typeof mountBridge>;
let socket: MockSocket;
let teardown: () => void;

beforeEach(() => { ({ socket, teardown } = installMockSocket()); });
afterEach(() => { h?.cleanup(); teardown?.(); });

describe('SDK bridge — auth.requestCredential', () => {
  it('resolves null when the user cancels the OAuth popup', async () => {
    h = mountBridge({ workflowId: 'wf-1', oauth: true });
    const id = h.sendRequest('auth.requestCredential', { credentialType: 'github_oauth' });
    // The handler dynamically imports the provider map before registering callbacks.
    await vi.waitFor(() => expect(h.oauthConnectCalled()).toBe(true));

    h.fireOAuthCancel();
    expect(h.responsesFor(id)[0]).toEqual({ type: 'noclick:response', id, result: null });
  });

  it('resolves the credential on success', async () => {
    h = mountBridge({ workflowId: 'wf-1', oauth: true });
    socket.replyTo('credential:list', { credentials: [{ id: 'c1', credential_type: 'github_oauth', name: 'GH' }] });
    const id = h.sendRequest('auth.requestCredential', { credentialType: 'github_oauth' });
    await vi.waitFor(() => expect(h.oauthConnectCalled()).toBe(true));

    h.fireOAuthSuccess('c1');
    await vi.waitFor(() => expect(h.responsesFor(id).length).toBe(1));
    expect(h.responsesFor(id)[0].result).toMatchObject({ id: 'c1', type: 'github_oauth', name: 'GH' });
  });
});
