/**
 * True only for origins the app is legitimately served from. OAuth callbacks
 * must never bounce authorization codes to an origin taken from untrusted
 * state without this exact-origin check.
 */
export function isTrustedAppOrigin(origin: string): boolean {
    let parsed: URL;
    try {
        parsed = new URL(origin);
    } catch {
        return false;
    }

    const isLoopback =
        parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1';
    if (parsed.protocol !== 'https:' && !isLoopback) return false;
    if (isLoopback) return true;

    const configured = [
        process.env.VITE_PUBLIC_URL,
        process.env.FRONTEND_URL,
    ].filter(Boolean) as string[];
    return configured.some((value) => {
        try {
            return new URL(value).origin === parsed.origin;
        } catch {
            return false;
        }
    });
}
