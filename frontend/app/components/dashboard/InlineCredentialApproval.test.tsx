// @vitest-environment jsdom
// Exercise the dashboard's real fetcher flow against a route-backed review.
// Decisions must use the same CSRF token and immutable call as the standalone page.
import { useState } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { InlineCredentialApproval } from './InlineCredentialApproval';
import { AttentionRow } from './sections';
import type { ReviewState } from '~/components/credential/CredentialApproval';

const NativeRequest = Request;
beforeEach(() => {
    // jsdom supplies its own AbortSignal; Node's Request rejects that realm.
    // Keep real URL/body parsing while these UI tests leave cancellation to the browser.
    vi.stubGlobal(
        'Request',
        class extends NativeRequest {
            constructor(input: RequestInfo | URL, init?: RequestInit) {
                const options = { ...init, signal: undefined };
                if (init?.body instanceof URLSearchParams) {
                    options.body = init.body.toString();
                    options.headers = {
                        'Content-Type':
                            'application/x-www-form-urlencoded;charset=UTF-8',
                    };
                }
                super(input, options);
            }
        }
    );
});
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});
const state: ReviewState = {
    id: 'request',
    credential_id: 'mail',
    credential_name: 'Personal Gmail',
    operation: 'send_email',
    node_type: 'automation-gmail',
    arguments: {
        to: ['alex@example.test'],
        body: '<script>untrusted()</script>',
    },
    status: 'pending',
    actionable: true,
    consumed: false,
    coordinator: true,
};

function mount({ fail = false, unavailable = false, collapsed = false } = {}) {
    const decided = vi.fn();
    const submitted: Record<string, FormDataEntryValue>[] = [];
    let current = unavailable ? { detail: 'Credential not found.' } : state;
    const loader = vi.fn(() => ({ state: current, csrfToken: 'csrf-review' }));
    const action = vi.fn(async ({ request }: { request: Request }) => {
        const data = await request.formData();
        submitted.push(Object.fromEntries(data));
        if (fail) return { error: 'The rules changed. Reload the request.' };
        current = {
            ...state,
            status: JSON.parse(String(data.get('payload'))).decision,
            actionable: false,
        };
        return { saved: true };
    });
    function Queue() {
        const [expanded, setExpanded] = useState(false);
        return (
            <AttentionRow
                item={{
                    id: 'approval:request',
                    kind: 'approval',
                    title: 'Send email',
                    workflow: null,
                    createdAt: '2026-09-24T10:00:00Z',
                    meta: { credentialAction: true, approvalId: 'request' },
                }}
                now="2026-09-24T10:05:00Z"
                expanded={expanded}
                onToggle={() => setExpanded(!expanded)}
            />
        );
    }
    const router = createMemoryRouter([
        {
            path: '/',
            element: collapsed ? (
                <Queue />
            ) : (
                <InlineCredentialApproval
                    approvalId="request"
                    onDecided={decided}
                />
            ),
        },
        {
            path: '/credential/approval/:approvalId',
            loader,
            action,
            element: <div>Standalone page</div>,
        },
    ]);
    const view = render(<RouterProvider router={router} />);
    return { ...view, router, loader, action, decided, submitted };
}

it('opens immutable details inline only when Review action is clicked', async () => {
    const { loader, router, container } = mount({ collapsed: true });
    expect(loader).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Review action' }));
    expect(await screen.findByText('alex@example.test')).toBeTruthy();
    expect(screen.getByText('<script>untrusted()</script>')).toBeTruthy();
    expect(container.querySelector('input, textarea, script')).toBeNull();
    expect(router.state.location.pathname).toBe('/');
    fireEvent.click(screen.getByRole('button', { name: 'Hide details' }));
    expect(screen.queryByText('alex@example.test')).toBeNull();
});

it.each(['Approve once', 'Decline'])(
    'submits %s with CSRF through the review action and refreshes once',
    async (label) => {
        const { action, decided, router, submitted } = mount();
        fireEvent.click(await screen.findByRole('button', { name: label }));
        await waitFor(() => expect(decided).toHaveBeenCalledTimes(1));
        const request = action.mock.calls[0][0].request;
        expect(request.method).toBe('POST');
        expect(submitted).toEqual([
            {
                csrf_token: 'csrf-review',
                payload: JSON.stringify({
                    decision: label === 'Decline' ? 'rejected' : 'approved',
                }),
            },
        ]);
        expect(request.url).toContain('/credential/approval/request');
        expect(router.state.location.pathname).toBe('/');
        expect(
            await screen.findByText(
                label === 'Decline' ? 'Action declined' : 'Approved once'
            )
        ).toBeTruthy();
        expect(
            screen.queryByRole('button', { name: 'Approve once' })
        ).toBeNull();
    }
);

it('keeps a failed decision visible and retryable without dismissing the request', async () => {
    const { decided } = mount({ fail: true });
    fireEvent.click(
        await screen.findByRole('button', { name: 'Approve once' })
    );
    expect((await screen.findByRole('alert')).textContent).toContain(
        'The rules changed'
    );
    expect(
        (
            screen.getByRole('button', {
                name: 'Approve once',
            }) as HTMLButtonElement
        ).disabled
    ).toBe(false);
    expect(decided).not.toHaveBeenCalled();
});

it('does not offer actions when the owner-checked loader denies access', async () => {
    mount({ unavailable: true });
    expect((await screen.findByRole('alert')).textContent).toBe(
        'Credential not found.'
    );
    expect(screen.queryByRole('button', { name: 'Approve once' })).toBeNull();
});
