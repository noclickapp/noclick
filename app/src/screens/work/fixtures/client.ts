// The client Work's fixtures, lab and tests run the real views with: NoClick's SDK over a fake /v1's `fetch`, so no
// call leaves the page. It holds no key.
import { DEFAULT_BASE_URL, NoClick } from 'noclick';
import { FIXTURE_BEARER } from '@/screens/console/fixtures/client';

export function workFixtureClient(fetch: typeof window.fetch): NoClick {
    return new NoClick({ apiKey: FIXTURE_BEARER, baseUrl: DEFAULT_BASE_URL, fetch, maxRetries: 2 });
}
