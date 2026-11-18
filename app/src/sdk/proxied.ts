// The browser's SDK client: it calls this app's own server at /api, which sends each call on to NoClick's API with the
// app's key (src/server/proxy.server.ts). The key never reaches the browser.
import { NoClick, type ClientOptions } from 'noclick';

export const PROXY_PATH = '/api';

/**
 * The bearer the browser's client sends. The SDK sends one with every call; this app's server never passes the
 * browser's Authorization header on (it sends its own key instead), so this only tells a reader where the key is.
 * Not a secret.
 */
export const BROWSER_BEARER = 'held-by-this-app-server';

/** A client for the app served at `origin`: `${origin}/api` stands in for NoClick's API. */
export function proxiedClient(origin: string, options: Omit<ClientOptions, 'apiKey' | 'baseUrl'> = {}): NoClick {
    return new NoClick({ ...options, apiKey: BROWSER_BEARER, baseUrl: new URL(origin).origin + PROXY_PATH });
}
