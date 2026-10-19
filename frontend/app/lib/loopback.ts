// Loopback hostnames: localhost, 127.0.0.1 and any *.localhost name (RFC 6761
// reserves .localhost for loopback). Local dev serves each worktree from its
// own wt<port>.localhost host (lib/devHost.ts), so every "is this local?"
// check must accept the subdomains too.
export function isLoopbackHostname(hostname: string | null | undefined): boolean {
    if (!hostname) return false;
    return hostname === 'localhost' || hostname === '127.0.0.1' || hostname.endsWith('.localhost');
}
