// What the pending-timer guard (test/pendingTimers.ts) and its report (test/pendingTimersReport.ts) share: the key the
// run's global setup provides its folder by, which each worker injects, and the lines a worker writes there. Its own
// module: the global setup's own exports read as nothing in a worker.
export const LEAKS = 'pendingTimersReport';

/** A timer orphaned at its file's end; what became of it (``leak``: it failed, saying this); the worker's exit. */
export type Line = { orphaned: string } | { settled: string; leak?: string } | { exited: true };

declare module 'vitest' {
    export interface ProvidedContext {
        pendingTimersReport: string;
    }
}
