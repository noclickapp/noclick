// Exercise the actual purchase route in the running app with a fake transport.
// This verifies the review and completion screens without buying a number or
// touching an account; preview() leaves the same route mounted for visual checks.
import { createRoot } from 'react-dom/client';
import { createRoutesStub } from 'react-router';
import { flushSync } from 'react-dom';
import PhonePurchasePage from '~/routes/credential.purchase.$token';
import { nc } from '~/lib/nc';

const quote = { id: 'review-quote', phone_number: '+15674833618', monthly_credits: 15, expires_at: '2099-01-01T00:00:00Z' };
let cleanup: (() => void) | undefined;

function mount() {
    cleanup?.();
    const host = document.createElement('div');
    host.id = 'phone-purchase-test';
    Object.assign(host.style, { position: 'fixed', inset: '0', zIndex: '9999', overflow: 'auto' });
    document.body.appendChild(host);
    const App = createRoutesStub([{
        path: '/', Component: PhonePurchasePage,
        loader: () => ({ purchase: { status: 'pending', purpose: 'A dedicated line for the studio’s receptionist agent.', quote }, csrfToken: 'test-csrf', email: 'owner@example.com', returnTo: '/b/review-link' }),
    }]);
    const root = createRoot(host);
    flushSync(() => root.render(<App initialEntries={['/']} />));
    cleanup = () => { root.unmount(); host.remove(); cleanup = undefined; };
    return host;
}

export async function preview() {
    mount();
    await nc.wait.forElement('#phone-purchase-test [data-testid="phone-purchase-confirmation"]');
    return { mounted: true };
}

export function closePreview() { cleanup?.(); }

export default async function () {
    const host = mount();
    const original = window.fetch;
    const calls: string[] = [];
    window.fetch = async (input, init) => {
        if (String(input) !== window.location.href || !(init?.body instanceof FormData)) return original(input, init);
        calls.push(String(init.body.get('operation')));
        nc.assert.equal(init.body.get('payload'), JSON.stringify({ quote_id: 'review-quote' }), 'Only the server quote is confirmed');
        return Response.json({ status: 'fulfilled', credential_id: 'test-credential', phone_number: quote.phone_number });
    };
    try {
        await nc.wait.until(() => !!host.querySelector('[data-testid="phone-purchase-confirmation"]'));
        nc.assert.includes(host.textContent || '', 'Renews monthly', 'Recurring price is visible');
        nc.assert.equal(calls.length, 0, 'Opening the page never purchases');
        const button = Array.from(host.querySelectorAll('button')).find(b => b.textContent?.includes('Confirm purchase'))!;
        button.click(); button.click();
        await nc.wait.until(() => host.textContent?.includes('Your number is ready') === true);
        nc.assert.equal(calls.length, 1, 'Double click confirms once');
        nc.assert.equal(host.querySelector('a[href="/b/review-link"]')?.getAttribute('href'), '/b/review-link', 'Returns to the original builder');
        nc.assert.truthy(host.scrollWidth <= host.clientWidth, 'No horizontal overflow');
        return { confirmedOnce: true, builderReturn: true, width: host.clientWidth };
    } finally {
        window.fetch = original;
        cleanup?.();
    }
}
