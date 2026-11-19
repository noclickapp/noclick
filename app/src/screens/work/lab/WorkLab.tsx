// Work over fixtures: the real page and its real views against Work's fake /v1 (worlds.ts), so every view opens with
// no account and no network. `?scene=` picks a view (scenes.ts; with none, the index lists them), `?as=key` answers
// as the API answers one of the account's keys rather than its signed-in owner, and the rest of the address is Work's
// own place, which moves as you click around. A window narrower than a laptop's draws it as the phone shell does,
// under a stand-in for its top bar. Times read against the browser's clock: for two screenshots to match, fix the
// clock before the page loads. A host that reaches the network its own way besides the platform client (its own
// socket, its own fetches) answers those from the scene's fixtures with `prepare`.
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import type { AccountMenuUser } from '@/ui/accountParts';
import { useIsMobile } from '@/ui/useIsMobile';
import { ConsoleScope } from '@/screens/console/ConsoleProviders';
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import { WorkScreen } from '../WorkScreen';
import type { WorkContextValue } from '../context';
import { LabPhoneBar } from '@/ui/lab/LabPhoneBar';
import { useSteps } from '@/ui/lab/steps';
import { SCENES, sceneSearch, type LabScene } from './scenes';
import { answerSessions } from './sessions';
import { labWorld, type Observe } from './worlds';

/** Who is signed in, as the fixtures name the account's owner. */
const USER: AccountMenuUser = { email: 'rowan@example.com', display_name: 'Rowan Hale' };

export interface WorkLabProps {
    /** Where the lab is mounted, without a trailing slash. */
    basePath: string;
    /** NoClick's own site, for the links Work builds to it: empty where the lab is served from it. */
    site?: string;
    /** What a host hands Work besides its client (WorkContext). */
    work?: WorkContextValue;
    /** Answers what the host reaches outside the platform client from the scene's `fetch`, before Work reads anything;
     *  returns how to stop. By default, a joined space's session client's calls (sessions.ts). */
    prepare?: (fetch: typeof window.fetch) => () => void;
}

export default function WorkLab({ basePath, site = NOCLICK_SITE, work, prepare = answerSessions }: WorkLabProps) {
    const [params] = useSearchParams();
    const scene = SCENES.find((s) => s.id === params.get('scene'));
    const actsAs = params.get('as') === 'key' ? 'key' : 'owner';
    if (!scene) return <LabIndex basePath={basePath} />;
    return <SceneView key={`${scene.id}:${actsAs}`} scene={scene} actsAs={actsAs} site={site} work={work} prepare={prepare} />;
}

/** Every scene, grouped, each a link to its view. */
function LabIndex({ basePath }: { basePath: string }) {
    const groups = [...new Set(SCENES.map((s) => s.group))];
    return (
        <div className="min-h-screen bg-background text-foreground">
            <div className="mx-auto max-w-[720px] space-y-8 px-8 py-10">
                <header>
                    <h1 className="text-[22px] font-semibold">Work lab</h1>
                    <p className="mt-1 text-[14px] text-muted-foreground">Every view of Work over made-up data, with no account, network or socket. Narrow the window past a laptop’s for the phone’s.</p>
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

/** One scene: its world made once, what the host prepares in place before Work reads anything, and its clicks made;
 *  `observe` is told of every call its views make (a test's record). */
export function SceneView({ scene, actsAs, site, work: values, prepare, observe }: { scene: LabScene; actsAs: 'owner' | 'key'; site: string; work?: WorkContextValue; prepare?: WorkLabProps['prepare']; observe?: Observe }) {
    const [lab] = useState(() => labWorld(scene.world, actsAs, observe));
    const [ready, setReady] = useState(false);
    const phone = useIsMobile();
    useEffect(() => {
        const undo = prepare?.(lab.fetch);
        setReady(true);
        return undo;
    }, [lab, prepare]);
    useSteps(ready ? scene.steps : undefined, 'work-lab');
    const scope = useMemo<ConsoleContextValue>(
        () => ({
            client: lab.client,
            actsAs,
            basePath: '/developers',
            apiUrl: 'https://api.noclick.com',
            site,
            home: '/',
            user: { id: '', email: USER.email },
            now: Date.now,
            lab: true,
            signOut: () => undefined,
            live: lab.live,
        }),
        [lab, actsAs, site]
    );
    if (!ready) return null;
    const work = (
        <ConsoleScope value={scope}>
            <WorkScreen client={lab.client} live={lab.live} keptAs={null} user={USER} work={values} />
        </ConsoleScope>
    );
    return <div className="fixed inset-0 flex flex-col bg-background text-foreground">{phone ? <LabPhoneBar title="Work">{work}</LabPhoneBar> : work}</div>;
}
