// `/usage-lab`, in development only: Settings → Usage over made-up data (src/screens/usage/lab), with no account and
// no network. `?scene=` picks a view (the index lists them all) and `?as=key` shows the page as it is here, acting as a
// key (the default shows what a signed-in owner sees). A built app answers 404 and carries none of it: the lab is
// imported only where `import.meta.env.DEV` is true.
import { lazy, Suspense } from 'react';
import { data } from 'react-router';
import type { Route } from './+types/usage-lab';

export const meta: Route.MetaFunction = () => [{ title: 'Usage lab · NoClick' }];

export function loader() {
    if (!import.meta.env.DEV) throw data(null, { status: 404 });
    return null;
}

const UsageLab = import.meta.env.DEV ? lazy(() => import('@/screens/usage/lab/UsageLab')) : null;

export default function UsageLabRoute() {
    if (!UsageLab) return null;
    return (
        <Suspense>
            <UsageLab basePath="/usage-lab" />
        </Suspense>
    );
}
