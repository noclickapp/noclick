// The links a refused coordinator call carries: a plan is priced per period, a
// one-time payment (funds for the balance) is priced once. A number's purchase
// page is recognised whichever tool answered with it.
import { describe, expect, it } from 'vitest';
import { isPhonePurchaseLink, refusalLinks } from '~/components/coordinator/cards/PurchaseCards';
import type { CoordinatorToolCall } from '~/lib/coordinatorToolCalls';

function refused(links: Array<Record<string, unknown>>): CoordinatorToolCall {
    return {
        id: 'c1', tool: 'generate_video', args: {}, running: false, startedAt: 0,
        result: { success: false, error: 'Video generation needs 9.6 credits and the account has 0.0.', kind: 'credits', purchase_links: links },
    };
}

describe('refusalLinks', () => {
    it('prices funds once and plans per period', () => {
        expect(refusalLinks(refused([
            { url: 'https://noclick.com/pay/1', label: '$10 of balance', price_usd: 10, billing_period: null },
            { url: 'https://noclick.com/pay/2', label: 'the Plus plan, billed monthly', price_usd: 25, billing_period: 'monthly' },
            { url: 'https://noclick.com/pay/3', label: 'the Pro plan, billed yearly', price_usd: 360, billing_period: 'yearly' },
        ]))).toEqual([
            { href: 'https://noclick.com/pay/1', label: '$10 of balance · $10' },
            { href: 'https://noclick.com/pay/2', label: 'Plus plan, billed monthly · $25/mo' },
            { href: 'https://noclick.com/pay/3', label: 'Pro plan, billed yearly · $360/yr' },
        ]);
    });

    it('offers nothing for a call that succeeded', () => {
        expect(refusalLinks({ ...refused([]), result: { success: true } })).toEqual([]);
    });
});

describe('isPhonePurchaseLink', () => {
    const answered = (tool: string, result: Record<string, unknown>): CoordinatorToolCall => ({ id: tool, tool, args: {}, running: false, startedAt: 0, result });

    it('is a purchase page from any tool, never a platform approval or a refusal', () => {
        expect(isPhonePurchaseLink(answered('quote', { success: true, status: 'pending', approval_url: 'https://noclick.com/credential/purchase/tok_1' }))).toBe(true);
        expect(isPhonePurchaseLink(answered('buy', { success: true, status: 'awaiting_approval', approval_url: 'https://noclick.com/approve/ap_1' }))).toBe(false);
        expect(isPhonePurchaseLink(answered('quote', { success: false, error: 'No', approval_url: 'https://noclick.com/credential/purchase/tok_1' }))).toBe(false);
    });
});
