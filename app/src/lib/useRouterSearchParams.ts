// The URL's query as the router has it now, and changes written on top of it. useSearchParams reads the location last
// drawn, which trails the router through a transition: the dashboard shows a page as its tab switches and the URL it was
// opened on a render later, so a page that writes its params from what it reads would write over that URL. The other
// way round, leaving a page for another route, the router is there a render before the page is gone: the page keeps the
// query it read on its own route, and writes nothing onto the route it's leaving for.
import { useCallback, useContext, useMemo, useRef, useSyncExternalStore } from 'react';
import { UNSAFE_DataRouterContext, useLocation, useNavigate } from 'react-router';

export type SearchParamsChange = (current: URLSearchParams) => URLSearchParams;

export function useRouterSearchParams(): [URLSearchParams, (change: SearchParamsChange, options?: { replace?: boolean }) => void] {
    const context = useContext(UNSAFE_DataRouterContext);
    if (!context) throw new Error('useRouterSearchParams is for a page under a data router (createBrowserRouter, the framework’s, or createMemoryRouter).');
    const { router } = context;
    // The route the page is drawn on, and the query the router last had there.
    const here = useLocation().pathname;
    const own = useRef('');
    const read = useCallback(() => {
        const { pathname, search } = router.state.location;
        if (pathname === here) own.current = search;
        return own.current;
    }, [router, here]);
    const search = useSyncExternalStore(router.subscribe, read, read);
    const params = useMemo(() => new URLSearchParams(search), [search]);
    const navigate = useNavigate();
    const write = useCallback(
        (change: SearchParamsChange, options: { replace?: boolean } = {}) => {
            const { pathname, search: now } = router.state.location;
            if (pathname !== here) return;
            void navigate(`?${change(new URLSearchParams(now))}`, options);
        },
        [navigate, router, here]
    );
    return [params, write];
}
