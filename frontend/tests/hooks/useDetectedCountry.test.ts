// @vitest-environment jsdom
// Which country a phone input starts on: the IP country from /api/public-session
// wins, then the browser locale's region, and nothing unsupported gets through.
import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const session = { country: null as string | null };
vi.mock('~/hooks/usePublicSession', () => ({ usePublicSession: () => session }));

import { useDetectedCountry } from '~/hooks/useDetectedCountry';

function withLanguages(languages: string[]) {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(languages);
}

afterEach(() => {
    vi.restoreAllMocks();
    session.country = null;
});

describe('useDetectedCountry', () => {
    it('prefers the IP country', () => {
        session.country = 'be';
        withLanguages(['en-US']);
        expect(renderHook(() => useDetectedCountry()).result.current).toBe('BE');
    });

    it('falls back to the first locale that names a region', () => {
        withLanguages(['de', 'de-DE', 'en-US']);
        expect(renderHook(() => useDetectedCountry()).result.current).toBe('DE');
    });

    it('starts international when nothing usable is known', () => {
        session.country = 'XX';
        withLanguages(['en']);
        expect(renderHook(() => useDetectedCountry()).result.current).toBeUndefined();
    });
});
