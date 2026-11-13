// @vitest-environment jsdom
// @vitest-environment-options {"url": "https://noclick.com/dashboard"}
// The browser client is made by supabase-client.ts and held in supabaseClientHolder.ts, which REST
// auth and the socket read. The holder imports nothing at runtime, so those readers never bring
// @supabase/ssr and supabase-js onto a page that doesn't make the client (every marketing page).
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/edition', () => ({ isLocalEdition: () => false }));

const holder = await import('~/lib/supabaseClientHolder');
const { getSupabaseBrowserClient } = await import('~/lib/supabase-client');

const ENV = { SUPABASE_URL: 'https://abcdefghijklmnopqrst.supabase.co', SUPABASE_ANON_KEY: 'anon-key' };

describe('the held browser client', () => {
    it('is the one supabase-client made, and is made once', async () => {
        expect(holder.getExistingBrowserClient()).toBeNull();
        expect(holder.hasSupabaseBrowserClient()).toBe(false);

        const client = getSupabaseBrowserClient(ENV);
        await client.auth.stopAutoRefresh();

        expect(holder.getExistingBrowserClient()).toBe(client);
        expect(holder.hasSupabaseBrowserClient()).toBe(true);
        expect(getSupabaseBrowserClient(ENV)).toBe(client);

        holder.clearSupabaseBrowserClient();
        expect(holder.getExistingBrowserClient()).toBeNull();
    });

    it('imports nothing at runtime', () => {
        const source = readFileSync(resolve(__dirname, '../../app/lib/supabaseClientHolder.ts'), 'utf8');
        const imports = source.split('\n').filter((line) => /^\s*(import|export)\b.*\bfrom\s+['"]/.test(line));
        expect(imports.every((line) => /^\s*import\s+type\b/.test(line))).toBe(true);
        expect(source).not.toMatch(/\bimport\(/);
    });
});
