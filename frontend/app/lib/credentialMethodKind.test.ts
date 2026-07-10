// Drift guard for the credential-method-kind discriminator. Scans every node JSON
// schema and asserts that each x-credential-type value present resolves to a known
// CredentialMethodKind — so a NEW discriminator (a future auth flow) fails here until
// someone consciously wires a kind + registry entry (or marks it field-based). This is
// what keeps a WhatsApp-QR-style regression (a kind the provide page silently mis-renders)
// from ever shipping unnoticed.

import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { kindFromCredentialType, type CredentialMethodKind } from './credentialMethodKind';

const KNOWN_KINDS: CredentialMethodKind[] = ['api_key', 'oauth', 'agent_oauth', 'qr_scan'];

// x-credential-type values we've consciously accounted for. Field-based ones
// (e.g. Reddit's "script": client_id/secret/username/password) resolve to api_key.
const KNOWN_DISCRIMINATORS = ['oauth', 'qr_scan', 'script'];

const schemasDir = join(dirname(fileURLToPath(import.meta.url)), '../schemas/nodes');

function collectDiscriminators(): Set<string> {
    const present = new Set<string>();
    for (const file of readdirSync(schemasDir)) {
        if (!file.endsWith('.json')) continue;
        const schema = JSON.parse(readFileSync(join(schemasDir, file), 'utf8'));
        for (const defn of Object.values(schema.$defs ?? {}) as Record<string, unknown>[]) {
            const xct = defn?.['x-credential-type'];
            if (typeof xct === 'string') present.add(xct);
        }
    }
    return present;
}

describe('credentialMethodKind discriminator', () => {
    it('maps each discriminator to a kind; absent → api_key', () => {
        expect(kindFromCredentialType('oauth')).toBe('oauth');
        expect(kindFromCredentialType('qr_scan')).toBe('qr_scan');
        expect(kindFromCredentialType('script')).toBe('api_key'); // field-based
        expect(kindFromCredentialType(undefined)).toBe('api_key');
        expect(kindFromCredentialType(null)).toBe('api_key');
    });

    it('every x-credential-type in the node schemas resolves to a known kind', () => {
        const present = collectDiscriminators();
        // Sanity: we actually read schemas (else the guard would be vacuous).
        expect(present.size).toBeGreaterThan(0);
        for (const xct of present) {
            expect(
                KNOWN_DISCRIMINATORS,
                `Unhandled x-credential-type "${xct}". Add a CredentialMethodKind + a ` +
                `CREDENTIAL_METHOD_COMPONENTS entry (interactive flow), or add it to the ` +
                `known field-based discriminators.`,
            ).toContain(xct);
            expect(KNOWN_KINDS).toContain(kindFromCredentialType(xct));
        }
    });
});
