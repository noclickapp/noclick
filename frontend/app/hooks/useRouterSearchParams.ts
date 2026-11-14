// The URL's query as the router has it now, and changes written on top of it. useSearchParams reads the location last
// drawn, which trails the router through a transition: the dashboard shows a page as its tab switches and the URL it was
// opened on a render later, so a page that writes its params from what it reads would write over that URL.
import { useCallback, useContext, useMemo, useSyncExternalStore } from 'react';
import { UNSAFE_DataRouterContext, useNavigate } from 'react-router';

export type SearchParamsChange = (current: URLSearchParams) => URLSearchParams;

export function useRouterSearchParams(): [URLSearchParams, (change: SearchParamsChange, options?: { replace?: boolean }) => void] {
    const context = useContext(UNSAFE_DataRouterContext);
    if (!context) throw new Error('useRouterSearchParams is for a page under a data router (createBrowserRouter, the framework’s, or createMemoryRouter).');
    const { router } = context;
    const read = useCallback(() => router.state.location.search, [router]);
    const search = useSyncExternalStore(router.subscribe, read, read);
    const params = useMemo(() => new URLSearchParams(search), [search]);
    const navigate = useNavigate();
    const write = useCallback(
        (change: SearchParamsChange, options: { replace?: boolean } = {}) => void navigate(`?${change(new URLSearchParams(router.state.location.search))}`, options),
        [navigate, router]
    );
    return [params, write];
}
