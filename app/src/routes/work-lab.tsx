// `/work-lab`, in development only: Work over made-up data (src/screens/work/lab), with no account and no network.
// `?scene=` picks a view (the index lists them all) and `?as=key` shows Work as it is here, acting as a key (the
// default shows what a signed-in owner sees). A built app answers 404 and carries none of it: the lab is imported only
// where `import.meta.env.DEV` is true.
import { lazy, Suspense } from 'react';
import { data } from 'react-router';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import type { Route } from './+types/work-lab';

export const meta: Route.MetaFunction = () => [{ title: 'Work lab · NoClick' }];

export function loader() {
    if (!import.meta.env.DEV) throw data(null, { status: 404 });
    return null;
}

const WorkLab = import.meta.env.DEV ? lazy(() => import('@/screens/work/lab/WorkLab')) : null;

export default function WorkLabRoute() {
    if (!WorkLab) return null;
    return (
        <Suspense>
            <WorkLab basePath="/work-lab" site={NOCLICK_SITE} />
        </Suspense>
    );
}
