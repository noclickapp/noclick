// @vitest-environment happy-dom
// The query as the router has it now: a page that writes its params from what it reads sees a change of its own query
// at once, and a page being left for another route never writes onto the route it's leaving for.
import { act, cleanup, render, screen } from '@testing-library/react';
import { useEffect } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { useRouterSearchParams } from './useRouterSearchParams';

afterEach(cleanup);

/** A page that always has a `space`: with none in its query, it writes its default, as Work does. */
function Page() {
    const [params, write] = useRouterSearchParams();
    const space = params.get('space');
    useEffect(() => {
        if (!space)
            write(
                (current) => {
                    current.set('space', 'home');
                    return current;
                },
                { replace: true }
            );
    }, [space, write]);
    return <p data-testid="space">{space ?? ''}</p>;
}

function open(address: string) {
    const router = createMemoryRouter(
        [
            { path: '/work', element: <Page />, loader: () => null },
            { path: '/resources', element: <p>Resources</p>, loader: () => null },
        ],
        { initialEntries: [address] }
    );
    render(<RouterProvider router={router} />);
    return router;
}

const at = (router: ReturnType<typeof open>) => router.state.location.pathname + router.state.location.search;

describe('the query as the router has it', () => {
    it('is read and written on the page’s own route', async () => {
        const router = open('/work');
        await screen.findByText('home');
        expect(at(router)).toBe('/work?space=home');
        await act(() => router.navigate('/work?space=acme'));
        expect(screen.getByTestId('space').textContent).toBe('acme');
        expect(at(router)).toBe('/work?space=acme');
    });

    it('is never written onto the route the page is left for', async () => {
        const router = open('/work?space=acme');
        await screen.findByText('acme');
        await act(() => router.navigate('/resources'));
        await screen.findByText('Resources');
        expect(at(router)).toBe('/resources');
    });
});
