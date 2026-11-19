// @vitest-environment happy-dom
// Runs in is one line a place over the fake /v1: the cloud sandbox, each NoClick machine with its price, one row that
// opens buying a new machine (its sizes, regions and hosts live in that popup, never here), and your own machines. No
// host is named and no paragraph explains; while machines aren't enabled here, each machine row says so instead. The
// sandbox's one muted line says it grows for app tests, unless the agent never runs them.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fakeWork } from '../agents/fixtures/workAgents';
import { WorkProviders } from '../agents/fixtures/providers';
import type { AppTesting } from 'noclick';
import { RunsBody, type RunsValue } from './footer';

afterEach(cleanup);

function show(options: { value?: RunsValue; machinesEnabled?: boolean; noMachines?: boolean; appTesting?: AppTesting } = {}) {
    const fake = fakeWork({ machinesEnabled: options.machinesEnabled });
    if (options.noMachines) fake.machines.splice(0);
    const onChange = vi.fn<(v: RunsValue) => void>();
    const onNewMachine = vi.fn();
    render(
        <WorkProviders client={fake.client}>
            <RunsBody value={options.value ?? { kind: 'sandbox' }} appTesting={options.appTesting ?? 'by_itself'} onChange={onChange} onNewMachine={onNewMachine} onAddComputer={() => undefined} />
        </WorkProviders>
    );
    return { onChange, onNewMachine };
}

const menu = () => screen.getByRole('menu', { name: 'Runs in' });

describe('Runs in', () => {
    it('is one line a place, a new machine one row that opens buying it', async () => {
        const { onChange, onNewMachine } = show();
        await waitFor(() => expect(screen.getByRole('menuitemradio', { name: /ops-box/ })).toBeTruthy());
        expect(screen.getByRole('menuitemradio', { name: /ops-box/ }).textContent).toContain('$31.20/mo');
        const another = screen.getByRole('menuitem', { name: 'Another machine…' });
        expect(menu().textContent).not.toMatch(/Hetzner|DigitalOcean|vCPU|Small|Large|where it’s cheapest/);
        expect(menu().querySelectorAll('p')).toHaveLength(1);
        fireEvent.click(another);
        expect(onNewMachine).toHaveBeenCalledTimes(1);
        fireEvent.click(screen.getByRole('menuitemradio', { name: /ops-box/ }));
        expect(onChange).toHaveBeenCalledWith({ kind: 'machine', id: 'm-ops-box', name: 'ops-box' });
    });

    it('the sandbox says it grows for app tests unless the agent never runs them', async () => {
        show({ appTesting: 'ask_first' });
        const sandbox = screen.getByRole('menuitemradio', { name: /Cloud sandbox/ });
        expect(sandbox.textContent).toBe('Cloud sandbox$0.19/hr while workingGrows for app tests');
        cleanup();
        show({ appTesting: 'never' });
        expect(screen.getByRole('menuitemradio', { name: /Cloud sandbox/ }).textContent).toBe('Cloud sandbox$0.19/hr while working');
        expect(screen.queryByText('Grows for app tests')).toBeNull();
    });

    it('with no machine yet, the row offers a new one', async () => {
        show({ noMachines: true });
        await waitFor(() => expect(screen.getByRole('menuitem', { name: 'A new machine…' })).toBeTruthy());
    });

    it('while agents can’t run on machines here, the row can’t be pressed and says why', async () => {
        const { onNewMachine } = show({ machinesEnabled: false });
        await waitFor(() => expect(screen.getByText("Agents on machines aren't enabled on this deployment yet.")).toBeTruthy());
        const row = screen.getByRole('menuitem', { name: /Another machine…/ });
        expect(row.hasAttribute('disabled')).toBe(true);
        expect(row.textContent).toContain('Not enabled yet');
        fireEvent.click(row);
        expect(onNewMachine).not.toHaveBeenCalled();
    });
});
