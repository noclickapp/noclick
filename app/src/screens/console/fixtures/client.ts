// The client the lab and the console's tests hand it: NoClick's real SDK client over the fixtures' canned /v1
// (fixtureFetch.ts), so the real pages run and no call leaves the page. It holds no key.
import { DEFAULT_BASE_URL, NoClick, type ClientOptions } from 'noclick';
import { makeFixtureFetch, type FixtureFetchOptions } from './fixtureFetch';

/** The bearer the SDK sends with every call; the fixtures never read it. Not a secret. */
export const FIXTURE_BEARER = 'a-fixture-holds-no-key';

export function fixtureClient(fixtures: FixtureFetchOptions, options: Omit<ClientOptions, 'apiKey' | 'baseUrl' | 'fetch'> = {}): NoClick {
    return new NoClick({ maxRetries: 2, ...options, apiKey: FIXTURE_BEARER, baseUrl: DEFAULT_BASE_URL, fetch: makeFixtureFetch(fixtures) });
}
