// `/step-form-lab`, in development only: a workflow step's settings form over a made-up workflow
// (src/screens/canvas/form/lab), with no account and no network. `?scene=` picks a step (the index lists them all) and
// `?as=key` shows the form as it is here, acting as a key. A built app answers 404 and carries none of it: the lab is
// imported only where `import.meta.env.DEV` is true.
import { lazy, Suspense } from 'react';
import { data } from 'react-router';
import type { Route } from './+types/step-form-lab';

export const meta: Route.MetaFunction = () => [{ title: 'Step form lab · NoClick' }];

export function loader() {
    if (!import.meta.env.DEV) throw data(null, { status: 404 });
    return null;
}

const StepFormLab = import.meta.env.DEV ? lazy(() => import('@/screens/canvas/form/lab/StepFormLab')) : null;

export default function StepFormLabRoute() {
    if (!StepFormLab) return null;
    return (
        <Suspense>
            <StepFormLab basePath="/step-form-lab" />
        </Suspense>
    );
}
