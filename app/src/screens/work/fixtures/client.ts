// The client Work's, Connections', Usage's and Settings' fixtures, labs and tests run the real views with: NoClick's
// SDK over a fake /v1's `fetch`, so no call leaves the page. It holds no key.
import { DEFAULT_BASE_URL, NoClick } from 'noclick';
import { FIXTURE_BEARER } from '@/screens/console/fixtures/client';

/** `maxRetries: 0` answers a refusal at once, as a scene showing one needs. */
export function workFixtureClient(fetch: typeof window.fetch, { maxRetries = 2 }: { maxRetries?: number } = {}): NoClick {
    return new NoClick({ apiKey: FIXTURE_BEARER, baseUrl: DEFAULT_BASE_URL, fetch, maxRetries });
}
