// @vitest-environment happy-dom
// A failure leads with its words, then the one button that fixes it: the cap that was reached on the page where it's
// raised, the account to reconnect at the link the error carries. The error's type and request id come after, folded.
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';
import { CredentialDisconnected, SpendCapExceeded } from 'noclick';
import { ConsoleScope } from '../ConsoleProviders';
import { fixtureConsole } from '../fixtures/context';
import { ErrorPanel } from './ErrorPanel';

afterEach(cleanup);

function shown(error: unknown) {
    render(
        <MemoryRouter>
            <ConsoleScope value={fixtureConsole()}>
                <ErrorPanel error={error} />
            </ConsoleScope>
        </MemoryRouter>
    );
}

describe('a failure in the console', () => {
    it("offers to raise the key's cap that stopped it, with what it was folded under", () => {
        shown(new SpendCapExceeded("This key's monthly cap of $20 is reached.", { requestId: 'req_1', details: { scope: 'key', scope_id: 'key_1' } }));
        expect(screen.getByRole('alert').textContent).toContain("This key's monthly cap of $20 is reached.");
        expect(screen.getByRole('link', { name: 'Raise the key’s cap' }).getAttribute('href')).toBe('/developers/keys?key=key_1');
        expect(screen.getByText('Details').closest('details')?.open).toBe(false);
        expect(screen.getByText('request req_1')).toBeTruthy();
    });

    it('offers to reconnect an account its provider refused, at the link the error carries', () => {
        shown(new CredentialDisconnected('Gmail signed out.', { details: { connect_url: 'https://noclick.com/connect/abc' } }));
        const reconnect = screen.getByRole('link', { name: /Reconnect/ });
        expect(reconnect.getAttribute('href')).toBe('https://noclick.com/connect/abc');
        expect(reconnect.getAttribute('target')).toBe('_blank');
    });
});
