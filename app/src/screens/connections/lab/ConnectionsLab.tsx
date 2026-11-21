// The Connections page over fixtures: the real page, its account pages and its dialogs, against a made-up account's
// connected accounts answered as the platform API answers (../fixtures/world.ts), so every scene opens with no account
// and no network. `?scene=` picks one (scenes.ts; with none, the index lists them), with the page's own `view` and
// `account` beside it; `?as=key` draws it acting as one of the account's keys rather than its signed-in owner. A window
// narrower than a laptop's draws it as the phone shell does, under a stand-in for its top bar. Dates read against the
// browser's clock: for two screenshots to match, fix the clock at the fixtures' CLOCK before the page loads. A host that
// reaches the network its own way besides the platform client answers that from the scene with `prepare`, and may add
// scenes of its own (`more`).
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ConsoleScope } from '@/screens/console/ConsoleProviders';
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import { LabPhoneBar } from '@/ui/lab/LabPhoneBar';
import { useSteps } from '@/ui/lab/steps';
import { useIsMobile } from '@/ui/useIsMobile';
import { workFixtureClient } from '@/screens/work/fixtures/client';
import { ConnectionsView } from '../ConnectionsPage';
import { ConnectionsContext, type ConnectionsContextValue } from '../context';
import { teamOf, worldFetch, type Observe } from '../fixtures/world';
import { SCENES, sceneSearch, type ConnectionsScene } from './scenes';

const NO_VALUES: ConnectionsContextValue = {};

export interface ConnectionsLabProps {
    /** Where the lab is mounted, without a trailing slash. */
    basePath: string;
    /** NoClick's own site, for the links the page builds to it: empty where the lab is served from it. */
    site?: string;
    /** What a host hands the page besides its client (the scene's team workspace goes over it). */
    values?: ConnectionsContextValue;
    /** Answers what the host reaches outside the platform client for `scene`, before the page reads anything; returns how
     *  to stop. */
    prepare?: (scene: ConnectionsScene) => () => void;
    /** The host's own scenes, after the lab's. */
    more?: readonly ConnectionsScene[];
}

export default function ConnectionsLab({ basePath, site = NOCLICK_SITE, values = NO_VALUES, prepare, more = [] }: ConnectionsLabProps) {
    const [params] = useSearchParams();
    const scenes = useMemo(() => [...SCENES, ...more], [more]);
    const scene = scenes.find((s) => s.id === params.get('scene'));
    const actsAs = params.get('as') === 'key' ? 'key' : 'owner';
    if (!scene) return <LabIndex basePath={basePath} scenes={scenes} />;
    return <SceneView key={`${scene.id}:${actsAs}`} scene={scene} actsAs={actsAs} site={site} values={values} prepare={prepare} />;
}

/** Every scene, grouped, each a link to its view. */
function LabIndex({ basePath, scenes }: { basePath: string; scenes: readonly ConnectionsScene[] }) {
    const groups = [...new Set(scenes.map((s) => s.group))];
    return (
        <div className="min-h-screen bg-background text-foreground">
            <div className="mx-auto max-w-[720px] space-y-8 px-8 py-10">
                <header>
                    <h1 className="text-[22px] font-semibold">Connections lab</h1>
                    <p className="mt-1 text-[14px] text-muted-foreground">The Connections page over made-up accounts, with no account or network. Narrow the window past a laptop’s for the phone’s.</p>
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

/** One scene: what the host prepares in place before the page reads anything, its world's API, then its clicks made;
 *  `observe` is told of every call the page makes (a test's record). */
export function SceneView({
    scene,
    actsAs,
    site,
    values = NO_VALUES,
    prepare,
    observe,
}: {
    scene: ConnectionsScene;
    actsAs: 'owner' | 'key';
    site: string;
    values?: ConnectionsContextValue;
    prepare?: ConnectionsLabProps['prepare'];
    observe?: Observe;
}) {
    const [ready, setReady] = useState(false);
    const phone = useIsMobile();
    useEffect(() => {
        const undo = prepare?.(scene);
        setReady(true);
        return undo;
    }, [prepare, scene]);
    useSteps(ready ? scene.steps : undefined, 'connections-lab', phone);
    // No retries, so a refused check fails at once.
    const client = useMemo(() => workFixtureClient(worldFetch(scene.world, { actsAs, observe }), { maxRetries: 0 }), [scene, actsAs, observe]);
    const scope = useMemo<ConsoleContextValue>(
        () => ({ client, actsAs, basePath: '/developers', apiUrl: 'https://api.noclick.com', site, home: '/', user: { id: '', email: 'maya@northwind.test' }, now: Date.now, lab: true, signOut: () => undefined, live: null }),
        [client, actsAs, site]
    );
    const context = useMemo<ConnectionsContextValue>(() => ({ ...values, teamWorkspace: teamOf(scene.world) }), [values, scene]);
    if (!ready) return null;
    const page = (
        <div className="relative min-h-0 flex-1">
            <ConsoleScope value={scope}>
                <ConnectionsContext.Provider value={context}>
                    <ConnectionsView />
                </ConnectionsContext.Provider>
            </ConsoleScope>
        </div>
    );
    return <div className="fixed inset-0 flex flex-col bg-background text-foreground">{phone ? <LabPhoneBar title="Connections">{page}</LabPhoneBar> : page}</div>;
}
