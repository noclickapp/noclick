// @vitest-environment jsdom
// Reproduces the IN-APP OAuth connect end-to-end through the real integration:
// OAuthConnectForm → useOAuthConnect → the real Linear factory hook → the default
// OAuthExchangeContext transport (socket-sender, mocked here). Simulates the popup
// callback postMessage and asserts the exchange fires and onCredentialCreated runs —
// the exact path that "reported success but didn't connect".

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));

import { sendEventAsync } from '~/lib/socket-sender';
import { useOAuthConnect } from '~/hooks/useOAuthConnect';
import { OAuthConnectForm } from './OAuthConnectForm';

const mockedSend = vi.mocked(sendEventAsync);

function Harness({ provider, credentialType, displayName, scopes, onCreated }: {
    provider: string; credentialType: string; displayName: string; scopes: string[];
    onCreated: (id: string, provider: string) => void;
}) {
    const oauth = useOAuthConnect({ onCredentialCreated: onCreated });
    return (
        <OAuthConnectForm
            provider={provider}
            credentialType={credentialType}
            displayName={displayName}
            Icon={() => null}
            scopes={scopes}
            connect={oauth.connect}
            connectingProvider={oauth.connectingProvider}
            isConnecting={oauth.isConnecting}
            error={oauth.error}
            onClearError={oauth.clearError}
            pendingSelection={oauth.pendingSelection}
            onResolvePendingSelection={oauth.resolvePendingSelection}
            onCancel={oauth.cancelConnect}
        />
    );
}

// Factory provider (Linear) and a bespoke, auto-merged provider (Google) — both must
// send the exchange and report the credential on popup success.
const CASES = [
    { provider: 'linear', credentialType: 'linear_oauth', displayName: 'Linear', scopes: ['read', 'write'] },
    { provider: 'google', credentialType: 'google_sheets_oauth', displayName: 'Google', scopes: ['https://www.googleapis.com/auth/spreadsheets'] },
];

describe('OAuthConnectForm in-app end-to-end', () => {
    beforeEach(() => {
        mockedSend.mockReset();
        vi.stubGlobal('open', vi.fn(() => ({ closed: false, close: vi.fn() })));
    });
    afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

    for (const c of CASES) {
        it(`${c.provider}: sends the exchange and reports the created credential on popup success`, async () => {
            mockedSend.mockResolvedValue({ success: true, credential_id: 'cred-1', credential_name: c.displayName, credential_type: c.credentialType, email: 'me@x.com' });
            const onCreated = vi.fn();
            render(<Harness {...c} onCreated={onCreated} />);

            fireEvent.click(screen.getByRole('button', { name: new RegExp(`Connect ${c.displayName} Account`, 'i') }));
            expect(window.open).toHaveBeenCalledTimes(1);

            await act(async () => {
                window.dispatchEvent(new MessageEvent('message', {
                    origin: window.location.origin,
                    data: { type: `${c.provider}-oauth-callback`, success: true, code: 'abc', redirectUri: 'http://x/cb', scopes: c.scopes },
                }));
            });

            await waitFor(() => expect(mockedSend).toHaveBeenCalled());
            expect(mockedSend).toHaveBeenCalledWith(expect.objectContaining({
                event_name: `${c.provider}:oauth:exchange`, code: 'abc', redirect_uri: 'http://x/cb',
            }));
            await waitFor(() => expect(onCreated).toHaveBeenCalled());
            expect(onCreated.mock.calls[0][0]).toBe('cred-1');
            expect(onCreated.mock.calls[0][1]).toBe(c.provider);
        });
    }
});
