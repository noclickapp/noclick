// Leaves an interval that reads the window: fine until this file's environment is gone, then failing, however long the
// teardown takes (a timeout's one firing could come before it on a loaded box). Run by test/pendingTimers.test.ts.
import { expect, it } from 'vitest';

function startBlink() {
    setInterval(() => window.location.href, 100);
}

it('starts a timer and never clears it', () => {
    startBlink();
    expect(window).toBeDefined();
});
