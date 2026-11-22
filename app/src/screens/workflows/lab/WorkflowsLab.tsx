// The workflows pages over fixtures (../fixtures.ts): the list, and one workflow's page with its canvas, a step's panel,
// its Setup tab and its Test Run, answered as the platform API answers them, so every scene opens with no account and
// no network. `?scene=` picks one (with none, the index lists them); `?as=key` draws it acting as one of the account's
// keys rather than its signed-in owner. What a scene changes (a step added, a setting typed) is saved to the fixture's
// own copy of the workflow, so it's there when the page reads it again.
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ClientProvider } from '@/sdk/client';
import { createWorkLive, WorkLiveContext } from '@/sdk/live';
import { WORKFLOW, type Observe } from '@/screens/canvas/graph/fixtures';
import { workFixtureClient } from '@/screens/work/fixtures/client';
import { workflowsFetch } from '../fixtures';
import { WorkflowPage, type WorkflowTab } from '../WorkflowPage';
import { WorkflowsPage } from '../WorkflowsPage';

export interface WorkflowsScene {
    id: string;
    title: string;
    /** The list, or the open workflow's page on a tab. */
    shows: 'list' | WorkflowTab;
    /** What the key may do with the open workflow. */
    access?: 'owner' | 'viewer';
}

export const SCENES: readonly WorkflowsScene[] = [
    { id: 'list', title: 'The workflows, under their folders', shows: 'list' },
    { id: 'canvas', title: 'A workflow’s canvas', shows: 'canvas' },
    { id: 'setup', title: 'Its Setup tab', shows: 'setup' },
    { id: 'test', title: 'Its Test Run', shows: 'test' },
    { id: 'viewer', title: 'A workflow the key may only look at', shows: 'canvas', access: 'viewer' },
];

export default function WorkflowsLab({ basePath }: { basePath: string }) {
    const [params] = useSearchParams();
    const scene = SCENES.find((s) => s.id === params.get('scene'));
    const actsAs = params.get('as') === 'key' ? 'key' : 'owner';
    if (!scene) return <LabIndex basePath={basePath} />;
    return <SceneView key={`${scene.id}:${actsAs}`} scene={scene} actsAs={actsAs} />;
}

function LabIndex({ basePath }: { basePath: string }) {
    return (
        <div className="min-h-screen bg-background text-foreground">
            <div className="mx-auto max-w-[720px] space-y-6 px-8 py-10">
                <header>
                    <h1 className="text-[22px] font-semibold">Workflows lab</h1>
                    <p className="mt-1 text-[14px] text-muted-foreground">The workflows pages over a made-up account, with no account or network.</p>
                </header>
                <ul className="space-y-1">
                    {SCENES.map((s) => (
                        <li key={s.id}>
                            <Link to={`${basePath}?scene=${s.id}`} className="text-[14px] underline-offset-4 hover:underline">
                                {s.title}
                            </Link>
                        </li>
                    ))}
                </ul>
            </div>
        </div>
    );
}

/** One scene, over its own client (no retries, so a refusal shows at once); `observe` is told of every call it makes
 *  (a test's record). */
export function SceneView({ scene, actsAs, observe }: { scene: WorkflowsScene; actsAs: 'owner' | 'key'; observe?: Observe }) {
    const client = useMemo(() => workFixtureClient(workflowsFetch({ actsAs, observe, access: scene.access }), { maxRetries: 0 }), [actsAs, observe, scene.access]);
    const live = useMemo(() => createWorkLive(), []);
    const [open, setOpen] = useState<string | null>(scene.shows === 'list' ? null : WORKFLOW);
    const [tab, setTab] = useState<WorkflowTab>(scene.shows === 'list' ? 'canvas' : scene.shows);
    return (
        <ClientProvider client={client}>
            <WorkLiveContext.Provider value={live}>
                <div className="h-screen bg-background text-foreground">
                    {open ? (
                        <WorkflowPage workflowId={open} name={open === WORKFLOW ? 'Orders' : undefined} tab={tab} onTab={setTab} onBack={() => setOpen(null)} />
                    ) : (
                        <WorkflowsPage onOpen={setOpen} />
                    )}
                </div>
            </WorkLiveContext.Provider>
        </ClientProvider>
    );
}
