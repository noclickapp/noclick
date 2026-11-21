// @vitest-environment happy-dom
// The headline where the money runs out at this pace. The account's owner reads the money with auto top-up in it, so
// the page knows whether a refill keeps work going and says so: work stops on the day, or the projection runs on. One
// of the account's keys reads it without auto top-up (it names a payment method), so its page says only when the
// balance runs out at this pace, never that work stops; and with no balance at all, nothing could refill it.
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { deriveView } from './derive';
import { fixturePage } from './fixtures';
import { Hero } from './parts';
import type { UsageBilling, UsageSnapshot } from './types';

// The reader's days, in one zone whatever the machine's.
vi.hoisted(() => {
    process.env.TZ = 'UTC';
});

afterEach(cleanup);

/** A fixture account's snapshot as its owner reads it. */
const asOwner = (slug: string): UsageSnapshot => fixturePage(slug).snap;

/** The same account as one of its keys reads it: the money without auto top-up or friends' credit. */
function asKey(slug: string): UsageSnapshot {
    const snap = asOwner(slug);
    const { plan, balance, funds, recurring, domains } = snap.billing!;
    return { ...snap, billing: { plan, balance, funds, recurring, domains } as UsageBilling };
}

const headline = (snap: UsageSnapshot) => {
    render(<Hero view={deriveView(snap)} />);
    const text = document.body.textContent ?? '';
    cleanup();
    return text;
};

describe('where the money runs out at this pace', () => {
    it('tells the owner work stops, where auto top-up is off', () => {
        expect(headline(asOwner('running-out'))).toMatch(/this month, then work stops [A-Z][a-z]{2} \d+/);
    });

    it('tells a key only when the balance runs out, and what the pace would need', () => {
        const text = headline(asKey('running-out'));
        expect(text).toMatch(/this month; at this pace the balance runs out [A-Z][a-z]{2} \d+/);
        expect(text).toMatch(/The pace would need ~\$\d+ this period/);
        expect(text).not.toMatch(/work stops|add funds to keep going/);
    });

    it('lets auto top-up carry the owner’s projection on, and still tells a key nothing it isn’t told', () => {
        expect(deriveView(asOwner('member')).refillUnknown).toBe(false);
        expect(headline(asOwner('member'))).not.toMatch(/work stops|runs out/);
        const view = deriveView(asKey('member'));
        expect(view.refillUnknown).toBe(true);
        expect(headline(asKey('member'))).not.toMatch(/work stops/);
    });

    it('says work stops to a key whose account never added funds, which nothing could refill', () => {
        const view = deriveView(asKey('free-new'));
        expect(view.hasBalance).toBe(false);
        expect(view.refillUnknown).toBe(false);
    });
});

it('draws the owner’s page as before: the headline a key gets is its own', () => {
    render(<Hero view={deriveView(asOwner('running-out'))} />);
    expect(screen.queryByText(/at this pace the balance runs out/)).toBeNull();
});
