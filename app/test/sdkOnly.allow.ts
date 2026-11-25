// What in the open app still reaches NoClick around the SDK, and why (sdkOnly.test.ts). `pending` is work a later change
// moves onto the SDK (2: a typed method that exists, 3: a method over a route that exists; the plan in NoClick's own
// repository); every other kind stays. Counts only go down: lower one, or drop its file, as the work lands.
import type { Allowlist } from './sdkOnlyScan';

export const ALLOW: Allowlist = {
    'src/screens/chat/useAgentsAtWork.ts': { count: 1, why: 'pending', chunk: 3 },
    'src/screens/numbers/usePhoneNumberPurchase.ts': { count: 11, why: 'pending', chunk: 2 },
    'src/screens/resources/ResourceRenderer.tsx': { count: 1, why: 'signed-link' },
    'src/screens/work/resources/space/actions.ts': { count: 1, why: 'pending', chunk: 3 },
    'src/screens/work/slotStandards.tsx': { count: 1, why: 'signed-link' },
    'src/sdk/owner.ts': { count: 1, why: 'pending', chunk: 3 },
    'src/server/responses.server.ts': { count: 1, why: 'proxy' },
};
