// The OAuth setup page is what a self-hoster sees the first time they click
// Connect on any of the 76 OAuth integrations, so its three facts have to be
// right: the correct callback URL for the host they're on, the env vars this
// instance actually reads, and where to create the app.

import { describe, it, expect } from 'vitest';
import { callbackUrlFor, oauthNotConfiguredResponse } from '~/lib/oauthSetupPage.server';
import { OAUTH_PROVIDER_SETUP, providerSetup } from '~/lib/oauthProviderSetup';

const req = (url: string, headers: Record<string, string> = {}) => new Request(url, { headers });

describe('callbackUrlFor', () => {
    it('derives from the request host, not a pinned value', () => {
        expect(callbackUrlFor(req('http://localhost:5111/api/auth/slack/authorize'), 'slack')).toBe(
            'http://localhost:5111/api/auth/slack/callback'
        );
        expect(callbackUrlFor(req('https://noclick.example.com/api/auth/slack/authorize'), 'slack')).toBe(
            'https://noclick.example.com/api/auth/slack/callback'
        );
    });

    it('honors proxy headers, since TLS usually terminates upstream', () => {
        const r = req('http://internal:3000/api/auth/github/authorize', {
            'X-Forwarded-Proto': 'https',
            'X-Forwarded-Host': 'flows.example.com',
        });
        expect(callbackUrlFor(r, 'github')).toBe('https://flows.example.com/api/auth/github/callback');
    });
});

describe('oauthNotConfiguredResponse', () => {
    const render = async (provider: string, missing: string[]) => {
        const res = oauthNotConfiguredResponse({
            request: req(`http://localhost:5111/api/auth/${provider}/authorize`),
            provider,
            missing,
        });
        return { res, html: await res.text() };
    };

    it('is a readable page, not an error status', async () => {
        const { res, html } = await render('slack', ['SLACK_CLIENT_ID']);
        // 5xx renders as a browser error page in some popup contexts.
        expect(res.status).toBe(200);
        expect(res.headers.get('Content-Type')).toContain('text/html');
        expect(html).toContain("Slack isn't connected yet");
    });

    it('shows the callback URL to register and the env vars that are missing', async () => {
        const { html } = await render('slack', ['SLACK_CLIENT_ID', 'SLACK_REDIRECT_URI']);
        expect(html).toContain('http://localhost:5111/api/auth/slack/callback');
        expect(html).toContain('SLACK_CLIENT_ID=');
        expect(html).toContain('SLACK_REDIRECT_URI=');
    });

    it('names BOTH env files, including the secret the backend needs', async () => {
        // The original instructions omitted CLIENT_SECRET and sent everything to
        // backend/.env, which leaves the flow broken in two different ways.
        const { html } = await render('linear', ['LINEAR_CLIENT_ID']);
        expect(html).toContain('frontend/.env');
        expect(html).toContain('backend/.env');
        expect(html).toContain('LINEAR_CLIENT_SECRET=');
        // client id is required by both processes
        expect(html.match(/LINEAR_CLIENT_ID=/g)?.length).toBe(2);
    });

    it('prefills the redirect URI with the URL it just told you to register', async () => {
        const { html } = await render('linear', []);
        expect(html).toContain('LINEAR_REDIRECT_URI=http://localhost:5111/api/auth/linear/callback');
    });

    it('omits the backend block for PKCE providers that need no secret', async () => {
        const { html } = await render('parallel', []);
        expect(html).not.toContain('backend/.env');
        expect(html).not.toContain('CLIENT_SECRET');
    });

    it('links the provider console when one is known', async () => {
        const { html } = await render('slack', ['SLACK_CLIENT_ID']);
        expect(html).toContain('https://api.slack.com/apps');
    });

    it('degrades to generic wording for an unknown provider', async () => {
        const { html } = await render('nonesuch', ['NONESUCH_CLIENT_ID']);
        expect(html).toContain('Nonesuch');
        expect(html).not.toContain('href="https://');
    });

    it('escapes provider-derived text rather than interpolating it raw', async () => {
        const { html } = await render('a"><script>x</script>', ['X']);
        expect(html).not.toContain('<script>x</script>');
    });
});

describe('provider metadata', () => {
    it('covers the providers a self-hoster reaches for first', () => {
        for (const p of ['google', 'slack', 'github', 'notion', 'linear', 'discord']) {
            expect(OAUTH_PROVIDER_SETUP[p]?.consoleUrl, `${p} needs a console link`).toBeTruthy();
        }
    });

    it('every console URL is absolute https', () => {
        for (const [p, e] of Object.entries(OAUTH_PROVIDER_SETUP)) {
            if (e.consoleUrl) expect(e.consoleUrl, p).toMatch(/^https:\/\//);
        }
    });

    it('falls back to a humanized label for unknown providers', () => {
        expect(providerSetup('facebook_pages').label).toBe('Facebook Pages');
        expect(providerSetup('some_new_thing').label).toBe('Some New Thing');
    });
});
