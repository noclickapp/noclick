// The pending-timer guard (test/pendingTimers.ts), run on fixtures in a vitest of their own: a timer a file leaves that
// fails once its environment is gone fails the run naming the file, the test and the line that scheduled it, whatever
// runs after that file or doesn't; one that does nothing when it fires fails nothing.
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { expect, it } from 'vitest';

const vitest = join(dirname(createRequire(import.meta.url).resolve('vitest/package.json')), 'vitest.mjs');
const config = join(import.meta.dirname, 'fixtures/leftTimer/vitest.config.ts');

function run(...files: string[]): { status: number | null; output: string } {
    // GITHUB_ACTIONS makes vitest add its GitHub reporter, which prints each error again as an annotation; the run
    // is read through the default reporter alone, wherever it runs.
    const { GITHUB_ACTIONS: _github, ...outer } = process.env;
    const env = { ...outer, NOCLICK_PENDING_TIMERS: '', CI: '1' };
    const done = spawnSync(process.execPath, [vitest, 'run', '--config', config, '--reporter', 'default', ...files], {
        encoding: 'utf8',
        env,
        timeout: 60_000,
    });
    return { status: done.status, output: `${done.stdout}\n${done.stderr}` };
}

function namesTheLeak(output: string): void {
    expect(output).toContain('a-leaves.fixture.ts left pending fired after that file\'s test environment was torn down, and failed: window is not defined');
    expect(output).toContain('setInterval(…, 100) in "starts a timer and never clears it"');
    expect(output).toMatch(/a-leaves\.fixture\.ts:6:\d+/);
    expect(output.match(/left pending fired/g)).toHaveLength(1);
}

it('fails the run on a timer that fires after its environment, naming where it came from', () => {
    const { status, output } = run();
    expect(status, output).toBe(1);
    namesTheLeak(output);
    expect(output).toContain('3 passed');
    expect(output).not.toContain('c-clears.fixture.ts left pending');
}, 70_000);

it('fails it when the leaking file runs last, with nothing after it to keep the run going', () => {
    // Thrown from its own timer, this leak was lost as its worker ended, and the run passed.
    const { status, output } = run('a-leaves');
    expect(status, output).toBe(1);
    namesTheLeak(output);
    expect(output).toContain('1 passed');
}, 70_000);
