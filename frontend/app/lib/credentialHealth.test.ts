// Unit tests for attached-credential health — the logic that turns a revoked/
// deleted-but-still-attached credential into an explicit UI state instead of
// an indistinguishable "Connected".

import { describe, it, expect } from 'vitest';
import {
    credentialHealth,
    attachedCredentialsHealth,
    credentialHealthMessage,
} from './credentialHealth';

const LIVE = { id: 'live-1', revoked_at: null };
const REVOKED = { id: 'dead-1', revoked_at: '2026-07-16T18:05:18Z' };

describe('credentialHealth', () => {
    it('reports ok for a live credential', () => {
        expect(credentialHealth('live-1', [LIVE, REVOKED])).toBe('ok');
    });

    it('reports revoked for a revoked credential', () => {
        expect(credentialHealth('dead-1', [LIVE, REVOKED])).toBe('revoked');
    });

    it('reports unknown for an id absent from the list', () => {
        expect(credentialHealth('gone-1', [LIVE])).toBe('unknown');
    });

    it('treats nothing-attached as ok (that is a different indicator)', () => {
        expect(credentialHealth(undefined, [LIVE])).toBe('ok');
        expect(credentialHealth(null, [LIVE])).toBe('ok');
    });
});

describe('attachedCredentialsHealth', () => {
    it('fails safe on an empty (not-yet-loaded) list', () => {
        expect(attachedCredentialsHealth({ t: 'dead-1' }, [])).toBe('ok');
    });

    it('revoked beats unknown beats ok across slots', () => {
        const creds = [LIVE, REVOKED];
        expect(attachedCredentialsHealth({ a: 'live-1' }, creds)).toBe('ok');
        expect(
            attachedCredentialsHealth({ a: 'live-1', b: 'gone-1' }, creds)
        ).toBe('unknown');
        expect(
            attachedCredentialsHealth({ a: 'gone-1', b: 'dead-1' }, creds)
        ).toBe('revoked');
    });

    it('handles empty/absent credentialIds', () => {
        expect(attachedCredentialsHealth({}, [LIVE])).toBe('ok');
        expect(attachedCredentialsHealth(undefined, [LIVE])).toBe('ok');
    });
});

describe('credentialHealthMessage', () => {
    it('has copy for both broken states and none for ok', () => {
        expect(credentialHealthMessage('revoked')).toMatch(/revoked/i);
        expect(credentialHealthMessage('unknown')).toMatch(/no longer exists/i);
        expect(credentialHealthMessage('ok')).toBeNull();
    });
});
