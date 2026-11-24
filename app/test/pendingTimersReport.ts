// The pending-timer guard's report (test/pendingTimers.ts): a global setup that gives the run a folder each worker
// writes to as its timers go, and fails the run naming the leaks once every file has run.
//
// A worker writes, each its own file, every timer it orphans at a file's end, what became of each (cleared, fired
// harmlessly, or a leak, with what it says), and its own exit. Vitest tears a worker's environment down as the worker
// closes, and reaches its global teardown without waiting for that: a leak firing there was thrown into a worker the
// run no longer heard, so the run passed whenever the leaking file ran last (2026-11-23). The teardown here waits
// until every orphan has settled or its worker is gone (nothing more can come from a process that ended), so the
// verdict comes from the leaks themselves, whatever order or speed the files ran in.
import { mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { TestProject } from 'vitest/node';
import { LEAKS, type Line } from './pendingTimersKey';

// One report a run: every project of it (the frontend's two) writes to the first one's.
let folder: string | undefined;

function alive(pid: number): boolean {
    try {
        process.kill(pid, 0);
        return true;
    } catch {
        return false;
    }
}

/** Each worker's lines, and whether it still owes an outcome: an orphan unsettled, in a live process that isn't this one. */
function read(dir: string): { leaks: string[]; owed: boolean } {
    const leaks: string[] = [];
    let owed = false;
    for (const name of readdirSync(dir)) {
        const pid = Number(name.split('-')[0]);
        const lines = readFileSync(join(dir, name), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l) as Line);
        const open = new Set<string>();
        let exited = false;
        for (const line of lines) {
            if ('orphaned' in line) open.add(line.orphaned);
            else if ('settled' in line) {
                open.delete(line.settled);
                if (line.leak) leaks.push(line.leak);
            } else exited = true;
        }
        owed ||= open.size > 0 && !exited && pid !== process.pid && alive(pid);
    }
    return { leaks, owed };
}

export default function setup(project: TestProject): (() => Promise<void>) | undefined {
    if (folder) {
        project.provide(LEAKS, folder);
        return undefined;
    }
    folder = mkdtempSync(join(tmpdir(), 'pending-timers-'));
    project.provide(LEAKS, folder);
    const dir = folder;
    return async () => {
        folder = undefined;
        let seen = read(dir);
        while (seen.owed) {
            await new Promise((resolve) => setTimeout(resolve, 20));
            seen = read(dir);
        }
        rmSync(dir, { recursive: true, force: true });
        if (seen.leaks.length) throw new Error(seen.leaks.join('\n\n'));
    };
}
