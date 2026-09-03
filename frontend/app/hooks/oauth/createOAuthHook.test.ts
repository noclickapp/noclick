// Contract test for the OAuth hook factory. Pins the risky per-provider surface
// (authorize path, scopes, delimiter) that the 35→factory collapse could get wrong,
// and enforces the robustness invariant that fixed the Linear bug: NO provider's
// scopes are mutated (no email/profile injected). buildAuthorizeUrl is pure, so this
// runs in the node env with no DOM.

import { describe, it, expect } from 'vitest';
import { buildAuthorizeUrl } from './createOAuthHook';
import { useLinearOAuth } from './useLinearOAuth';
import { useAttioOAuth } from './useAttioOAuth';
import { useMicrosoftOAuth } from './useMicrosoftOAuth';
import { useNotionOAuth } from './useNotionOAuth';
import { useGithubOAuth } from './useGithubOAuth';
import { useZoomOAuth } from './useZoomOAuth';
import { useCalendlyOAuth } from './useCalendlyOAuth';

const cfg = (h: any) => h.oauthConfig;
const scopesOf = (url: string) => new URL(url, 'http://x').searchParams.get('scopes');

describe('createOAuthHook contract', () => {
    it('exposes each factory hook config', () => {
        for (const h of [useLinearOAuth, useAttioOAuth, useMicrosoftOAuth, useNotionOAuth, useGithubOAuth, useZoomOAuth, useCalendlyOAuth]) {
            expect(cfg(h)?.provider).toBeTruthy();
        }
    });

    it('builds the standard authorize URL from config (Linear)', () => {
        expect(buildAuthorizeUrl(cfg(useLinearOAuth), 'my cred')).toBe(
            '/api/auth/linear/authorize?name=my+cred&scopes=read%2Cwrite%2Cissues%3Acreate%2Ccomments%3Acreate',
        );
    });

    it('honours per-provider deviations: attio space delimiter', () => {
        const s = scopesOf(buildAuthorizeUrl(cfg(useAttioOAuth), 'x'));
        expect(s).toContain(' ');
        expect(s).not.toContain(',');
    });

    it('honours per-provider deviations: microsoft https:// scopes are preserved', () => {
        expect(buildAuthorizeUrl(cfg(useMicrosoftOAuth), 'x')).toContain(
            'https%3A%2F%2Fgraph.microsoft.com%2FMail.Send',
        );
    });

    it('honours per-provider deviations: Notion and Zoom send no scopes param', () => {
        for (const hook of [useNotionOAuth, useZoomOAuth]) {
            expect(
                new URL(buildAuthorizeUrl(cfg(hook), 'x', ['read:anything']), 'http://x').searchParams.has('scopes'),
            ).toBe(false);
        }
    });

    it('never injects email/profile into any factory provider scopes (Linear regression guard)', () => {
        for (const h of [useLinearOAuth, useAttioOAuth, useMicrosoftOAuth, useNotionOAuth, useGithubOAuth, useZoomOAuth]) {
            const c = cfg(h);
            const s = scopesOf(buildAuthorizeUrl(c, 'x'));
            if (s !== null) {
                const list = s.split(c.scopeDelimiter || ',');
                expect(list, `${c.provider} must not add email`).not.toContain('email');
                expect(list, `${c.provider} must not add profile`).not.toContain('profile');
            }
        }
    });

    it('org consent rides the same authorize URL as admin_consent=1, off by default (Microsoft)', () => {
        const c = cfg(useMicrosoftOAuth);
        const plain = new URL(buildAuthorizeUrl(c, 'x'), 'http://x');
        expect(plain.searchParams.has('admin_consent')).toBe(false);
        const org = new URL(buildAuthorizeUrl(c, 'x', undefined, { orgConsent: true }), 'http://x');
        expect(org.pathname).toBe('/api/auth/microsoft/authorize');
        expect(org.searchParams.get('admin_consent')).toBe('1');
        expect(org.searchParams.get('scopes')).toBe(plain.searchParams.get('scopes'));
    });

    it('caller scopes override defaults, joined verbatim (no mutation)', () => {
        const url = buildAuthorizeUrl({ provider: 'linear', defaultScopes: ['read'] }, 'x', ['read', 'write']);
        expect(scopesOf(url)).toBe('read,write');
    });
});
