// Regions: the catalog, and the account's default region set in Settings.
import { fixtureAccount, ok, type FixtureRoute } from '../core';

const CATALOG = [
    ['us-east', 'US East', 'The eastern United States'],
    ['us-west', 'US West', 'The western United States'],
    ['eu', 'Europe', 'The European Economic Area'],
    ['ap', 'Asia-Pacific', 'Asia and the Pacific'],
] as const;

export function fixtureRegions(defaultRegion: string | null) {
    return CATALOG.map(([name, label, location]) => ({
        object: 'region',
        name,
        label,
        location,
        kinds: ['sandbox', 'agent'],
        default: name === defaultRegion,
    }));
}

export const routes: readonly FixtureRoute[] = [
    {
        method: 'GET',
        path: '/v1/regions',
        reply: (r) => ok({ object: 'list', data: fixtureRegions(fixtureAccount(r.set).default_region), next_cursor: null }),
    },
    {
        method: 'PATCH',
        path: '/v1/account',
        reply: (r) => {
            const body = (r.body ?? {}) as { default_region?: string | null; spending_paused?: unknown };
            const account = fixtureAccount(r.set);
            return ok({
                ...account,
                ...('default_region' in body ? { default_region: body.default_region } : {}),
                // Designed: the default a paused user is told.
                ...('spending_paused' in body ? { spending_paused: body.spending_paused } : {}),
            });
        },
    },
];
