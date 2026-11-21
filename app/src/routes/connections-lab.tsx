// `/connections-lab`, in development only: the Connections page over made-up accounts (src/screens/connections/lab),
// with no account and no network. `?scene=` picks a view (the index lists them all) and `?as=key` shows the page as it
// is here, acting as a key (the default shows what a signed-in owner sees). A built app answers 404 and carries none of
// it: the lab is imported only where `import.meta.env.DEV` is true.
import { lazy, Suspense } from 'react';
import { data } from 'react-router';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import type { Route } from './+types/connections-lab';

export const meta: Route.MetaFunction = () => [{ title: 'Connections lab · NoClick' }];

export function loader() {
    if (!import.meta.env.DEV) throw data(null, { status: 404 });
    return null;
}

const ConnectionsLab = import.meta.env.DEV ? lazy(() => import('@/screens/connections/lab/ConnectionsLab')) : null;

export default function ConnectionsLabRoute() {
    if (!ConnectionsLab) return null;
    return (
        <Suspense>
            <ConnectionsLab basePath="/connections-lab" site={NOCLICK_SITE} />
        </Suspense>
    );
}
