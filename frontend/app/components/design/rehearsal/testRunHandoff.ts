/* The builder→Test Run hand-off: when the AI builder fires a `run_test` op,
   this primes the sticky valtio flags that (1) open the agent block's test
   mode and (2) arm RehearsalScreen's auto-start — selection rides inside the
   payload so the screen applies it only after the live scenario list can
   confirm it exists. Imperative (no hooks) because the caller is an event
   consumer, and sticky because every target component may mount later. */

import { getLocalComponentValtio } from '~/state';
import { rehydrateRehearsalAuthoring } from './useRehearsalAuthoring';

export interface TestRunRequest {
    /** Trigger node TYPE (e.g. 'automation-telegram') — the scenario list's slug. */
    trigger?: string;
    /** A situation slug under that trigger (authored key or custom run slug). */
    run?: string;
}

function prime(path: string, key: string, value: unknown): void {
    const proxy = getLocalComponentValtio(path);
    if (!proxy.state) proxy.state = {};
    proxy.state[key] = value;
}

/** Open the Test Run screen for this workflow and start a rehearsal once its
    scenario list has settled. Safe to call before any target is mounted. */
export async function requestTestRun(
    workflowId: string,
    opts?: TestRunRequest
): Promise<void> {
    // The builder may have just authored the run it names — refresh the
    // server-backed authoring store first so the slug is resolvable.
    try {
        await rehydrateRehearsalAuthoring(workflowId);
    } catch {
        // Auto-start falls back to the first available situation.
    }
    prime('rehearsalScreen', `autorun-${workflowId}`, {
        trigger: opts?.trigger,
        run: opts?.run,
    });
    prime('agentChatBlock', `open-test-${workflowId}`, true);
}
