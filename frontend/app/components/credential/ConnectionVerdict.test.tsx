// @vitest-environment jsdom
// The one renderer for "did this credential work?" — pins the three stories
// (working / rejected / unverified) so no surface can dress "cannot judge" up
// as green, and that a rejection always carries the provider's words + hint.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { ConnectionVerdict, verdictState, verdictSummary } from './ConnectionVerdict';

afterEach(cleanup);

describe('verdictState', () => {
    it('maps the tri-state honestly', () => {
        expect(verdictState({ reachable: true })).toBe('working');
        expect(verdictState({ reachable: false })).toBe('rejected');
        expect(verdictState({ reachable: null })).toBe('unverified');
        expect(verdictState(null)).toBe('unverified');
        expect(verdictState(undefined)).toBe('unverified');
    });
});

describe('verdictSummary', () => {
    it('leads with the samples, then the account, then the kind of proof', () => {
        expect(verdictSummary({ reachable: true, noun: 'workbooks', samples: [{ label: 'Sales' }, { label: 'Ops' }], total: 5 }))
            .toBe('workbooks: Sales, Ops +3 more');
        expect(verdictSummary({ reachable: true, account_label: 'Acme' })).toBe('Acme');
        expect(verdictSummary({ reachable: true, proves: 'reachability' })).toBe('key accepted');
        expect(verdictSummary({ reachable: false, error: 'nope' })).toBeNull();
    });
});

describe('ConnectionVerdict', () => {
    it('shows the account data as the proof', () => {
        render(
            <ConnectionVerdict
                providerLabel="Tableau"
                verification={{ reachable: true, noun: 'workbooks', samples: [{ label: 'Sales' }, { label: 'Ops' }], account_label: 'Acme site' }}
            />,
        );
        expect(screen.getByText(/Your workbooks/)).toBeTruthy();
        expect(screen.getByText('Sales, Ops')).toBeTruthy();
        expect(screen.getByText('Acme site')).toBeTruthy();
    });

    it('says when a probe only proved the key was accepted', () => {
        render(<ConnectionVerdict providerLabel="Translate" verification={{ reachable: true, proves: 'reachability' }} />);
        expect(screen.getByText('Translate accepted this key')).toBeTruthy();
    });

    it('renders a rejection with the provider words, the hint and a way back', () => {
        const back = vi.fn();
        render(
            <ConnectionVerdict
                providerLabel="Tableau"
                onReconnect={back}
                verification={{ reachable: false, error: 'HTTP 403 with a web page', hint: 'That address serves a web page, not an API.' }}
            />,
        );
        expect(screen.getByText('Tableau rejected this credential')).toBeTruthy();
        expect(screen.getByText('HTTP 403 with a web page')).toBeTruthy();
        expect(screen.getByText(/serves a web page/)).toBeTruthy();
        fireEvent.click(screen.getByText(/Reconnect Tableau/));
        expect(back).toHaveBeenCalled();
    });

    it('never dresses "cannot judge" up as working', () => {
        render(<ConnectionVerdict providerLabel="Tableau" verification={{ reachable: null }} />);
        expect(screen.getByText('Saved, not verified')).toBeTruthy();
        expect(screen.queryByText(/Working/)).toBeNull();
    });

    it('lets the samples answer the field they came from', () => {
        const pick = vi.fn();
        render(
            <ConnectionVerdict
                providerLabel="Slack"
                onPick={pick}
                pickField="channel"
                picked=""
                verification={{ reachable: true, noun: 'channels', answers_field: 'channel', samples: [{ label: '#sales', value: 'C1' }] }}
            />,
        );
        fireEvent.click(screen.getByText('#sales'));
        expect(pick).toHaveBeenCalledWith('C1');
    });
});
