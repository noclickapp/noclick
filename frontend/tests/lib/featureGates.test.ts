import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/internalUsers', () => ({
    isInternalEmail: (email: string) => email === 'staff@example.com',
}));

import { FEATURE_ROLLOUT, allowAccounts, featureGateState, isFeatureEnabled } from '~/lib/featureGates';

describe('feature gates', () => {
    beforeEach(() => {
        featureGateState.email = '';
    });

    it('rolls an internal feature out to the hosted team only', () => {
        expect(FEATURE_ROLLOUT.phone_numbers).toBe('internal');
        expect(isFeatureEnabled('phone_numbers', 'staff@example.com')).toBe(true);
        expect(isFeatureEnabled('phone_numbers', 'customer@example.com')).toBe(false);
        expect(isFeatureEnabled('phone_numbers', '')).toBe(false);
        expect(isFeatureEnabled('phone_numbers', null)).toBe(false);
    });

    it('lets a named account pilot an internal feature without joining the staff list', () => {
        expect(isFeatureEnabled('phone_numbers', 'pilot@example.com')).toBe(false);
        allowAccounts('phone_numbers', [' Pilot@Example.com ']);
        expect(isFeatureEnabled('phone_numbers', 'pilot@example.com')).toBe(true);
        expect(isFeatureEnabled('phone_numbers', 'other@example.com')).toBe(false);
    });

    it('opens an everyone feature to every account, signed in or not', () => {
        expect(FEATURE_ROLLOUT.phone_channel).toBe('everyone');
        expect(isFeatureEnabled('phone_channel', 'customer@example.com')).toBe(true);
        expect(isFeatureEnabled('phone_channel', null)).toBe(true);
    });

    it('mirrors the backend rollout table one feature at a time', () => {
        // The backend enforces; this table only hides surfaces. A feature must
        // exist on both sides under the same name (backend/utils/feature_gates.py).
        expect(Object.keys(FEATURE_ROLLOUT)).toEqual(['phone_channel', 'coordinator', 'phone_numbers']);
    });
});
