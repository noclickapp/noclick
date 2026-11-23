// Leaves a timer that does nothing once it fires: no failure (run by test/pendingTimers.test.ts).
import { it } from 'vitest';

it('leaves a harmless timer', () => {
    setTimeout(() => undefined, 300);
});
