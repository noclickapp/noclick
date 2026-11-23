// Leaves a timer that reads the window after this file's environment is gone (run by test/pendingTimers.test.ts).
import { expect, it } from 'vitest';

function startBlink() {
    setTimeout(() => window.location.href, 300);
}

it('starts a timer and never clears it', () => {
    startBlink();
    expect(window).toBeDefined();
});
