// What the lab answers that the platform client it hands Work doesn't carry: a space joined in another account is read
// through a session's own client, which calls NoClick's API with the browser's fetch. While a scene is mounted, those
// calls are answered from its fixtures, so the lab reaches no network.
import { DEFAULT_BASE_URL } from 'noclick';

/** Answers the browser's calls to NoClick's API from `api` until the returned function puts its fetch back. */
export function answerSessions(api: typeof window.fetch): () => void {
    const real = window.fetch;
    const platform = new URL(DEFAULT_BASE_URL).origin;
    window.fetch = (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, window.location.href);
        return url.origin === platform ? api(input, init) : real(input, init);
    };
    return () => {
        window.fetch = real;
    };
}
