// happy-dom, with a teardown that waits after taking the window away until the timers a file left have fired and
// failed (the guard drops each as it does), as one fires in the moment between a real file's teardown and its worker
// ending. Waiting on the guard, not a clock: a loaded machine once starved a fixed wait before the timer's first tick.
// A guard that stopped catching them never ends this wait, and test/pendingTimers.test.ts's run times out.
import { builtinEnvironments, type Environment } from 'vitest/runtime';

const GUARD = Symbol.for('noclick.tests.pendingTimers');
type Guard = { pending: Map<unknown, { orphaned: boolean }> };

export default <Environment>{
    name: 'slow-teardown',
    viteEnvironment: 'client',
    async setup(global, options) {
        const env = await builtinEnvironments['happy-dom'].setup(global, options);
        return {
            async teardown(g) {
                await env.teardown(g);
                const guard = (globalThis as unknown as Record<symbol, Guard | undefined>)[GUARD];
                while (guard && [...guard.pending.values()].some((entry) => entry.orphaned)) {
                    await new Promise((resolve) => setTimeout(resolve, 20));
                }
            },
        };
    },
};
