// @vitest-environment happy-dom
// App testing in an agent's chat: each switch is one quiet line (its lead in bold, then what it costs), a line that
// turned it on carrying What's this? and the way to the agent's profile; the card that asks the owner first answers
// Allow, Allow from now on or Not now through the question's own route, then gives way to the line its answer leaves.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import type { NoClick } from 'noclick';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CoordinatorToolCall } from '@/lib/toolCalls';
import { WorkClientContext } from '../client';

const requests: { method: string; path: string; json?: unknown }[] = [];
let stored: Record<string, unknown> = {};
const client = {
    request: async (method: string, path: string, options: { json?: unknown } = {}) => {
        requests.push({ method, path, json: options.json });
        if (method === 'POST') stored = { ...stored, status: 'answered', answer: { choice: (options.json as { choice: string }).choice } };
        return stored;
    },
};
import { AppTestingAskCard, AppTestingLine } from './AppTesting';

/** The card reads and answers the question with Work's client. */
const withClient = (card: ReactElement) => <WorkClientContext.Provider value={client as unknown as NoClick}>{card}</WorkClientContext.Provider>;

afterEach(() => {
    cleanup();
    requests.length = 0;
});

const ON = { state: 'on' as const, lead: 'Atlas turned on app testing for this task', detail: 'about $0.44/hour while it works', reason: 'run the checkout tests against Postgres' };
const OFF = { state: 'off' as const, lead: 'Atlas turned app testing off', detail: 'ran 18 min, $0.13', reason: 'run the checkout tests against Postgres' };

describe('a switch’s line', () => {
    it('says it went on and what it costs, explains itself and opens the profile', () => {
        const onProfile = vi.fn();
        render(<AppTestingLine note={ON} agentName="Atlas" onProfile={onProfile} />);
        expect(screen.getByText('Atlas turned on app testing for this task').closest('[data-row="app-testing"]')?.textContent).toContain(
            'Atlas turned on app testing for this task · about $0.44/hour while it works'
        );
        expect(screen.queryByTestId('app-testing-explained')).toBeNull();
        fireEvent.click(screen.getByRole('button', { name: 'What’s this?' }));
        const explained = screen.getByTestId('app-testing-explained').textContent;
        expect(explained).toContain('Atlas starts your app and a test database on a bigger computer');
        expect(explained).toContain('This time: run the checkout tests against Postgres.');
        expect(explained).toContain('This is Docker, for those who know the term.');
        fireEvent.click(screen.getByRole('button', { name: 'Change in Atlas’s profile' }));
        expect(onProfile).toHaveBeenCalledTimes(1);
    });

    it('says it went off with what it really ran and cost, and nothing more', () => {
        render(<AppTestingLine note={OFF} agentName="Atlas" onProfile={() => undefined} />);
        expect(screen.getByText('Atlas turned app testing off').parentElement?.textContent).toBe('Atlas turned app testing off · ran 18 min, $0.13');
        expect(screen.queryByRole('button')).toBeNull();
    });
});

function asked(): CoordinatorToolCall {
    return {
        id: 'call-1',
        tool: 'app_testing',
        args: { on: true, reason: ON.reason },
        result: { success: true, request_id: 'req-1', operation_id: 'op-1', status: 'asked', title: 'Atlas needs to run a test database to check your app', detail: 'About $0.44/hour while it works', reason: ON.reason },
        running: false,
    } as unknown as CoordinatorToolCall;
}

const pending = () => {
    stored = { id: 'req-1', status: 'pending', message: 'Atlas needs to run a test database to check your app. Allow?', options: ['Allow', 'Not now', 'Allow from now on'], answer: null, expires_at: null, owner_can_answer: true };
};

describe('the card asking first', () => {
    it.each([
        [false, 'Allow', 'Allow'],
        [true, 'Allow', 'Allow from now on'],
        [false, 'Not now', 'Not now'],
    ])('with from now on %s, %s answers %s, then gives way to its line', async (always, button, choice) => {
        pending();
        const { container } = render(withClient(<AppTestingAskCard call={asked()} />));
        expect(screen.getByText('Atlas needs to run a test database to check your app')).toBeTruthy();
        expect(screen.getByText('About $0.44/hour while it works, nothing while idle')).toBeTruthy();
        expect(screen.getByText('It’s for this: run the checkout tests against Postgres.')).toBeTruthy();
        if (always) fireEvent.click(screen.getByRole('checkbox', { name: 'Allow from now on' }));
        await waitFor(() => expect((screen.getByRole('button', { name: button }) as HTMLButtonElement).disabled).toBe(false));
        fireEvent.click(screen.getByRole('button', { name: button }));
        await waitFor(() => expect(container.textContent).toBe(''));
        expect(requests.at(-1)).toEqual({ method: 'POST', path: '/v1/humans/requests/req-1/answer', json: { choice } });
    });

    it('reads back as one line once nobody answered in time, and waits on someone else without buttons', async () => {
        stored = { id: 'req-1', status: 'expired', message: 'x', options: null, answer: null, expires_at: null };
        render(withClient(<AppTestingAskCard call={asked()} />));
        expect(await screen.findByText('Nobody answered in time · app testing stayed off')).toBeTruthy();
        cleanup();
        pending();
        stored = { ...stored, owner_can_answer: false };
        render(withClient(<AppTestingAskCard call={asked()} />));
        expect(await screen.findByText('Waiting for their answer')).toBeTruthy();
        expect(screen.queryByRole('button', { name: 'Allow' })).toBeNull();
    });
});
