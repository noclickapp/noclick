// The console over fixtures: the real client and the real pages against canned /v1 answers (../fixtures), so every
// page opens with no account and no network. `?fixture=populated|empty|first-run|error` picks the data and `?as=key`
// answers as the API answers one of the account's keys rather than its signed-in owner; both stick while moving
// around the lab. The lab also draws what is designed and not built yet (each tagged "designed"), which the real
// console never shows.
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { DeveloperConsole } from '../DeveloperConsole';
import { fixtureClient } from '../fixtures/client';
import { FIXTURE_NOW_MS, FIXTURE_USER, parseFixtureSet } from '../fixtures/core';

export interface ConsoleLabProps {
    /** The route's `params['*']`. */
    section: string | undefined;
    /** Where the lab is mounted, without a trailing slash. */
    basePath: string;
    /** NoClick's own site and the app "back" leads to, as `ConsoleContextValue` has them. */
    site: string;
    home: string;
    /** The country to open a country's choice on, where the host knows the person's. */
    country?: string;
    /** What stands atop the sidebar. */
    workspace?: ReactNode;
}

type ActsAs = 'owner' | 'key';
const parseActsAs = (value: string | null): ActsAs => (value === 'key' ? 'key' : 'owner');

const fixedNow = () => FIXTURE_NOW_MS;
const labSignOut = () => console.warn('Sign out is disabled in the lab.');

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

/** Says, over every lab page, what the lab is. */
function LabNote({ actsAs }: { actsAs: ActsAs }) {
    return (
        <p
            role="note"
            aria-label="About the lab"
            className="pointer-events-none fixed bottom-3 left-1/2 z-[60] m-0 max-w-[calc(100vw-24px)] -translate-x-1/2 rounded-full border border-dashed border-foreground/20 bg-popover px-3 py-1.5 text-center text-[12px] text-muted-foreground shadow-lg"
        >
            Lab: made-up data{actsAs === 'key' ? ', answered as to an API key' : ''}. What’s tagged “designed” isn’t built yet, and the real console leaves it out.
        </p>
    );
}

export default function ConsoleLab({ section, basePath, site, home, country, workspace }: ConsoleLabProps) {
    const set = parseFixtureSet(useSticky('fixture'));
    const actsAs = parseActsAs(useSticky('as'));
    const client = useMemo(() => fixtureClient({ set, actsAs }), [set, actsAs]);
    return (
        <>
            <DeveloperConsole
                key={`${set}:${actsAs}`}
                section={section}
                client={client}
                actsAs={actsAs}
                basePath={basePath}
                apiUrl={client.baseUrl}
                site={site}
                home={home}
                country={country}
                user={FIXTURE_USER}
                now={fixedNow}
                lab
                onSignOut={labSignOut}
                live={null}
                workspace={workspace}
            />
            <LabNote actsAs={actsAs} />
        </>
    );
}
