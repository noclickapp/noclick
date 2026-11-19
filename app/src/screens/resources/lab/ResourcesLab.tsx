// Resources over the console's fixtures (../../console/fixtures): the real reads and the real pages against canned /v1
// answers, with no account and no network. `?fixture=populated|empty|first-run|error` picks the data and `?as=key`
// answers as the API answers one of the account's keys (as `/resources` is served), else as its signed-in owner.
// Neither is a page's own address, so moving around the lab keeps them.
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { ConsoleProviders } from '@/screens/console/ConsoleProviders';
import { fixtureClient } from '@/screens/console/fixtures/client';
import { FIXTURE_NOW_MS, FIXTURE_USER, parseFixtureSet } from '@/screens/console/fixtures/core';
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { ResourcesContext, type ResourcesContextValue } from '../context';
import { ResourcesView } from '../ResourcesPage';
import { ResourcesReads } from '../reads';

export interface ResourcesLabProps {
    /** NoClick's own site and the app "back" leads to, as `ConsoleContextValue` has them. */
    site: string;
    home: string;
    /** Where the console's pages are, for Resources' links to them. */
    consolePath: string;
    country?: string;
}

type ActsAs = 'owner' | 'key';

/** A query parameter's value, kept once named: it sticks while later addresses leave it out. */
function useSticky(name: string): string | null {
    const [search] = useSearchParams();
    const requested = search.get(name);
    const [value, setValue] = useState(requested);
    useEffect(() => {
        if (requested) setValue(requested);
    }, [requested]);
    return value;
}

const fixedNow = () => FIXTURE_NOW_MS;
const labSignOut = () => console.warn('Sign out is disabled in the lab.');

export default function ResourcesLab({ site, home, consolePath, country }: ResourcesLabProps) {
    const set = parseFixtureSet(useSticky('fixture'));
    const actsAs: ActsAs = useSticky('as') === 'key' ? 'key' : 'owner';
    const client = useMemo(() => fixtureClient({ set, actsAs }), [set, actsAs]);
    const consoleValue = useMemo<ConsoleContextValue>(
        () => ({ client, actsAs, basePath: consolePath, apiUrl: client.baseUrl, site, home, country, user: FIXTURE_USER, now: fixedNow, lab: true, signOut: labSignOut, live: null }),
        [client, actsAs, consolePath, site, home, country]
    );
    const resources = useMemo<ResourcesContextValue>(() => ({ billing: true, country }), [country]);
    return (
        <ConsoleProviders key={`${set}:${actsAs}`} value={consoleValue}>
            <ResourcesContext.Provider value={resources}>
                <ResourcesReads>
                    <div className="h-dvh">
                        <ResourcesView />
                    </div>
                </ResourcesReads>
            </ResourcesContext.Provider>
            <p
                role="note"
                aria-label="About the lab"
                className="pointer-events-none fixed bottom-3 left-1/2 z-[60] m-0 max-w-[calc(100vw-24px)] -translate-x-1/2 rounded-full border border-dashed border-foreground/20 bg-popover px-3 py-1.5 text-center text-[12px] text-muted-foreground shadow-lg"
            >
                Lab: made-up data{actsAs === 'key' ? ', answered as to an API key' : ''}.
            </p>
        </ConsoleProviders>
    );
}
