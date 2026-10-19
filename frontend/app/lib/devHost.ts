// Local dev gives every worktree a host of its own. Browsers scope cookies by
// host, never by port, so dev servers on localhost:5173, :5174, … shared one
// jar: each worktree's ~5 KB Supabase session rode every request to every dev
// server and the backend, and past three sessions the Cookie header outgrew
// Node's 16 KB limit (HTTP 431 on every local page). A page load on
// localhost:<port> is moved to wt<port>.localhost:<port> (loopback by RFC 6761),
// whose jar holds that worktree's session alone.
//
// Dependency-free: vite.config.ts loads this before the app's aliases exist.
import type { Plugin } from 'vite';

/** The cookie a local worktree's Supabase session lives in (see supabase-client). */
export function worktreeAuthCookieName(port: string): string {
    return `sb-noclick-wt${port}-auth-token`;
}

export function worktreeHost(port: string): string {
    return `wt${port}.localhost`;
}

type Headers = Record<string, string | string[] | undefined>;

export interface HostRedirect {
    location: string;
    /** Set-Cookie values expiring sessions the shared jar should no longer hold. */
    expire: string[];
}

const SHARED_HOST = /^(localhost|127\.0\.0\.1):(\d+)$/;
// The session Supabase wrote before cookies were named per worktree.
const PRE_WORKTREE_SESSION = /^sb-127-auth-token/;
// 127.0.0.1 is also the local Supabase API's host, and its gateway answers
// "Bad request" to a Cookie header over 8 KB: two sessions in that jar (any
// worktree's) break sign-in for every worktree, so none may stay there.
const SUPABASE_SESSION = /^sb-.*-auth-token/;

function header(headers: Headers, name: string): string | undefined {
    const value = headers[name];
    return Array.isArray(value) ? value[0] : value;
}

/** A page load on the shared localhost jar, moved to this worktree's own host.
 *  Anything else (fetches, HMR, webhooks, CLI tools) is left alone. */
export function worktreeRedirect(req: { method?: string; url?: string; headers: Headers }): HostRedirect | null {
    if (req.method !== 'GET' && req.method !== 'HEAD') return null;
    if (header(req.headers, 'sec-fetch-mode') !== 'navigate') return null;
    const shared = SHARED_HOST.exec(header(req.headers, 'host') ?? '');
    if (!shared) return null;
    const [, hostname, port] = shared;
    const ownSession = worktreeAuthCookieName(port);
    const stale = (name: string) =>
        hostname === '127.0.0.1' ? SUPABASE_SESSION.test(name) : name.startsWith(ownSession) || PRE_WORKTREE_SESSION.test(name);
    const expire = (header(req.headers, 'cookie') ?? '')
        .split(';')
        .map((pair) => pair.split('=')[0].trim())
        .filter(stale)
        .map((name) => `${name}=; Max-Age=0; Path=/`);
    return { location: `http://${worktreeHost(port)}:${port}${req.url ?? '/'}`, expire };
}

// The first visit still carries the old shared jar, which can be over Node's
// 16 KB default; accept it so the redirect that sheds it can be served.
const MAX_HEADER_BYTES = 64 * 1024;

export function worktreeHostPlugin(): Plugin {
    return {
        name: 'noclick-worktree-host',
        apply: 'serve',
        configureServer(server) {
            // Read per connection, so setting it before the first request applies to all.
            if (server.httpServer) (server.httpServer as { maxHeaderSize?: number }).maxHeaderSize = MAX_HEADER_BYTES;
            server.middlewares.use((req, res, next) => {
                const redirect = worktreeRedirect(req);
                if (!redirect) return next();
                res.statusCode = 307;
                res.setHeader('Location', redirect.location);
                if (redirect.expire.length) res.setHeader('Set-Cookie', redirect.expire);
                res.end();
            });
        },
    };
}
