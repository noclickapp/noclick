// Exercise the public uninstall callback's authenticated backend handoff.
// Provider requests stay synthetic; exact identity matching and transactional
// deletion are covered by backend tests against an isolated Postgres container.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/supabase', () => ({ requireAuth: vi.fn() }));
vi.mock('~/lib/hostedDefaults', () => ({
    apiBaseUrl: () => 'https://api.example.test',
}));

import { action } from '~/routes/api/auth/pipedrive.callback';

const BASIC = 'Basic ' + Buffer.from('cid:fixture-secret').toString('base64');
const IDENTITY = { client_id: 'cid', company_id: 42, user_id: 7 };
const fetchMock = vi.fn();

function del(
    body: unknown = IDENTITY,
    auth: string | null = BASIC,
    method = 'DELETE'
) {
    const headers: Record<string, string> = {
        'content-type': 'application/json',
    };
    if (auth) headers.authorization = auth;
    return action({
        request: new Request(
            'https://frontend.example.test/api/auth/pipedrive/callback',
            {
                method,
                headers,
                body: method === 'GET' ? undefined : JSON.stringify(body),
            }
        ),
    } as never) as Promise<Response>;
}

beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    vi.stubEnv('PIPEDRIVE_CLIENT_SECRET', '');
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(Response.json({ success: true, removed: 1 }));
});
afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
});

describe('pipedrive uninstall action', () => {
    it('works without a frontend secret and forwards only the exact identity to the fixed backend', async () => {
        const res = await del({
            ...IDENTITY,
            timestamp: 123,
            ignored: 'private-marker',
        });
        expect(res.status).toBe(200);
        expect(await res.json()).toEqual({ success: true, removed: 1 });
        expect(res.headers.get('cache-control')).toContain('no-store');
        expect(fetchMock).toHaveBeenCalledTimes(1);
        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe(
            'https://api.example.test/api/credential-request/pipedrive/install/uninstall'
        );
        expect(options.method).toBe('POST');
        expect(options.headers.authorization).toBe(BASIC);
        expect(options.redirect).toBe('error');
        expect(options.signal).toBeInstanceOf(AbortSignal);
        expect(JSON.parse(options.body)).toEqual({
            client_id: 'cid',
            company_id: '42',
            user_id: '7',
        });
    });

    it('returns a verified idempotent zero, not a count of selected credentials', async () => {
        fetchMock.mockResolvedValue(
            Response.json({ success: true, removed: 0 })
        );
        expect(await (await del()).json()).toEqual({
            success: true,
            removed: 0,
        });
    });

    it.each([null, 'Bearer fixture', 'Basic invalid!'])(
        'rejects absent/non-Basic authentication locally: %s',
        async (auth) => {
            expect((await del(IDENTITY, auth)).status).toBe(401);
            expect(fetchMock).not.toHaveBeenCalled();
        }
    );

    it('rejects non-DELETE', async () => {
        expect((await del(IDENTITY, BASIC, 'GET')).status).toBe(405);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it.each([
        null,
        [],
        {},
        { company_id: 42, user_id: 7 },
        { ...IDENTITY, client_id: '' },
        { ...IDENTITY, client_id: 123 },
        { ...IDENTITY, client_id: 'x'.repeat(129) },
        { ...IDENTITY, company_id: '42; DROP TABLE credentials' },
        { ...IDENTITY, company_id: 0 },
        { ...IDENTITY, user_id: true },
        { ...IDENTITY, user_id: 7.1 },
        { ...IDENTITY, user_id: 9007199254740992 },
        { ...IDENTITY, user_id: '1'.repeat(21) },
    ])('fails closed on incomplete/malformed identity: %j', async (body) => {
        expect((await del(body)).status).toBe(400);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('rejects invalid JSON instead of pretending cleanup succeeded', async () => {
        const res = (await action({
            request: new Request('https://frontend.example.test', {
                method: 'DELETE',
                headers: { authorization: BASIC },
                body: '{',
            }),
        } as never)) as Response;
        expect(res.status).toBe(400);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it.each([400, 401, 500, 404, 302])(
        'preserves honest failure without exposing provider/backend bodies: %s',
        async (status) => {
            fetchMock.mockResolvedValue(
                new Response('private-marker', { status })
            );
            const res = await del();
            expect(res.status).toBe(
                [400, 401, 500].includes(status) ? status : 502
            );
            expect(await res.text()).not.toContain('private-marker');
            expect(fetchMock).toHaveBeenCalledTimes(1);
        }
    );

    it.each([
        null,
        { success: false, removed: 1 },
        { success: true, removed: -1 },
        { success: true, removed: 0.5 },
        { success: true, removed: '1' },
        { success: true, removed: 9007199254740992 },
    ])('rejects an unverified cleanup result: %j', async (result) => {
        fetchMock.mockResolvedValue(Response.json(result));
        expect((await del()).status).toBe(502);
    });

    it('does not expose or retry a timeout', async () => {
        fetchMock.mockRejectedValue(new Error('private-marker'));
        const res = await del();
        expect(res.status).toBe(502);
        expect(await res.text()).not.toContain('private-marker');
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });
});
