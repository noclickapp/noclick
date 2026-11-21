// The step form over fixtures: the real form for one step of a made-up workflow, its schema, dropdowns, loaded values
// and previews answered as the platform API answers them (../fixtures/world.ts), so every scene opens with no account
// and no network. `?scene=` picks one (scenes.ts; with none, the index lists them); `?as=key` draws it acting as one of
// the account's keys rather than its signed-in owner. The step before the one open is a webhook whose last output the
// fields can reference.
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import type { Node } from '@xyflow/react';
import { ClientProvider } from '@/sdk/client';
import { workFixtureClient } from '@/screens/work/fixtures/client';
import { NodeConfig } from '../NodeConfig';
import { ReferenceAutocompleteProvider } from '../ReferenceAutocompleteContext';
import { ReferenceHoverProvider } from '../ReferenceHoverContext';
import { formFetch, type Observe } from '../fixtures/world';
import { SCENES, sceneSearch, type StepFormScene } from './scenes';

/** The step before the one open: a webhook whose last delivery the open step's fields reference. */
const UPSTREAM: Node[] = [
    {
        id: 'hook',
        type: 'example-hook',
        position: { x: 0, y: 0 },
        data: { label: 'Webhook', output: { body: { name: 'Ada', email: 'ada@example.test', items: [{ sku: 'A1' }] } } },
    },
];

export default function StepFormLab({ basePath }: { basePath: string }) {
    const [params] = useSearchParams();
    const scene = SCENES.find((s) => s.id === params.get('scene'));
    const actsAs = params.get('as') === 'key' ? 'key' : 'owner';
    if (!scene) return <LabIndex basePath={basePath} />;
    return <SceneView key={`${scene.id}:${actsAs}`} scene={scene} actsAs={actsAs} />;
}

function LabIndex({ basePath }: { basePath: string }) {
    const groups = [...new Set(SCENES.map((s) => s.group))];
    return (
        <div className="min-h-screen bg-background text-foreground">
            <div className="mx-auto max-w-[720px] space-y-8 px-8 py-10">
                <header>
                    <h1 className="text-[22px] font-semibold">Step form lab</h1>
                    <p className="mt-1 text-[14px] text-muted-foreground">A workflow step’s settings over a made-up workflow, with no account or network.</p>
                </header>
                {groups.map((group) => (
                    <section key={group}>
                        <h2 className="mb-2 text-[15px] font-semibold">{group}</h2>
                        <ul className="space-y-1">
                            {SCENES.filter((s) => s.group === group).map((s) => (
                                <li key={s.id}>
                                    <Link to={`${basePath}${sceneSearch(s)}`} className="text-[14px] underline-offset-4 hover:underline">
                                        {s.title}
                                    </Link>
                                </li>
                            ))}
                        </ul>
                    </section>
                ))}
            </div>
        </div>
    );
}

/** One scene: the form for its step, over its own client (no retries, so a refusal shows at once); `observe` is told of
 *  every call the form makes (a test's record). */
export function SceneView({ scene, actsAs, observe }: { scene: StepFormScene; actsAs: 'owner' | 'key'; observe?: Observe }) {
    const client = useMemo(() => workFixtureClient(formFetch({ actsAs, observe }), { maxRetries: 0 }), [actsAs, observe]);
    const [config, setConfig] = useState(scene.step.config);
    const [operation, setOperation] = useState(scene.step.operation);
    return (
        <div className="min-h-screen bg-background p-6 text-foreground">
            <div className="mx-auto max-w-[480px]" data-testid="step-form">
                <ClientProvider client={client}>
                    <ReferenceHoverProvider>
                        <ReferenceAutocompleteProvider inputNodes={UPSTREAM}>
                            <NodeConfig {...scene.step} config={config} operation={operation} onChange={setConfig} onOperationChange={setOperation} />
                        </ReferenceAutocompleteProvider>
                    </ReferenceHoverProvider>
                </ClientProvider>
            </div>
        </div>
    );
}
