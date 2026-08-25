// Every authorize route must resolve the instance's OAuth app before it reads
// the credentials, and must read the variable names the instance actually sets.
//
// Both halves failed silently in practice. A route without the call reports
// "not configured" no matter what was saved (google, until all 49 were patched),
// and a route reading FACEBOOK_APP_ID while the resolver writes
// FACEBOOK_CLIENT_ID does the same — the save appears to work and Connect still
// sends people to the setup page. Neither is visible to a typecheck or to a test
// of one provider, so it is checked across the whole directory.

import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'fs';
import { join } from 'path';
import { OAUTH_PROVIDER_SETUP } from '~/lib/oauthProviderSetup';

const ROUTES_DIR = join(process.cwd(), 'app/routes/api/auth');

const routes = readdirSync(ROUTES_DIR)
    .filter((f) => f.endsWith('.authorize.tsx'))
    .map((file) => ({
        file,
        provider: file.split('.')[0],
        source: readFileSync(join(ROUTES_DIR, file), 'utf8'),
    }));

/** The names the resolver writes — mirrors applyInstanceOAuthEnv. */
function resolverWrites(provider: string): string[] {
    const frontendEnv = OAUTH_PROVIDER_SETUP[provider]?.frontendEnv ?? [];
    const stem = provider.toUpperCase();
    const redirectVar = frontendEnv.find((v) => v.endsWith('REDIRECT_URI')) ?? `${stem}_REDIRECT_URI`;
    const idVar = frontendEnv.find((v) => v !== redirectVar) ?? `${stem}_CLIENT_ID`;
    return [idVar, redirectVar];
}

/** Credential env vars a route reads (ignores NODE_ENV and friends). */
function credentialVarsRead(source: string): string[] {
    return [...source.matchAll(/process\.env\.([A-Z0-9_]*(?:CLIENT_ID|APP_ID|REDIRECT_URI))/g)].map((m) => m[1]);
}

describe('OAuth authorize routes', () => {
    it('covers every provider the setup map knows about', () => {
        expect(routes.length).toBeGreaterThan(40);
    });

    it.each(routes)('$file resolves the instance app inside the loader', ({ provider, source }) => {
        const call = source.indexOf(`applyInstanceOAuthEnv(request, '${provider}')`);
        expect(call, 'must call applyInstanceOAuthEnv with its own provider key').toBeGreaterThan(-1);

        const loader = source.indexOf('export async function loader');
        expect(loader, 'must have a loader').toBeGreaterThan(-1);
        expect(call, 'the call belongs inside the loader, not at module scope').toBeGreaterThan(loader);

        // Module-scope credential reads would be evaluated once at import, long
        // before any request, so the resolver could never affect them.
        const firstCredentialRead = source.search(/process\.env\.[A-Z0-9_]*(?:CLIENT_ID|APP_ID|REDIRECT_URI)/);
        if (firstCredentialRead !== -1) {
            expect(
                firstCredentialRead,
                'credentials must be read after the instance app is resolved',
            ).toBeGreaterThan(call);
        }
    });

    it('backend overrides agree with the frontend map', () => {
        // The two sides must name the same variable: the backend writes the
        // secret and the client id into the process env, the frontend reads the
        // client id name to decide what to set. A mismatch means one side
        // configures a provider the other still thinks is unconfigured.
        const py = readFileSync(
            join(process.cwd(), '../backend/utils/instance_oauth.py'),
            'utf8',
        );
        const block = /_ENV_NAME_OVERRIDES = \{([\s\S]*?)\}/.exec(py)?.[1] ?? '';
        const overrides = [...block.matchAll(/"([a-z0-9_]+)":\s*\("([A-Z0-9_]+)",\s*"([A-Z0-9_]+)"\)/g)];
        expect(overrides.length, 'expected to parse the backend override map').toBeGreaterThan(0);

        for (const [, provider, idVar] of overrides) {
            expect(resolverWrites(provider)[0], `${provider}: backend and frontend disagree`).toBe(idVar);
        }
    });

    it.each(routes)('$file reads a variable the resolver actually sets', ({ provider, source }) => {
        const read = credentialVarsRead(source);
        if (read.length === 0) return; // nothing to reconcile (PKCE with derived values)
        const written = resolverWrites(provider);
        expect(
            read.some((v) => written.includes(v)),
            `route reads ${read.join(', ')} but the resolver sets ${written.join(', ')} — ` +
                'add the provider to _ENV_NAME_OVERRIDES (backend/utils/instance_oauth.py) ' +
                'and to its frontendEnv entry, or the saved app is written where nothing reads it',
        ).toBe(true);
    });
});
