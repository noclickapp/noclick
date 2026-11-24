// @vitest-environment node
// Keeps the run going while the timer a-leaves left fires, as the rest of a real suite does (run by
// test/pendingTimers.test.ts).
import { it } from 'vitest';

it('runs on', () => new Promise<void>((resolve) => setTimeout(resolve, 2500)));
