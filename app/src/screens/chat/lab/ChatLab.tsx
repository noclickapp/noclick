// The Chat page over fixtures: the real page and the real chat (NoClick's one session on /v1, its cards, the Beside, the
// switchers under the box, the Connect menu, the "+" menu, the memories) against the chat's fake /v1 (worlds.ts), so
// every scene opens with no account and no network. `?scene=` picks one (scenes.ts; with none, the index lists them),
// `?as=key` answers as the API answers one of the account's keys rather than its signed-in owner. A window narrower
// than a laptop's draws it as the phone shell does, under a stand-in for its top bar. Times read against the browser's
// clock: for two screenshots to match, fix the clock before the page loads (the scenes are set at threads.ts's CLOCK).
// A host that reaches the network its own way besides the platform client (its own socket, its own fetches) answers
// those from the scene with `prepare`, and may add scenes of its own (`more`).
import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { ConsoleScope } from '@/screens/console/ConsoleProviders';
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import { LabPhoneBar } from '@/ui/lab/LabPhoneBar';
import { useSteps } from '@/ui/lab/steps';
import { useIsMobile } from '@/ui/useIsMobile';
import { ChatPage } from '../ChatPage';
import { ChatContext, type ChatContextValue } from '../context';
import { CoordinatorChat } from '../CoordinatorChat';
import type { ReferenceDisplay } from '../thread';
import { SCENES, sceneSearch, type ChatScene } from './scenes';
import { chatWorld, type Observe } from './worlds';

/** The signed-in owner the fixtures name. */
const OWNER_EMAIL = 'maya@morrowbakery.test';
const NO_VALUES: ChatContextValue = {};

export interface ChatLabProps {
    /** Where the lab is mounted, without a trailing slash. */
    basePath: string;
    /** NoClick's own site, for the links the chat builds to it: empty where the lab is served from it. */
    site?: string;
    /** What a host hands the chat besides its client. */
    values?: ChatContextValue;
    /** How the host names what a message points at. */
    useReferenceDisplay?: () => ReferenceDisplay;
    /** Answers what the host reaches outside the platform client from the scene's `fetch`, before the chat reads
     *  anything; returns how to stop. */
    prepare?: (fetch: typeof window.fetch, scene: ChatScene) => () => void;
    /** The host's own scenes, after the lab's. */
    more?: readonly ChatScene[];
}

export default function ChatLab({ basePath, site = NOCLICK_SITE, values = NO_VALUES, useReferenceDisplay, prepare, more = [] }: ChatLabProps) {
    const [params] = useSearchParams();
    const scenes = useMemo(() => [...SCENES, ...more], [more]);
    const scene = scenes.find((s) => s.id === params.get('scene'));
    const actsAs = params.get('as') === 'key' ? 'key' : 'owner';
    if (!scene) return <LabIndex basePath={basePath} scenes={scenes} />;
    return <SceneView key={`${scene.id}:${actsAs}`} scene={scene} actsAs={actsAs} site={site} values={values} useReferenceDisplay={useReferenceDisplay} prepare={prepare} />;
}

/** Every scene, grouped, each a link to its view. */
function LabIndex({ basePath, scenes }: { basePath: string; scenes: readonly ChatScene[] }) {
    const groups = [...new Set(scenes.map((s) => s.group))];
    return (
        <div className="min-h-screen bg-background text-foreground">
            <div className="mx-auto max-w-[720px] space-y-8 px-8 py-10">
                <header>
                    <h1 className="text-[22px] font-semibold">Chat lab</h1>
                    <p className="mt-1 text-[14px] text-muted-foreground">The Chat page over made-up data, with no account, network or socket. Narrow the window past a laptop’s for the phone’s.</p>
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

const ownWords: () => ReferenceDisplay = () => () => undefined;

/** One scene: its world made once, what the host prepares in place before the chat reads anything, and its clicks
 *  made; `observe` is told of every call its views make (a test's record). */
export function SceneView({
    scene,
    actsAs,
    site,
    values = NO_VALUES,
    useReferenceDisplay = ownWords,
    prepare,
    observe,
}: {
    scene: ChatScene;
    actsAs: 'owner' | 'key';
    site: string;
    values?: ChatContextValue;
    useReferenceDisplay?: () => ReferenceDisplay;
    prepare?: ChatLabProps['prepare'];
    observe?: Observe;
}) {
    const [lab] = useState(() => chatWorld(scene.world, actsAs, observe));
    const [ready, setReady] = useState(false);
    const phone = useIsMobile();
    useEffect(() => {
        const undo = prepare?.(lab.fetch, scene);
        setReady(true);
        return undo;
    }, [lab, prepare, scene]);
    useSteps(ready ? scene.steps : undefined, 'chat-lab', phone);
    const scope = useMemo<ConsoleContextValue>(
        () => ({
            client: lab.client,
            actsAs,
            basePath: '/developers',
            apiUrl: 'https://api.noclick.com',
            site,
            home: '/',
            user: { id: '', email: OWNER_EMAIL },
            now: Date.now,
            lab: true,
            signOut: () => undefined,
            live: lab.live,
        }),
        [lab, actsAs, site]
    );
    if (!ready) return null;
    const chat = (
        <div className="relative min-h-0 flex-1">
            <ConsoleScope value={scope}>
                <ChatContext.Provider value={values}>
                    <SceneChat lab={lab} useReferenceDisplay={useReferenceDisplay} />
                </ChatContext.Provider>
            </ConsoleScope>
        </div>
    );
    return <div className="fixed inset-0 flex flex-col bg-background text-foreground">{phone ? <LabPhoneBar title="Chat">{chat}</LabPhoneBar> : chat}</div>;
}

/** The chat over the scene's world, drawn once what the host prepares is in place: what names a message's chips may
 *  read what the host answers. */
function SceneChat({ lab, useReferenceDisplay }: { lab: ReturnType<typeof chatWorld>; useReferenceDisplay: () => ReferenceDisplay }) {
    const referenceDisplay = useReferenceDisplay();
    return (
        <CoordinatorChat client={lab.client} live={lab.live} referenceDisplay={referenceDisplay}>
            <ChatPage />
        </CoordinatorChat>
    );
}
