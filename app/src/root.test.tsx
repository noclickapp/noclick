// @vitest-environment happy-dom
import { cleanup, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, expect, it } from 'vitest';
import App from './root';
import { useClient } from './sdk/client';
import { BROWSER_BEARER } from './sdk/proxied';

afterEach(cleanup);

function ClientShown() {
    const client = useClient();
    return (
        <p>
            {client.baseUrl} {String(client.apiKey)}
        </p>
    );
}

it('hands every screen a client for this app’s own /api, holding no key', async () => {
    const router = createMemoryRouter([{ path: '/', Component: App, children: [{ index: true, Component: ClientShown }] }]);
    render(<RouterProvider router={router} />);
    expect((await screen.findByText(/\/api/)).textContent).toBe(`${window.location.origin}/api ${BROWSER_BEARER}`);
});
