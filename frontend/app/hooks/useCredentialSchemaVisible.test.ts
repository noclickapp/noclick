// @vitest-environment jsdom
// A sign-in held back for marketplace review shows on our own dev servers, never on a self-hosted instance (whose
// `make local` is a dev server too).
import { renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const edition = vi.hoisted(() => ({ local: false }));
vi.mock('~/lib/edition', () => ({ isLocalEdition: () => edition.local }));
vi.mock('posthog-js/react', () => ({ useActiveFeatureFlags: () => [] }));

import { useCredentialSchemaVisible } from './useCredentialSchemaVisible';

const META = { 'x-credential-hidden': true, 'x-credential-preview-flag': 'meta-oauth-preview' };

afterEach(() => {
    edition.local = false;
});

describe('useCredentialSchemaVisible', () => {
    it('shows a previewed sign-in on a dev server', () => {
        expect(import.meta.env.DEV).toBe(true);
        const { result } = renderHook(() => useCredentialSchemaVisible());
        expect(result.current(META)).toBe(true);
    });

    it('keeps it hidden on a self-hosted instance', () => {
        edition.local = true;
        const { result } = renderHook(() => useCredentialSchemaVisible());
        expect(result.current(META)).toBe(false);
        expect(result.current({})).toBe(true);
    });
});
