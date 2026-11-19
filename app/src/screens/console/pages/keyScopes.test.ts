// A key holds a scope it must be granted by name (approvals:answer, agents:terminal, ...) only when that scope is
// picked on its own: the API lists those apart from what Full access is built from, and the console leaves them out of
// Full access whichever way a server lists them.
import { describe, expect, it } from 'vitest';
import { EXPLICIT_SCOPES, fullAccessScopes } from '@/sdk/owner';
import { META } from '../fixtures/core';
import { accountScopes } from './Keys';

describe("a key's scopes", () => {
    it('builds Full access from what a key with every scope holds, never a scope named alone', () => {
        const { full, all } = accountScopes(META);
        expect(full).not.toContain('approvals:answer');
        expect(all).toEqual(expect.arrayContaining(['approvals:answer', 'agents:terminal', ...full]));
        expect(fullAccessScopes(full).filter((s) => EXPLICIT_SCOPES.includes(s))).toEqual([]);
    });

    it('leaves them out of Full access from a server that lists every scope together', () => {
        const older = accountScopes({ scopes: [...META.scopes, ...META.explicit_scopes] });
        expect(fullAccessScopes(older.full).filter((s) => EXPLICIT_SCOPES.includes(s))).toEqual([]);
        expect(older.all).toEqual(older.full);
    });
});
