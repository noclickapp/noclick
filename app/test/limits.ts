// How long a test that reads the whole app may take. The guards that parse every source file with TypeScript need
// about three seconds of CPU alone, and several times that while the rest of the suite shares the machine's cores:
// they wait on that work, so their limit is sized to it, never to vitest's default five seconds.
export const SCAN_S = 60_000;
