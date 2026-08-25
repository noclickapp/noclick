// Every public endpoint of this installation, resolved in one place.
//
// The hosted service has defaults to fall back on; a self-hosted installation
// has none, and a fallback here would silently point an operator's traffic at
// someone else's servers. So each resolver either derives the answer from this
// installation's own configuration or fails loudly.
//
// One derivation does exist, and it is the reason a single-origin install needs
// no configuration at all: in the browser, an unset VITE_API_URL means the
// origin the page was served from. The container image and every one-click host
// put the app and the backend behind one hostname, so "here" is the right
// answer rather than "not configured". On the server there is no "here", which
// is why the same unset value still throws there.
//
// `tests/lib/hostedDefaults.test.ts` pins the behaviour; the repo-wide scan in
// `backend/tests/test_no_hosted_endpoints.py` keeps hostnames out of every
// other module.

const trimSlashes = (url: string) => String(url).replace(/\/+$/, '');

const sameOrigin = (): string | undefined =>
    typeof window !== 'undefined' ? window.location.origin : undefined;

function notConfigured(envVar: string, purpose: string): never {
    throw new Error(
        `${envVar} is not set. Configure the public ${purpose} URL for this installation.`,
    );
}

/** Base URL of the backend API. Works in the browser and in the app server —
 *  Vite injects import.meta.env on both sides. */
export function apiBaseUrl(): string {
    const configured =
        import.meta.env.VITE_API_URL ||
        (typeof process !== 'undefined' ? process.env?.VITE_API_URL : undefined) ||
        sameOrigin();
    if (!configured) notConfigured('VITE_API_URL', 'API');
    return trimSlashes(configured);
}

/** Base URL of the event relay (user events + workflow presence/cursors). The
 *  backend serves the relay protocol in-process at /relay. */
export function relayBaseUrl(): string {
    const override =
        typeof window !== 'undefined'
            ? (window as unknown as { __RELAY_URL__?: string }).__RELAY_URL__
            : undefined;
    // process.env as well as import.meta.env, exactly as apiBaseUrl does: the
    // single-origin image builds the bundle with no URL baked in, so on the app
    // server import.meta.env is empty and there is no origin to fall back to.
    // Reading only the build-time value made the server throw as its modules
    // loaded, and the container exited before it listened.
    const configured =
        override ||
        import.meta.env.VITE_RELAY_URL ||
        (typeof process !== 'undefined' ? process.env?.VITE_RELAY_URL : undefined);
    if (configured) return trimSlashes(configured);
    const apiUrl =
        import.meta.env.VITE_API_URL ||
        (typeof process !== 'undefined' ? process.env?.VITE_API_URL : undefined) ||
        sameOrigin();
    if (!apiUrl) notConfigured('VITE_RELAY_URL', 'event relay');
    return `${trimSlashes(apiUrl).replace(/^http/, 'ws')}/relay`;
}

/** Backend hosting the email webhook routes. Server-side only (a route module),
 *  so it reads process.env rather than the client-visible import.meta.env. */
export function emailWorkerUrl(): string {
    const configured = process.env.EMAIL_WORKER_URL || process.env.VITE_API_URL;
    if (!configured) notConfigured('EMAIL_WORKER_URL', 'email worker');
    return trimSlashes(configured);
}

/** The MCP endpoint external clients (Claude, ChatGPT) connect to. Shown to
 *  users verbatim, so a hardcoded host would hand this installation's users
 *  somebody else's server. */
export function mcpServerUrl(): string {
    return `${apiBaseUrl()}/mcp`;
}
