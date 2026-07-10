// The public credential-provide page's OAuth transport — the single HTTP seam that
// lets the SAME provider hooks (redirect OAuth) and agent OAuth components run without
// an authed socket. It maps the socket-shaped events those hooks emit onto the
// token-scoped credential-request endpoints, storing the credential for the requester:
//   - redirect OAuth   `{provider}:oauth:exchange`        -> POST /provide (code exchange)
//   - agent device/PKCE `{provider}:auth:{start|poll|exchange}` -> /agent-oauth/{start,complete}
//   - WhatsApp QR scan  `whatsapp:qr:{start|status}`        -> /qr/{start,status}
// Bound to the active method's credential_type. Shaped like sendEventAsync so it drops
// straight into OAuthExchangeContext, AgentOAuthConnect's sendEvent, and the QR form's.

import type { OAuthExchange } from '~/hooks/oauth/OAuthExchangeContext';

export function provideLinkTransport(apiBase: string, token: string, credentialType: string): OAuthExchange {
    const base = `${apiBase}/api/credential-request/${token}`;

    return async (event) => {
        const name: string = event?.event_name || '';

        // --- WhatsApp QR scan (start → poll status) ---
        // The QR credential is minted server-side bound to the requester; the
        // shapes returned mirror the socket responses the QR form already reads.
        if (name === 'whatsapp:qr:start' || name === 'whatsapp:qr:status') {
            const isStart = name === 'whatsapp:qr:start';
            const res = await fetch(`${base}/qr/${isStart ? 'start' : 'status'}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(isStart ? {} : { connection_id: event.connection_id }),
            });
            if (!res.ok) {
                const e = await res.json().catch(() => ({}));
                return { success: false, status: 'error', message: e.detail || 'WhatsApp connection failed' };
            }
            return await res.json();
        }

        // --- Agent CLI OAuth (device-code / PKCE) ---
        if (/:auth:(start|poll|exchange)$/.test(name)) {
            if (name.endsWith(':start')) {
                const res = await fetch(`${base}/agent-oauth/start`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ credential_type: credentialType }),
                });
                if (!res.ok) {
                    const e = await res.json().catch(() => ({}));
                    return { success: false, message: e.detail || 'Failed to start sign-in' };
                }
                const d = await res.json();
                const disp = d.display || {};
                const poll = d.poll || {};
                return {
                    success: true,
                    verification_url: disp.verification_url,
                    verification_uri: disp.verification_url,
                    verification_uri_complete: disp.verification_uri_complete,
                    user_code: disp.user_code,
                    device_auth_id: poll.device_auth_id,
                    device_code: poll.device_code,
                    interval: disp.interval,
                    expires_in: disp.expires_in,
                    auth_url: disp.authorize_url,
                    auth_session_id: poll.auth_session_id,
                };
            }
            // poll / exchange → complete
            const poll: Record<string, unknown> = {};
            for (const k of ['device_auth_id', 'user_code', 'device_code', 'auth_session_id']) {
                if (event[k] !== undefined) poll[k] = event[k];
            }
            if (event.authorization_code !== undefined) poll.code = event.authorization_code;
            const res = await fetch(`${base}/agent-oauth/complete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ credential_type: credentialType, poll }),
            });
            if (!res.ok) {
                const e = await res.json().catch(() => ({}));
                return { success: false, status: 'error', message: e.detail || 'Sign-in failed' };
            }
            const r = await res.json();
            if (r.status === 'success') return { success: true, status: 'completed', credential_id: r.credential_id };
            return { success: true, status: r.status };
        }

        // --- Redirect OAuth exchange ---
        if (/:oauth:exchange$/.test(name)) {
            const res = await fetch(`${base}/provide`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    credential_type: credentialType,
                    oauth_code: event.code,
                    redirect_uri: event.redirect_uri,
                    scopes: event.scopes,
                    code_verifier: event.code_verifier,
                }),
            });
            if (!res.ok) {
                const e = await res.json().catch(() => ({}));
                return { success: false, error: e.detail || 'Failed to connect' };
            }
            const r = await res.json();
            return { success: r.status === 'success', credential_id: r.credential_id, message: r.message };
        }

        return { success: false, error: `Unsupported OAuth event: ${name}` };
    };
}
