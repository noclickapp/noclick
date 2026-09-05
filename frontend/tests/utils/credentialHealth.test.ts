// The picker and auto-select judge a connection-backed credential by the
// backend's verdict, never by the provider's status word: WhatsApp reports a
// live session as 'connected' but Discord reports one as 'installed', and the
// string comparison that once lived here rendered every healthy Discord install
// as "(disconnected)" with WhatsApp re-scan copy under it (2026-09-05).

import { describe, expect, it } from 'vitest';

import { isConnectionDropped, isDeadCredential } from '~/utils/credentialAutoSelect';

describe('connection health verdicts', () => {
    it('a live Discord install is healthy even though its status word is not "connected"', () => {
        const cred = { connection_status: 'installed', connection_healthy: true };
        expect(isConnectionDropped(cred)).toBe(false);
        expect(isDeadCredential(cred)).toBe(false);
    });

    it('a removed Discord bot and a dropped WhatsApp session are both dead', () => {
        expect(isDeadCredential({ connection_status: 'removed', connection_healthy: false })).toBe(true);
        expect(isDeadCredential({ connection_status: 'scan_qr', connection_healthy: false })).toBe(true);
    });

    it('an unknown verdict is never dead, whatever the status word says', () => {
        expect(isDeadCredential({ connection_status: 'failed' })).toBe(false);
        expect(isDeadCredential({ connection_status: 'failed', connection_healthy: null })).toBe(false);
        expect(isDeadCredential({})).toBe(false);
    });

    it('revocation is terminal regardless of connection health', () => {
        expect(isDeadCredential({ revoked_at: '2026-09-05T00:00:00Z', connection_healthy: true })).toBe(true);
        expect(isConnectionDropped({ connection_healthy: true })).toBe(false);
    });
});
