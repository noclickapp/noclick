// What Work's page gives its views, for tests and the local preview: the platform client (over the fake /v1), who is
// viewing, the live frames (delivered by hand), where a click goes (recorded) and a router for the URL a view reads.
import { createContext, useContext, useState, type ReactNode } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { NoClick } from 'noclick';
import { TooltipProvider } from '@/ui/tooltip';
import { WorkClientContext } from '../../client';
import { createWorkLive, WorkLiveContext, type WorkLive } from '@/sdk/live';
import { WorkNavContext, type WorkNav } from '../../nav';
import { WorkViewerContext, type WorkViewer } from '../../viewer';

/** The account looking at its own spaces, as tests see Work unless they say otherwise. */
export const ACCOUNT_VIEWER: WorkViewer = {
    type: 'account',
    id: null,
    name: 'Rowan Hale',
};

export interface Visited {
    went: { to: keyof WorkNav; args: unknown[] }[];
    nav: WorkNav;
}

/** A nav that records where each click went. */
export function recordingNav(): Visited {
    const went: Visited['went'] = [];
    const record =
        (to: keyof WorkNav) =>
        (...args: unknown[]) =>
            void went.push({ to, args });
    const nav = {
        openChannel: record('openChannel'),
        openDm: record('openDm'),
        openAgent: record('openAgent'),
        openProfile: record('openProfile'),
        openMachine: record('openMachine'),
        newAgent: record('newAgent'),
        openHome: record('openHome'),
        openMembers: record('openMembers'),
        closePanel: record('closePanel'),
    } as WorkNav;
    return { went, nav };
}

const Children = createContext<ReactNode>(null);
function Slot() {
    return <>{useContext(Children)}</>;
}

export function WorkProviders({
    client,
    live,
    nav,
    viewer = ACCOUNT_VIEWER,
    children,
    url = '/dashboard?tab=work',
    inRouter = false,
}: {
    client: NoClick;
    live?: WorkLive;
    nav?: WorkNav;
    viewer?: WorkViewer;
    children: ReactNode;
    url?: string;
    inRouter?: boolean;
}) {
    // One router for the mount; what it draws comes through context, so a rerender with new children shows them.
    const [router] = useState(() =>
        createMemoryRouter([{ path: '*', element: <Slot /> }], {
            initialEntries: [url],
        })
    );
    const [ownLive] = useState(createWorkLive);
    return (
        <WorkClientContext.Provider value={client}>
            <WorkViewerContext.Provider value={viewer}>
                <WorkLiveContext.Provider value={live ?? ownLive}>
                    <WorkNavContext.Provider value={nav ?? recordingNav().nav}>
                        <TooltipProvider>
                            {/* A page already in the app's router (the local preview) brings its own. */}
                            {inRouter ? (
                                children
                            ) : (
                                <Children.Provider value={children}>
                                    <RouterProvider router={router} />
                                </Children.Provider>
                            )}
                        </TooltipProvider>
                    </WorkNavContext.Provider>
                </WorkLiveContext.Provider>
            </WorkViewerContext.Provider>
        </WorkClientContext.Provider>
    );
}
