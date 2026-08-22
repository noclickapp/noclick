import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const APP = join(process.cwd(), 'app');

const hooks = [
    'hooks/oauth/useShopifyOAuth.ts',
    'hooks/oauth/useQuickBooksOAuth.ts',
    'hooks/oauth/useSlackOAuth.ts',
];

const routes = [
    'routes/api/auth/shopify.authorize.tsx',
    'routes/api/auth/intuit.authorize.tsx',
    'routes/api/auth/slack.authorize.tsx',
];

describe('custom OAuth secret transport', () => {
    it.each(hooks)(
        '%s submits setup values through the POST popup helper',
        (file) => {
            const source = readFileSync(join(APP, file), 'utf8');
            expect(source).toContain('openOAuthPostPopup');
            expect(source).not.toMatch(/\/authorize\?\$\{/);
            expect(source).not.toMatch(/params\.set\([^\n]*(?:secret|Secret)/);
        }
    );

    it.each(routes)(
        '%s never reads a client secret from search params',
        (file) => {
            const source = readFileSync(join(APP, file), 'utf8');
            expect(source).toContain('export async function action');
            expect(source).toContain('oauthPostFormData(request)');
            expect(source).not.toMatch(
                /searchParams\.get\(['"](?:client_secret|customClientSecret)['"]\)/
            );
        }
    );
});
