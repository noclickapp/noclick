// @vitest-environment happy-dom
// What the step form puts off from a handler or a read is dropped when it unmounts: nothing is left pending after it.
// (A change still waiting to reach the canvas is passed on as the form goes, unless it's a load the form no longer
// wants, which it never passed on once gone.)
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ClientProvider } from '@/sdk/client';
import { workFixtureClient } from '@/screens/work/fixtures/client';
import { formFetch, WORKFLOW } from './fixtures/world';
import { NodeConfig } from './NodeConfig';

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

const FAKE = { toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] as Array<'setTimeout' | 'clearTimeout' | 'setInterval' | 'clearInterval'> };

const ADDRESS = 'https://hooks.example.test/hook';

const client = () => workFixtureClient(formFetch(), { maxRetries: 0 });

/** Lets the form's reads answer, with timers held. */
async function answered() {
    await act(async () => {
        for (let i = 0; i < 50; i++) await Promise.resolve();
    });
}

describe('the step form’s timers', () => {
    it('drops the “Cleared” reset when it unmounts', async () => {
        const view = render(
            <ClientProvider client={client()}>
                <NodeConfig nodeType="state-manager" nodeId="memo" workflowId={WORKFLOW} config={{ key: 'k' }} onChange={() => undefined} />
            </ClientProvider>
        );
        const button = await screen.findByRole('button', { name: 'Clear State' });
        vi.useFakeTimers(FAKE);
        fireEvent.click(button);
        await answered();
        expect(screen.getByRole('button', { name: /Cleared/ })).toBeTruthy();
        view.unmount();
        expect(vi.getTimerCount()).toBe(0);
    });

    async function loadedAddress(onChange: () => void) {
        vi.useFakeTimers(FAKE);
        const view = render(
            <ClientProvider client={client()}>
                <NodeConfig nodeType="example-hook" nodeId="hook" workflowId={WORKFLOW} config={{}} onChange={onChange} />
            </ClientProvider>
        );
        // The form reads its type, then the trigger's address; the canvas hears the address a task later, held here.
        for (let i = 0; i < 20 && !screen.queryByDisplayValue(ADDRESS); i++) await answered();
        expect(screen.getByDisplayValue(ADDRESS)).toBeTruthy();
        return view;
    }

    it('passes on a value it loaded a task later', async () => {
        const onChange = vi.fn();
        await loadedAddress(onChange);
        expect(onChange).not.toHaveBeenCalled();
        act(() => vi.advanceTimersByTime(0));
        expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ webhook_url: ADDRESS }), 'hook');
    });

    it('drops a loaded value it no longer wants when it unmounts, leaving nothing pending', async () => {
        const onChange = vi.fn();
        const view = await loadedAddress(onChange);
        view.unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.runAllTimers();
        expect(onChange).not.toHaveBeenCalled();
    });
});
