// `/resources-lab`, in development only: Resources over made-up data (src/screens/resources/lab), with no account and
// no network. `?fixture=populated|empty|first-run|error` picks the data and `?as=key` shows Resources as it is here,
// acting as a key (the default shows what a signed-in owner sees). A built app answers 404 and carries none of it: the
// lab is imported only where `import.meta.env.DEV` is true.
import { lazy, Suspense } from 'react';
import { data } from 'react-router';
import { useLocaleCountry } from '@/lib/localeCountry';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import type { Route } from './+types/resources-lab';

export const meta: Route.MetaFunction = () => [{ title: 'Resources lab · NoClick' }];

export function loader() {
    if (!import.meta.env.DEV) throw data(null, { status: 404 });
    return null;
}

const ResourcesLab = import.meta.env.DEV ? lazy(() => import('@/screens/resources/lab/ResourcesLab')) : null;

export default function ResourcesLabRoute() {
    const country = useLocaleCountry();
    if (!ResourcesLab) return null;
    return (
        <Suspense>
            <ResourcesLab site={NOCLICK_SITE} home="/" consolePath="/developers-lab" country={country} />
        </Suspense>
    );
}
