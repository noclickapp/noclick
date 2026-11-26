// What in the open app still reaches NoClick around the SDK, and why (sdkOnly.test.ts). Every kind here stays (each
// is said in sdkOnlyScan.ts's `Kind`); a new hit goes through the SDK. Counts only go down.
import type { Allowlist } from './sdkOnlyScan';

export const ALLOW: Allowlist = {
    'src/screens/resources/ResourceRenderer.tsx': { count: 1, why: 'signed-link' },
    'src/screens/work/slotStandards.tsx': { count: 1, why: 'signed-link' },
    'src/server/responses.server.ts': { count: 1, why: 'proxy' },
};
