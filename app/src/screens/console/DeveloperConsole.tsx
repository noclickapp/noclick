// The developer console: one platform client, the account the shell reads, and
// the section picked from the route's splat. Pages are lazy and found by
// sections.ts; a page not written yet renders a stub.
import { useMemo, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { ConsoleProviders } from './ConsoleProviders';
import { ConsoleShell } from './ConsoleShell';
import { PageActionsProvider, PageHeader } from './ui/PageHeader';
import { ListStyleContext, parseListStyle } from './ui/DataTable';
import { PageFrame } from './ui/PageFrame';
import { ownerOnlyWhy, useOwnerOnly } from './ownerOnly';
import { pageName, parseSectionPath, resolvePage, type SectionDef } from './sections';

/** What whoever renders the console hands it: everything in its context (`ConsoleContextValue` says what each is),
 *  and the address it's at. */
export interface DeveloperConsoleProps extends Omit<ConsoleContextValue, 'now' | 'lab' | 'signOut'> {
    /** The route's `params['*']`. */
    section: string | undefined;
    now?: () => number;
    lab?: boolean;
    onSignOut: () => void;
}

function NotBuilt({ section }: { section: SectionDef }) {
    return (
        <>
            <PageHeader section={section.id} />
            <p className="m-0 text-sm text-muted-foreground">Not built yet.</p>
        </>
    );
}

function SectionPage({ splat }: { splat: string | undefined }) {
    const route = parseSectionPath(splat);
    const ownerCan = useOwnerOnly();
    if (!route.section) {
        return <PageHeader title="Not found" purpose="There's no console page at this address." />;
    }
    // Opened by its address in a console acting as a key: the section isn't listed, and its page would only be refused.
    if (route.section.ownerOnly && !ownerCan(route.section.ownerOnly)) {
        return <PageHeader title={route.section.label} purpose={ownerOnlyWhy(route.section.ownerOnly)} />;
    }
    const name = pageName(route)!;
    const Page = resolvePage(name);
    if (!Page) return <NotBuilt section={route.section} />;
    return (
        <PageFrame resetKey={splat ?? ''}>
            <Page rest={route.rest} />
        </PageFrame>
    );
}

/** The developers lab alone tries the list looks side by side (`?listStyle=A|B|C`); the console always has the default. */
function LabListStyle({ children }: { children: ReactNode }) {
    const [params] = useSearchParams();
    return <ListStyleContext.Provider value={parseListStyle(params.get('listStyle'))}>{children}</ListStyleContext.Provider>;
}

export function DeveloperConsole({ section, client, actsAs, basePath, apiUrl, site, home, country, user, now, lab = false, onSignOut, live, workspace }: DeveloperConsoleProps) {
    const value = useMemo<ConsoleContextValue>(
        () => ({ client, actsAs, basePath, apiUrl, site, home, country, user, now: now ?? Date.now, lab, signOut: onSignOut, live, workspace }),
        [client, actsAs, basePath, apiUrl, site, home, country, user, now, lab, onSignOut, live, workspace]
    );
    return (
        <ConsoleProviders value={value}>
            <ConsoleShell section={parseSectionPath(section).section}>
                <PageActionsProvider>
                    {lab ? (
                        <LabListStyle>
                            <SectionPage splat={section} />
                        </LabListStyle>
                    ) : (
                        <SectionPage splat={section} />
                    )}
                </PageActionsProvider>
            </ConsoleShell>
        </ConsoleProviders>
    );
}
