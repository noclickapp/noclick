// @vitest-environment jsdom
// The shared manual-credential form: pins that a refused save lands per field
// (and clears when that field is edited), that a provider refusal shows its
// words plus the hint, that the legacy string result still works, and that a
// credential class's "where to find these" instructions render.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { CredentialCreatePanel, toSaveFailure } from './CredentialCreatePanel';

afterEach(cleanup);

const fields = [
    { name: 'server_url', label: 'Server URL', type: 'text', required: true },
    { name: 'pat_secret', label: 'Token Secret', type: 'password', required: true, helpUrl: 'https://help.example.com/pat' },
];

function fill() {
    fireEvent.change(screen.getByPlaceholderText('My Tableau'), { target: { value: 'x' } });
    const inputs = document.querySelectorAll('input');
    fireEvent.change(inputs[1], { target: { value: 'https://acme.cloudmanager.tableau.com' } });
    fireEvent.change(inputs[2], { target: { value: 'https://site' } });
}

describe('toSaveFailure', () => {
    it('normalises the legacy string and the structured object', () => {
        expect(toSaveFailure(null)).toBeNull();
        expect(toSaveFailure('nope')).toEqual({ error: 'nope' });
        expect(toSaveFailure({ error: 'e', hint: 'h' })).toEqual({ error: 'e', hint: 'h' });
    });
});

describe('CredentialCreatePanel', () => {
    it('renders the instructions and the per-field help link', () => {
        render(<CredentialCreatePanel label="Tableau" fields={fields} onSave={async () => null} instructions="Open your site, not Cloud Manager." />);
        expect(screen.getByTestId('credential-instructions').textContent).toContain('not Cloud Manager');
        expect(screen.getByText('Where to find this').closest('a')?.getAttribute('href')).toBe('https://help.example.com/pat');
    });

    it('puts field verdicts under their inputs and clears one when it is edited', async () => {
        const onSave = vi.fn(async () => ({
            error: 'Token Secret looks like a web address.',
            fieldErrors: {
                server_url: 'That is the Cloud Manager console, not your site.',
                pat_secret: 'Token Secret looks like a web address.',
            },
        }));
        render(<CredentialCreatePanel label="Tableau" fields={fields} onSave={onSave} />);
        fill();
        fireEvent.click(screen.getByText('Create'));
        await waitFor(() => expect(screen.getAllByRole('alert').length).toBe(2));
        expect(screen.getByText(/Cloud Manager console/)).toBeTruthy();
        // The banner does not repeat a sentence an input already carries.
        expect(screen.getAllByText('Token Secret looks like a web address.').length).toBe(1);

        fireEvent.change(document.querySelectorAll('input')[2], { target: { value: 'real-secret' } });
        expect(screen.queryByText('Token Secret looks like a web address.')).toBeNull();
        expect(screen.getByText(/Cloud Manager console/)).toBeTruthy();
    });

    it('shows a provider refusal with its hint', async () => {
        render(
            <CredentialCreatePanel
                label="Tableau"
                fields={fields}
                onSave={async () => ({ error: 'The server answered HTTP 403 with a web page', hint: 'Check the server URL.' })}
            />,
        );
        fill();
        fireEvent.click(screen.getByText('Create'));
        await waitFor(() => expect(screen.getByText(/HTTP 403/)).toBeTruthy());
        expect(screen.getByText('Check the server URL.')).toBeTruthy();
    });

    it('still accepts the legacy one-line error', async () => {
        render(<CredentialCreatePanel label="Tableau" fields={fields} onSave={async () => 'Plan limit reached'} />);
        fill();
        fireEvent.click(screen.getByText('Create'));
        await waitFor(() => expect(screen.getByText('Plan limit reached')).toBeTruthy());
    });
});
