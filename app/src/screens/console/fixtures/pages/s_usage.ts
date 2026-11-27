// Usage: the app's own page's reads (GET /v1/usage/groups, GET /v1/usage/billing, POST /v1/usage/charges), answered
// from the Usage lab's world so the console draws the same page over the same made-up month. Populated, a Member
// account that spends; empty and first-run, an account with no charges; the error set, the read failing.
import { worldApi, type UsageWorld } from '@/screens/usage/lab/world';
import { PAGE_ERROR, ok, type FixtureReply, type FixtureRequest, type FixtureRoute } from '../core';

function worldOf(request: FixtureRequest): UsageWorld {
    return request.set === 'populated' ? { billed: 'member' } : { unbilled: 'empty' };
}

/** One of the world's answers as a fixture reply: its JSON under its `object`. */
async function answer(object: string, read: unknown, body: (value: never) => object): Promise<FixtureReply> {
    const value = await read;
    if (value instanceof Response) return { status: value.status, body: await value.json() };
    return ok({ object, ...body(value as never) });
}

export const routes: FixtureRoute[] = [
    {
        method: 'GET',
        path: '/v1/usage/groups',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : answer('usage_groups', worldApi(worldOf(r)).groups(), (ledger: object) => ledger)),
    },
    {
        method: 'GET',
        path: '/v1/usage/billing',
        reply: (r) => (r.set === 'error' ? PAGE_ERROR : answer('usage_billing', worldApi(worldOf(r)).billing(), (billing: unknown) => ({ billing }))),
    },
    {
        method: 'POST',
        path: '/v1/usage/charges',
        reply: (r) => {
            if (r.set === 'error') return PAGE_ERROR;
            const asked = (r.body ?? {}) as { keys?: string[]; day?: string; cursor?: string; limit?: number };
            const page = worldApi(worldOf(r)).charges({ keys: asked.keys ?? null, day: asked.day ?? null }, asked.cursor ?? null, asked.limit ?? 50);
            return answer('usage_charges', page, (p: object) => p);
        },
    },
];
