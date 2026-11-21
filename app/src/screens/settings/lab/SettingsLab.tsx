// Settings over made-up data: the real page (its frame and the app's own sections: Usage, Plan and billing,
// Notifications, Developer) against their reads on the platform's API, answered through the client the page reads with
// (world.ts), so every scene opens with no account and no network. `?scene=` picks a scene (scenes.ts; with none, the
// index lists them), with the section it opens on as `section` beside it, and `?as=key` answers as the API answers one
// of the account's keys (as `/settings` is served; the default shows what a signed-in owner sees). A host's own lab
// draws its Settings in the same frame (`LabIndex`, `LabPage`). A window narrower than a laptop's draws it as the phone
// shell does, under a stand-in for its top bar. Dates read against the browser's clock: for two screenshots to match,
// fix the clock at world.ts's CLOCK and the zone at UTC before the page loads.
import { useMemo, type ReactNode } from 'react';
import { Link, useSearchParams } from 'react-router';
import { DEFAULT_BASE_URL } from 'noclick';
import type { WorkLive } from '@/sdk/live';
import { liveFromWatch, sdkLive } from '@/sdk/watchLive';
import type { ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { NOCLICK_SITE } from '@/screens/console/lib/site';
import { LabPhoneBar } from '@/ui/lab/LabPhoneBar';
import { useSteps } from '@/ui/lab/steps';
import { useIsMobile } from '@/ui/useIsMobile';
import { AppSettings, SettingsScope } from '../SettingsPage';
import { SCENES, sceneSearch, type SettingsScene } from './scenes';
import { ACCOUNT_ID, CLOCK, OWNER_EMAIL, settingsClient, type ActsAs, type Observe } from './world';

export default function SettingsLab({ basePath }: { basePath: string }) {
    const [params] = useSearchParams();
    const scene = SCENES.find((s) => s.id === params.get('scene'));
    const actsAs: ActsAs = params.get('as') === 'key' ? 'key' : 'owner';
    if (!scene) return <LabIndex basePath={basePath} scenes={SCENES} />;
    return <SceneView key={`${scene.id}:${actsAs}`} scene={scene} actsAs={actsAs} />;
}

/** Every scene, grouped, each a link to its view. */
export function LabIndex({ basePath, scenes }: { basePath: string; scenes: readonly { id: string; title: string; group: string; section?: string }[] }) {
    const groups = [...new Set(scenes.map((s) => s.group))];
    return (
        <div className="min-h-screen bg-background text-foreground">
            <div className="mx-auto max-w-[720px] space-y-8 px-8 py-10">
                <header>
                    <h1 className="text-[22px] font-semibold">Settings lab</h1>
                    <p className="mt-1 text-[14px] text-muted-foreground">Settings over a made-up account, with no account, network or backend. Narrow the window past a laptop’s for the phone’s.</p>
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

/** A scene's page, as a host frames Settings: the window, and on a phone a stand-in for the phone shell's bar.
 *  `data-lab-settings` lets the shots find the column that scrolls. */
export function LabPage({ phone, children }: { phone: boolean; children: ReactNode }) {
    const page = (
        <div className="relative min-h-0 flex-1" data-lab-settings>
            {children}
        </div>
    );
    return <div className="fixed inset-0 flex flex-col bg-background text-foreground">{phone ? <LabPhoneBar title="Settings">{page}</LabPhoneBar> : page}</div>;
}

/** One scene, as `/settings` draws it acting as `actsAs`, over a client of its own (so nothing is kept from another
 *  scene's read), then its clicks made. `observe` hears every call the page makes. */
export function SceneView({ scene, actsAs = 'owner', observe }: { scene: SettingsScene; actsAs?: ActsAs; observe?: Observe }) {
    const phone = useIsMobile();
    const client = useMemo(() => settingsClient(scene.world, observe, actsAs), [scene, observe, actsAs]);
    // The account's change stream, as `/settings` follows it: refused here, as where the API doesn't serve it.
    const live = useMemo(() => liveFromWatch(sdkLive(client), { backstopMs: null }), [client]);
    const value = useMemo<ConsoleContextValue & { live: WorkLive }>(
        () => ({
            client,
            actsAs,
            basePath: '/developers',
            apiUrl: DEFAULT_BASE_URL,
            site: NOCLICK_SITE,
            home: '/',
            user: { id: ACCOUNT_ID, email: actsAs === 'owner' ? OWNER_EMAIL : null },
            now: () => Date.parse(CLOCK),
            lab: true,
            signOut: () => undefined,
            live,
        }),
        [client, actsAs, live]
    );
    useSteps(scene.steps, 'settings-lab', phone);
    return (
        <LabPage phone={phone}>
            <SettingsScope value={value}>
                <AppSettings />
            </SettingsScope>
        </LabPage>
    );
}
