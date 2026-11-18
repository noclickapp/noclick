// A console's context over the fixtures, as a host would hand it: for a test that mounts part of the console.
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { fixtureClient } from './client';
import { FIXTURE_USER, type FixtureRoute } from './core';

export function fixtureConsole(over: Partial<ConsoleContextValue> & { routes?: readonly FixtureRoute[] } = {}): ConsoleContextValue {
    const { routes, ...rest } = over;
    const actsAs = rest.actsAs ?? 'owner';
    return {
        client: fixtureClient({ set: 'populated', actsAs, routes }, { maxRetries: 0 }),
        actsAs,
        basePath: '/developers',
        apiUrl: 'https://api.noclick.com',
        site: 'https://noclick.com',
        home: '/',
        user: FIXTURE_USER,
        now: Date.now,
        lab: false,
        signOut: () => undefined,
        live: null,
        ...rest,
    };
}
