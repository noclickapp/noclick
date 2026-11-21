// Settings → Usage over made-up data: the real page (its read, "Where it goes" in the address, the charges a page at a
// time, what stands in its slots) against the page's reads on the platform's API, answered through the client the page
// reads with (world.ts), so every scene opens with no account and no network. `?scene=` picks a scene (scenes.ts; with
// none, the index lists them), with the page's own `by`, `in` and `pick` beside it, and `?as=key` answers as the API
// answers one of the account's keys (as `/usage` is served). A host adds scenes of its own (`more`) and puts in place
// what it needs before a scene reads anything (`prepare`). A window narrower than a laptop's draws it as the phone
// shell does, under a stand-in for its top bar. Days and dates read against the browser's clock and zone: for two
// screenshots to match, fix the clock at world.ts's CLOCK and the zone at UTC before the page loads.
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ClientProvider } from '@/sdk/client';
import { WorkLiveContext } from '@/sdk/live';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import { LabPhoneBar } from '@/ui/lab/LabPhoneBar';
import { useSteps } from '@/ui/lab/steps';
import { useIsMobile } from '@/ui/useIsMobile';
import { UsagePage } from '../UsagePage';
import { SCENES, sceneSearch, type UsageScene } from './scenes';
import { usageClient, type ActsAs, type Observe } from './world';

export interface UsageLabProps {
    /** Where the lab is, for its index's links. */
    basePath: string;
    /** The host's own scenes, listed after the lab's. */
    more?: readonly UsageScene[];
    /** What the host puts in place before a scene reads anything; returns what takes it away. */
    prepare?: (scene: UsageScene) => () => void;
}

export default function UsageLab({ basePath, more = [], prepare }: UsageLabProps) {
    const [params] = useSearchParams();
    const scenes = useMemo(() => [...SCENES, ...more], [more]);
    const scene = scenes.find((s) => s.id === params.get('scene'));
    const actsAs: ActsAs = params.get('as') === 'key' ? 'key' : 'owner';
    if (!scene) return <LabIndex basePath={basePath} scenes={scenes} />;
    return <SceneView key={`${scene.id}:${actsAs}`} scene={scene} actsAs={actsAs} prepare={prepare} />;
}

/** Every scene, grouped, each a link to its view. */
function LabIndex({ basePath, scenes }: { basePath: string; scenes: readonly UsageScene[] }) {
    const groups = [...new Set(scenes.map((s) => s.group))];
    return (
        <div className="min-h-screen bg-background text-foreground">
            <div className="mx-auto max-w-[720px] space-y-8 px-8 py-10">
                <header>
                    <h1 className="text-[22px] font-semibold">Usage lab</h1>
                    <p className="mt-1 text-[14px] text-muted-foreground">Settings → Usage over made-up accounts, with no account, network or backend. Narrow the window past a laptop’s for the phone’s.</p>
                </header>
                {groups.map((group) => (
                    <section key={group}>
                        <h2 className="mb-2 text-[15px] font-semibold">{group}</h2>
                        <ul className="space-y-1">
                            {scenes
                                .filter((s) => s.group === group)
                                .map((s) => (
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

/** One scene: what the host prepares in place before the page reads anything, and a client of its own over the scene's
 *  world (so nothing is kept from another scene's read), then its clicks made. `observe` hears every call it makes. */
export function SceneView({ scene, actsAs = 'owner', prepare, observe }: { scene: UsageScene; actsAs?: ActsAs; prepare?: UsageLabProps['prepare']; observe?: Observe }) {
    const [ready, setReady] = useState(false);
    const phone = useIsMobile();
    useEffect(() => {
        const undo = prepare?.(scene);
        setReady(true);
        return undo;
    }, [scene, prepare]);
    const client = useMemo(() => usageClient(scene.world, observe, actsAs), [scene, observe, actsAs]);
    // The account's change stream, as `/usage` follows it: refused here, as where the API doesn't serve it.
    const live = useMemo(() => liveFromWatch(sdkLive(client), { backstopMs: null }), [client]);
    useSteps(ready ? scene.steps : undefined, 'usage-lab', phone);
    if (!ready) return null;
    const view = scene.draw ? (
        scene.draw()
    ) : (
        // As `/usage` frames the page (and NoClick's own `/dashboard/usage`).
        <div className="mx-auto max-w-[1080px] px-4 py-8">
            <UsagePage />
        </div>
    );
    const page = (
        <div data-lab-scroll className="relative min-h-0 flex-1 overflow-y-auto">
            <ClientProvider client={client}>
                <WorkLiveContext.Provider value={live}>{view}</WorkLiveContext.Provider>
            </ClientProvider>
        </div>
    );
    return <div className="fixed inset-0 flex flex-col bg-background text-foreground">{phone ? <LabPhoneBar title="Usage">{page}</LabPhoneBar> : page}</div>;
}
