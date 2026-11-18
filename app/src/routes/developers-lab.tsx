// `/developers-lab/*`, in development only: the developer console over made-up data (src/screens/console/lab), with
// no account and no network, for working on its pages. `?fixture=populated|empty|first-run|error` picks the data and
// `?as=key` shows the console as it is here, acting as a key (the default shows what a signed-in owner sees). A built
// app answers 404 and carries none of it: the lab is imported only where `import.meta.env.DEV` is true.
import { lazy, Suspense } from 'react';
import { data, useParams } from 'react-router';
import { useLocaleCountry } from '@/lib/localeCountry';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import type { Route } from './+types/developers-lab';

const LAB_PATH = '/developers-lab';

export const meta: Route.MetaFunction = () => [{ title: 'Developers lab · NoClick' }];

export function loader() {
    if (!import.meta.env.DEV) throw data(null, { status: 404 });
    return null;
}

const ConsoleLab = import.meta.env.DEV ? lazy(() => import('@/screens/console/lab/ConsoleLab')) : null;

export default function DevelopersLab() {
    const params = useParams();
    const country = useLocaleCountry();
    if (!ConsoleLab) return null;
    return (
        <Suspense>
            <ConsoleLab section={params['*']} basePath={LAB_PATH} site={NOCLICK_SITE} home="/" country={country} />
        </Suspense>
    );
}
