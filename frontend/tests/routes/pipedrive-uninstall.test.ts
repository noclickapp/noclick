// Unit tests for the Pipedrive OAuth callback route's `action` (DELETE) — the
// app-uninstall handler. Pipedrive sends the uninstall to the SAME callback URL
// as install (only one is allowed), so this verifies: DELETE-only, HTTP Basic
// auth is enforced, and matching Pipedrive credentials are deleted by
// company_id / user_id. Supabase is mocked so the test checks routing/auth/
// cleanup logic, not network I/O.

import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/supabase', () => ({ createServiceRoleClient: vi.fn() }));

import { createServiceRoleClient } from '~/lib/supabase';
import { action } from '~/routes/api/auth/pipedrive.callback';

const BASIC = 'Basic ' + Buffer.from('cid:secret').toString('base64');

function fakeClient(creds: { id: string }[]) {
    const calls: {
        orFilter?: string;
        deletedShareIds?: string[];
        deletedCredIds?: string[];
    } = {};
    const client = {
        from(table: string) {
            if (table === 'credentials') {
                return {
                    select: () => ({
                        eq: () => ({
                            or: (f: string) => {
                                calls.orFilter = f;
                                return Promise.resolve({ data: creds, error: null });
                            },
                        }),
                    }),
                    delete: () => ({
                        in: (_c: string, ids: string[]) => {
                            calls.deletedCredIds = ids;
                            return Promise.resolve({ error: null });
                        },
                    }),
                };
            }
            return {
                delete: () => ({
                    eq: () => ({
                        in: (_c: string, ids: string[]) => {
                            calls.deletedShareIds = ids;
                            return Promise.resolve({ error: null });
                        },
                    }),
                }),
            };
        },
    };
    return { client, calls };
}

function del(body: unknown, auth: string | null = BASIC, method = 'DELETE') {
    const headers: Record<string, string> = { 'content-type': 'application/json' };
    if (auth) headers.authorization = auth;
    return action({
        request: new Request('https://noclick.com/api/auth/pipedrive/callback', {
            method,
            headers,
            body: method === 'GET' ? undefined : JSON.stringify(body),
        }),
    } as never) as Promise<Response>;
}

beforeEach(() => {
    process.env.PIPEDRIVE_CLIENT_ID = 'cid';
    process.env.PIPEDRIVE_CLIENT_SECRET = 'secret';
    vi.mocked(createServiceRoleClient).mockReset();
});

describe('pipedrive uninstall action', () => {
    it('deletes matching credential(s) and returns 200', async () => {
        const { client, calls } = fakeClient([{ id: 'cred-1' }]);
        vi.mocked(createServiceRoleClient).mockReturnValue(client as never);

        const res = await del({ client_id: 'cid', company_id: 42, user_id: 7 });
        expect(res.status).toBe(200);
        expect(await res.json()).toEqual({ success: true, removed: 1 });
        expect(calls.deletedCredIds).toEqual(['cred-1']);
        expect(calls.deletedShareIds).toEqual(['cred-1']);
        // both identifiers become PostgREST .or filters (numeric-sanitized)
        expect(calls.orFilter).toContain('pipedrive_company_id.eq.42');
        expect(calls.orFilter).toContain('pipedrive_user_id.eq.7');
    });

    it('rejects a bad Basic auth with 401 and never touches the DB', async () => {
        const res = await del(
            { company_id: 42 },
            'Basic ' + Buffer.from('cid:WRONG').toString('base64')
        );
        expect(res.status).toBe(401);
        expect(createServiceRoleClient).not.toHaveBeenCalled();
    });

    it('rejects missing auth with 401', async () => {
        const res = await del({ company_id: 42 }, null);
        expect(res.status).toBe(401);
    });

    it('rejects non-DELETE with 405', async () => {
        const res = await del(undefined, BASIC, 'GET');
        expect(res.status).toBe(405);
        expect(createServiceRoleClient).not.toHaveBeenCalled();
    });

    it('no-ops (removed:0) when the body carries no company/user id', async () => {
        const res = await del({ client_id: 'cid' });
        expect(res.status).toBe(200);
        expect(await res.json()).toEqual({ success: true, removed: 0 });
        expect(createServiceRoleClient).not.toHaveBeenCalled();
    });

    it('ignores non-numeric ids (injection guard) → treated as absent', async () => {
        const res = await del({ company_id: "42; DROP TABLE credentials" });
        expect(res.status).toBe(200);
        expect(await res.json()).toEqual({ success: true, removed: 0 });
    });
});
