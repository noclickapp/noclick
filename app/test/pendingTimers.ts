// A timer a DOM test file leaves behind fails the run by name. A DOM environment's setTimeout and setInterval are Node's
// own, so one still pending when the file's environment is torn down fires afterwards, against a window that's gone, and
// the run fails on a bare "window is not defined" that names no test, every test having passed. This records each timer
// a DOM file schedules (the file, the test and the repo frames that scheduled it); one still pending after the file's
// last test that throws when it fires is rethrown naming them, so the leak is found where it was made.
//
// It judges timers that fire after their environment and fail, not every timer pending at a test's end: today most DOM
// files leave a rendered tree, an unanswered request's timeout or a stream's reconnect pending past their tests, which
// do nothing once they fire (hundreds of them when this was written), and failing on them would be noise. Both the open
// app's tests and the app built on it run under it.
// `NOCLICK_PENDING_TIMERS=report` lists, at each DOM file's end, every timer and animation frame still pending after
// whatever it rendered is unmounted (and clears them): the audit to find the rest.
import { afterAll, expect } from 'vitest';

type Pending = { kind: string; ms: number; file?: string; test?: string; from: string[]; orphaned: boolean };
type Guard = { active: boolean; pending: Map<unknown, Pending> };

const KEY = Symbol.for('noclick.tests.pendingTimers');
const REPORT = process.env.NOCLICK_PENDING_TIMERS === 'report';

// The nearest frames of the repo's own code that scheduled it: what to fix.
function scheduledFrom(): string[] {
    const limit = Error.stackTraceLimit;
    Error.stackTraceLimit = 40;
    const stack = new Error().stack ?? '';
    Error.stackTraceLimit = limit;
    return stack
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => /\(?\//.test(line) && !/node_modules|node:|test\/pendingTimers\.ts/.test(line))
        .map((line) => line.replace(`${process.cwd()}/`, ''))
        .slice(0, 4);
}

function describe({ kind, ms, test, from }: Pending): string {
    return (
        `${kind}(…, ${ms})${test ? ` in "${test}"` : ''}` +
        (from.length ? from.map((frame) => `\n      ${frame}`).join('') : "\n      (scheduled outside the repo's code)")
    );
}

// Once per process: a worker that runs file after file keeps it, and a timer outlives the file that made it.
function install(): Guard {
    const guard: Guard = { active: false, pending: new Map() };
    const g = globalThis as unknown as Record<string, (...args: unknown[]) => unknown>;
    const real = { setTimeout: g.setTimeout, clearTimeout: g.clearTimeout, setInterval: g.setInterval, clearInterval: g.clearInterval };

    const schedule = (kind: 'setTimeout' | 'setInterval', self: unknown, callback: unknown, ms: unknown, args: unknown[]) => {
        if (!guard.active || typeof callback !== 'function') return real[kind].call(self, callback, ms, ...args);
        const state = expect.getState();
        const entry: Pending = {
            kind,
            ms: Number(ms) || 0,
            file: state.testPath?.replace(`${process.cwd()}/`, ''),
            test: state.currentTestName,
            from: scheduledFrom(),
            orphaned: false,
        };
        const handle = real[kind].call(
            self,
            function (this: unknown, ...a: unknown[]) {
                if (kind === 'setTimeout') guard.pending.delete(handle);
                if (!entry.orphaned) return (callback as (...x: unknown[]) => unknown).apply(this, a);
                try {
                    return (callback as (...x: unknown[]) => unknown).apply(this, a);
                } catch (error) {
                    guard.pending.delete(handle);
                    real.clearTimeout.call(globalThis, handle);
                    throw new Error(
                        `A timer ${entry.file ?? 'a test file'} left pending fired after that file's test environment was ` +
                            `torn down, and failed: ${(error as Error)?.message ?? error}\n  ${describe(entry)}\n` +
                            `Clear it when its component unmounts (an effect's cleanup), or, in a test, before the test ends.`,
                        { cause: error }
                    );
                }
            },
            ms,
            ...args
        );
        guard.pending.set(handle, entry);
        return handle;
    };
    const clear = function (this: unknown, handle: unknown) {
        guard.pending.delete(handle);
        // Node's clearTimeout clears an interval too, and the reverse.
        return real.clearTimeout.call(this, handle);
    };
    g.setTimeout = function (this: unknown, callback: unknown, ms?: unknown, ...args: unknown[]) {
        return schedule('setTimeout', this, callback, ms, args);
    };
    g.setInterval = function (this: unknown, callback: unknown, ms?: unknown, ...args: unknown[]) {
        return schedule('setInterval', this, callback, ms, args);
    };
    g.clearTimeout = clear;
    g.clearInterval = clear;
    return guard;
}

if (typeof document !== 'undefined') {
    const scope = globalThis as unknown as Record<symbol, Guard | undefined>;
    const guard = (scope[KEY] ??= install());
    guard.active = true;

    // Animation frames die with their environment's window, so only the audit lists them.
    const frames = new Map<number, Pending>();
    const win = globalThis as unknown as {
        requestAnimationFrame?: (cb: FrameRequestCallback) => number;
        cancelAnimationFrame?: (id: number) => void;
    };
    if (REPORT && win.requestAnimationFrame && win.cancelAnimationFrame) {
        const request = win.requestAnimationFrame;
        const cancel = win.cancelAnimationFrame;
        win.requestAnimationFrame = (callback: FrameRequestCallback) => {
            const id = request((time) => {
                frames.delete(id);
                callback(time);
            });
            frames.set(id, { kind: 'requestAnimationFrame', ms: 0, test: expect.getState().currentTestName, from: scheduledFrom(), orphaned: false });
            return id;
        };
        win.cancelAnimationFrame = (id: number) => {
            frames.delete(id);
            cancel(id);
        };
    }

    afterAll(async () => {
        const file = expect.getState().testPath?.replace(`${process.cwd()}/`, '');
        if (REPORT) {
            const { cleanup } = await import('@testing-library/react');
            cleanup();
        }
        guard.active = false;
        const left = [...guard.pending.entries()].filter(([, entry]) => entry.file === file && !entry.orphaned);
        left.forEach(([, entry]) => (entry.orphaned = true));
        if (!REPORT) return;
        left.forEach(([handle]) => clear(handle));
        const all = [...left.map(([, entry]) => entry), ...frames.values()];
        frames.forEach((_, id) => win.cancelAnimationFrame?.(id));
        frames.clear();
        if (all.length) {
            throw new Error(
                `This file left ${all.length} timer${all.length === 1 ? '' : 's'} pending after everything it rendered was ` +
                    `unmounted:\n${all.map((entry) => `  ${describe(entry)}`).join('\n')}`
            );
        }
    });

    function clear(handle: unknown) {
        guard.pending.delete(handle);
        clearTimeout(handle as ReturnType<typeof setTimeout>);
    }
}

export {};
