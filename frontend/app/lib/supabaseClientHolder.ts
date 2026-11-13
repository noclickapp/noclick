// The page's one Supabase browser client, held apart from the code that makes it.
//
// Anything that only needs the client once it exists (REST auth headers, the socket's auth
// callback) reads it here, so importing them never pulls @supabase/ssr and supabase-js (about
// 64 KB gzipped) into a page: a marketing page never makes the client and never loads them.
// supabase-client.ts makes the client and holds it here. Keep this module free of runtime imports.

import type { SupabaseClient } from '@supabase/supabase-js';

let heldClient: SupabaseClient | null = null;
let heldUrl: string | null = null;

/** The held client when it was made for `supabaseUrl`, else null. */
export function heldBrowserClient(supabaseUrl: string): SupabaseClient | null {
    return heldClient && heldUrl === supabaseUrl ? heldClient : null;
}

export function holdBrowserClient(client: SupabaseClient, supabaseUrl: string): void {
    heldClient = client;
    heldUrl = supabaseUrl;
}

/**
 * The browser client if one has been made, else null. For non-React modules (socket auth
 * callbacks, REST headers) that only use a session that already exists.
 */
export function getExistingBrowserClient(): SupabaseClient | null {
    return heldClient;
}

/** Whether a browser client has been made. */
export function hasSupabaseBrowserClient(): boolean {
    return heldClient !== null;
}

/** Forgets the client (tests and explicit cleanup only). */
export function clearSupabaseBrowserClient(): void {
    heldClient = null;
    heldUrl = null;
}
