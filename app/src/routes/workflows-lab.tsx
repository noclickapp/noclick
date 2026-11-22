// `/workflows-lab`, in development only: the workflows pages over made-up data (src/screens/workflows/lab), with no
// account and no network. `?scene=` picks a view (the index lists them all) and `?as=key` shows the page as it is here,
// acting as a key. A built app answers 404 and carries none of it: the lab is imported only where
// `import.meta.env.DEV` is true.
import { lazy, Suspense } from 'react';
import { data } from 'react-router';
import type { Route } from './+types/workflows-lab';

export const meta: Route.MetaFunction = () => [{ title: 'Workflows lab · NoClick' }];

export function loader() {
    if (!import.meta.env.DEV) throw data(null, { status: 404 });
    return null;
}

const WorkflowsLab = import.meta.env.DEV ? lazy(() => import('@/screens/workflows/lab/WorkflowsLab')) : null;

export default function WorkflowsLabRoute() {
    if (!WorkflowsLab) return null;
    return (
        <Suspense>
            <WorkflowsLab basePath="/workflows-lab" />
        </Suspense>
    );
}
