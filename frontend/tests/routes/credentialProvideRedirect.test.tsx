// @vitest-environment jsdom
// The public provide page returns the person to the request's redirect_url once
// the credential lands, using the address the backend builds; a request without
// one never navigates, and a failed lookup is shown instead of swallowed.
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ loaderData: vi.fn(), details: {} as Record<string, unknown> }));
vi.mock('react-router', async (importOriginal) => ({
    ...(await importOriginal<typeof import('react-router')>()),
    useLoaderData: mocks.loaderData,
}));
vi.mock('~/lib/nodeCatalog.server', () => ({ getAllSerializedNodeMeta: () => ({}) }));
vi.mock('~/components/credential/CredentialProvideFlow', () => ({
    formatCredentialType: (t: string) => t,
    CredentialProvideFlow: ({ onDetails, onProvided }: {
        onDetails: (d: Record<string, unknown>) => void;
        onProvided: () => void;
    }) => (
        <div>
            <button onClick={() => onDetails(mocks.details)}>load</button>
            <button onClick={() => onProvided()}>provide</button>
        </div>
    ),
}));

import ProvideCredentialPage from '~/routes/credential.provide.$token';

const baseDetails = {
    credential_type: 'affinity_api_key', requester_name: 'Acme', requester_email: null,
    is_oauth: false, requires_pkce: false, credential_fields: [], available_methods: [],
    status: 'pending', expires_at: '',
};

async function provide() {
    render(<ProvideCredentialPage />);
    fireEvent.click(screen.getByText('load'));
    await act(async () => { fireEvent.click(screen.getByText('provide')); });
}

describe('provide page redirect', () => {
    const assign = vi.fn();

    beforeEach(() => {
        mocks.loaderData.mockReturnValue({ token: 'tok123', nodeIconData: {} });
        vi.stubGlobal('location', { ...window.location, assign });
    });
    afterEach(() => {
        cleanup();
        assign.mockReset();
        vi.unstubAllGlobals();
    });

    it('sends the person to the backend-built return address', async () => {
        mocks.details = { ...baseDetails, redirect_url: 'https://app.example/done' };
        const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
            redirect_url: 'https://app.example/done?credential_id=c1&status=success',
        })));
        vi.stubGlobal('fetch', fetcher);
        await provide();
        expect(fetcher.mock.calls[0][0]).toMatch(/\/api\/credential-request\/tok123\/return$/);
        expect(assign).toHaveBeenCalledWith('https://app.example/done?credential_id=c1&status=success');
        expect(screen.getByTestId('provide-success-note').textContent).toBe('Taking you back…');
    });

    it('stays on the page when the request set no redirect', async () => {
        mocks.details = { ...baseDetails };
        const fetcher = vi.fn();
        vi.stubGlobal('fetch', fetcher);
        await provide();
        expect(fetcher).not.toHaveBeenCalled();
        expect(assign).not.toHaveBeenCalled();
        expect(screen.getByTestId('provide-success-note').textContent).toContain('You can safely close this page');
    });

    it('shows why it could not return instead of hanging', async () => {
        mocks.details = { ...baseDetails, redirect_url: 'https://app.example/done' };
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
            JSON.stringify({ detail: 'This credential request has not been fulfilled' }), { status: 409 })));
        await provide();
        expect(assign).not.toHaveBeenCalled();
        expect(screen.getByRole('alert').textContent).toBe('This credential request has not been fulfilled');
    });
});
