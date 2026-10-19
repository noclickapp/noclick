// @vitest-environment jsdom
// The shared connect form: pins that a refused save lands per field (and clears when that field is edited), that a
// provider refusal shows who refused and their words plus the hint, that the legacy string result still works, that
// the button is never greyed out (pressed early, it says what's missing under each empty field) and names who is
// checking while it waits, and that optional values fold under "More options".
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { CredentialCreatePanel, toSaveFailure } from './CredentialCreatePanel';

afterEach(cleanup);

const fields = [
    { name: 'server_url', label: 'Server URL', type: 'text', required: true },
    { name: 'pat_secret', label: 'Token Secret', type: 'password', required: true, helpUrl: 'https://help.example.com/pat' },
];

function fill() {
    const inputs = document.querySelectorAll('input');
    fireEvent.change(inputs[0], { target: { value: 'https://acme.cloudmanager.tableau.com' } });
    fireEvent.change(inputs[1], { target: { value: 'https://site' } });
}

describe('toSaveFailure', () => {
    it('normalises the legacy string and the structured object', () => {
        expect(toSaveFailure(null)).toBeNull();
        expect(toSaveFailure('nope')).toEqual({ error: 'nope' });
        expect(toSaveFailure({ error: 'e', hint: 'h' })).toEqual({ error: 'e', hint: 'h' });
    });
});

describe('CredentialCreatePanel', () => {
    it('labels fields in sentence case and links where a value comes from by its host', () => {
        render(<CredentialCreatePanel app="Tableau" fields={fields} onSave={async () => null} />);
        expect(screen.getByText('Token secret')).toBeTruthy();
        expect(screen.getByText('help.example.com').closest('a')?.getAttribute('href')).toBe('https://help.example.com/pat');
        // No "Required" badge on every field, and no name asked up front.
        expect(screen.queryByText(/required/i)).toBeNull();
        expect(screen.queryByText('Name')).toBeNull();
    });

    it('never greys the button out: pressed early, it says what is missing under each empty field', async () => {
        const onSave = vi.fn(async () => null);
        render(<CredentialCreatePanel app="Tableau" fields={fields} onSave={onSave} />);
        const button = screen.getByRole('button', { name: 'Connect' }) as HTMLButtonElement;
        expect(button.disabled).toBe(false);
        fireEvent.click(button);
        await waitFor(() => expect(screen.getByText('Enter the server URL.')).toBeTruthy());
        expect(screen.getByText('Enter the token secret.')).toBeTruthy();
        expect(onSave).not.toHaveBeenCalled();
    });

    it('says who it is checking with while it waits', async () => {
        let finish: (v: null) => void = () => undefined;
        render(<CredentialCreatePanel app="Tableau" fields={fields} onSave={() => new Promise((resolve) => (finish = resolve))} />);
        fill();
        fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        await waitFor(() => expect(screen.getByText('Checking with Tableau…')).toBeTruthy());
        finish(null);
    });

    it('puts field verdicts under their inputs and clears one when it is edited', async () => {
        const onSave = vi.fn(async () => ({
            error: 'Token Secret looks like a web address.',
            fieldErrors: {
                server_url: 'That is the Cloud Manager console, not your site.',
                pat_secret: 'Token Secret looks like a web address.',
            },
        }));
        render(<CredentialCreatePanel app="Tableau" fields={fields} onSave={onSave} />);
        fill();
        fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        await waitFor(() => expect(screen.getAllByRole('alert').length).toBe(2));
        expect(screen.getByText(/Cloud Manager console/)).toBeTruthy();
        // Under its own label the server's "Token Secret looks like…" reads "This looks like…", said once.
        expect(screen.getAllByText('This looks like a web address.').length).toBe(1);

        fireEvent.change(document.querySelectorAll('input')[1], { target: { value: 'real-secret' } });
        expect(screen.queryByText('This looks like a web address.')).toBeNull();
        expect(screen.getByText(/Cloud Manager console/)).toBeTruthy();
    });

    it('shows a provider refusal as who refused, their words and the hint', async () => {
        render(
            <CredentialCreatePanel
                app="Tableau"
                fields={fields}
                onSave={async () => ({ error: 'The server answered HTTP 403 with a web page', hint: 'Check the server URL.' })}
            />,
        );
        fill();
        fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        await waitFor(() => expect(screen.getByText(/HTTP 403/)).toBeTruthy());
        expect(screen.getByText('Tableau didn’t accept it')).toBeTruthy();
        expect(screen.getByText('Check the server URL.')).toBeTruthy();
    });

    it('never puts a failure of ours in the provider\'s mouth', async () => {
        render(<CredentialCreatePanel app="Notion" fields={fields} onSave={async () => ({ error: 'Request timeout' })} />);
        fill();
        fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        await waitFor(() => expect(screen.getByText('Request timeout')).toBeTruthy());
        expect(screen.queryByText('Notion didn’t accept it')).toBeNull();
    });

    it('reads a refusal the reply marks as the provider\'s, even with no hint', async () => {
        render(<CredentialCreatePanel app="Slack" fields={fields} onSave={async () => ({ error: 'Slack API error: account_inactive', rejected: true })} />);
        fill();
        fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        await waitFor(() => expect(screen.getByText('Slack didn’t accept it')).toBeTruthy());
    });

    it('still accepts the legacy one-line error', async () => {
        render(<CredentialCreatePanel app="Tableau" fields={fields} onSave={async () => 'Plan limit reached'} />);
        fill();
        fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        await waitFor(() => expect(screen.getByText('Plan limit reached')).toBeTruthy());
    });

    it('folds optional values under "More options"', () => {
        render(<CredentialCreatePanel fields={[...fields, { name: 'region', label: 'Region', type: 'text', required: false }]} onSave={async () => null} />);
        expect(screen.queryByText('Region')).toBeNull();
        fireEvent.click(screen.getByText('More options'));
        expect(screen.getByText('Region')).toBeTruthy();
        expect(screen.getByText('(optional)')).toBeTruthy();
    });
});
