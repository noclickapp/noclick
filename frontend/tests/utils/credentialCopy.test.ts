// The connect dialog's words come from the schema alone; these pin the rules that make a developer docstring read as
// something a person can act on (the whole catalog is pinned by credentialCopyAudit.test.ts).
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { asNamed, copyMethodOf, fieldHelp, fieldLabel, methodCopy, sentenceCase, stepsFromDescription, withArticle, withoutAppName } from '~/utils/credentialCopy';
import { loadAllNodeSchemas } from '~/utils/nodeSchemas';

// The subjects read node schemas, which load per type (some at collection time).
await loadAllNodeSchemas();

const methodsOf = (nodeType: string) => credentialRequirements(nodeType).map((r) => copyMethodOf(methodFromRequirement(r)));

describe('credential copy', () => {
    it("names Notion's two ways in plainly, sign-in first, with no URL or class description", () => {
        const [oauth, token] = methodsOf('automation-notion');
        expect(methodCopy(oauth, 'Notion')).toEqual({
            name: 'Sign in with Notion',
            line: 'Opens Notion to sign in. NoClick never sees your password.',
            howTo: null,
            source: null,
        });
        expect(methodCopy(token, 'Notion')).toEqual({
            name: 'Internal integration token',
            line: 'Paste an internal integration token from Notion.',
            howTo: 'Create an internal integration. Then share the desired pages/databases with your integration.',
            source: { href: 'https://www.notion.so/my-integrations', host: 'notion.so' },
        });
    });

    it("signs a Google app in with Google, the provider, not the app", () => {
        const [gmail] = methodsOf('automation-gmail');
        expect(methodCopy(gmail, 'Gmail', 'Google').name).toBe('Sign in with Google');
    });

    it("reads Bluesky's app password from the field's own link", () => {
        const [method] = methodsOf('automation-bluesky');
        const copy = methodCopy(method, 'Bluesky');
        expect(copy.name).toBe('App password');
        expect(copy.source?.host).toBe('bsky.app');
        // The schema's "BlueSky" reads as the catalog names the app.
        expect(copy.howTo).toContain('from Bluesky settings');
        expect(method.fields?.map(fieldLabel)).toEqual(['Handle or email', 'App password']);
    });

    it('spells out an acronym the label leans on', () => {
        const [, pat] = methodsOf('automation-airtable');
        expect(methodCopy(pat, 'Airtable').line).toBe('Paste a personal access token from Airtable.');
    });

    it("doesn't say where a key comes from when no provider issues it", () => {
        const [apiKey] = methodsOf('automation-http-request');
        expect(methodCopy(apiKey, 'HTTP Request').line).toBe('Paste an API key.');
        expect(asNamed('the "acme" in https://acme.fellow.app, from Fellow settings', 'Fellow')).toBe('the "acme" in https://acme.fellow.app, from Fellow settings');
    });

    it('never asks for a const discriminator', () => {
        const methods = methodsOf('automation-cloudflare');
        for (const m of methods) expect(m.fields?.map((f) => f.label)).not.toContain('Credential Type');
    });

    it('keeps the steps of a description and drops what the link and the class say', () => {
        expect(
            stepsFromDescription('API Key credential for Mailchimp.\n\nGet your API key at: https://mailchimp.com/keys\nNavigate to: Profile -> Extras -> API Keys')
        ).toBe('Navigate to: Profile → Extras → API Keys.');
        expect(stepsFromDescription('Bearer token authentication')).toBeNull();
        // A wrapped docstring line continues its sentence.
        expect(stepsFromDescription('Create an App Password from settings\nwithout exposing your password.')).toBe(
            'Create an App Password from settings without exposing your password.'
        );
    });

    it('drops help that only restates the label, keeping what its brackets add', () => {
        expect(fieldHelp({ label: 'API Key', description: 'Your Apollo.io API Key' }, 'Apollo')).toBeNull();
        expect(fieldHelp({ label: 'Internal Integration Token', description: "Your Notion Internal Integration Token (starts with 'ntn_' or 'secret_')" }, 'Notion')).toBe(
            'Starts with ntn_ or secret_.'
        );
        expect(fieldHelp({ label: 'Access Token', description: 'Attio access token from Settings. Passed as a Bearer token.' }, 'Attio')).toBe(
            'Attio access token from Settings.'
        );
    });

    it('keeps an example URL and drops a pointer to one', () => {
        expect(fieldHelp({ label: 'Cluster URL', description: 'Your endpoint, e.g. https://xyz.cloud.qdrant.io' }, 'Qdrant')).toBe(
            'Your endpoint, e.g. https://xyz.cloud.qdrant.io'
        );
        expect(fieldHelp({ label: 'API Key', description: 'Your Extend key from Dashboard (https://dashboard.extend.ai/developers)' }, 'Extend')).toBe(
            'Your Extend key from Dashboard'
        );
    });

    it('sets labels in sentence case, keeping brands and acronyms', () => {
        expect(sentenceCase('Handle or Email')).toBe('Handle or email');
        expect(sentenceCase('Webhook Primary Signing Key')).toBe('Webhook primary signing key');
        expect(sentenceCase('GitHub API Key')).toBe('GitHub API key');
        expect(withoutAppName('Google Sheets OAuth', 'Google Sheets')).toBe('OAuth');
        expect(withArticle('API key')).toBe('an API key');
        expect(withArticle('REST URL')).toBe('a REST URL');
        expect(sentenceCase('Organization Slug')).toBe('Organization slug');
        expect(sentenceCase('Account Identifier')).toBe('Account identifier');
    });

    it('never recases an app inside a URI scheme', () => {
        expect(asNamed('use mongodb://localhost:27017/ or mongodb+srv://x', 'MongoDB')).toBe('use mongodb://localhost:27017/ or mongodb+srv://x');
        expect(asNamed('Go to mongodb Atlas', 'MongoDB')).toBe('Go to MongoDB Atlas');
    });

    it('names a class by its title without the Credential suffix', () => {
        expect(methodsOf('automation-postgres').map((m) => m.label)).not.toContain('Postgress');
    });

    it('keeps how a value travels out of the help', () => {
        expect(fieldHelp({ label: 'Key ID', description: 'Key ID (used as the HTTP Basic username)' }, 'ClickHouse')).toBeNull();
        expect(fieldHelp({ label: 'Key Secret', description: 'Shown only once at creation; used as the HTTP Basic password.' }, 'ClickHouse')).toBe('Shown only once at creation.');
        expect(fieldHelp({ label: 'Bearer Token', description: 'A Fathom bearer token to send as Authorization: Bearer <token>.' }, 'Fathom')).toBeNull();
        expect(fieldHelp({ label: 'API Token', description: 'Cloudflare API Token (Bearer token)' }, 'Cloudflare')).toBeNull();
    });

    it("keeps a local URL a step types, and takes the steps' link as the source when the schema names none", () => {
        const [, script] = methodsOf('automation-reddit');
        const copy = methodCopy(script, 'Reddit');
        expect(copy.howTo).toContain('Set redirect uri to http://localhost:8080');
        expect(copy.source?.host).toBe('reddit.com');
    });

    it('names a value by the brand that issues it, and a tab by its secret', () => {
        const feedly = methodsOf('automation-rss').find((m) => /feedly/i.test(m.label));
        expect(feedly && methodCopy(feedly, 'RSS').line).toBe('Paste a developer access token from Feedly.');
        const [weaviate] = methodsOf('automation-weaviate');
        expect(methodCopy(weaviate, 'Weaviate').name).toBe('API key');
        // The line names the secret the tab does, then what is required beside it.
        expect(methodCopy(weaviate, 'Weaviate').line).toBe('Paste an API key from Weaviate and enter the cluster URL.');
        const [chroma] = methodsOf('automation-chroma');
        expect(methodCopy(chroma, 'Chroma')).toMatchObject({ name: 'API token', line: 'Paste an API token from Chroma and enter the tenant and database.' });
    });
});
