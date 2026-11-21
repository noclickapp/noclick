// The Settings lab's scenes: the page over a world each (world.ts), opened on a section (none: Settings as it opens,
// Usage on a laptop and the list on a phone), and for what no address opens (the cap being changed) the clicks that
// open it. The same list draws the lab's index, is what a screenshot of every scene walks, and is what
// settingsAsKey.test.tsx opens as the owner and as a key.
import type { LabStep } from '@/ui/lab/steps';
import type { SettingsSectionId } from '../sections';
import type { SettingsApiWorld } from './world';

export interface SettingsScene {
    id: string;
    title: string;
    group: string;
    world: SettingsApiWorld;
    /** The section the address opens; none is Settings as it opens. */
    section?: SettingsSectionId;
    steps?: LabStep[];
}

/** A Member with a cap, partway through the period. */
const MEMBER: SettingsApiWorld = { tier: 'member', balanceUsd: 42.5, capUsd: 50, spentUsd: 12.4 };

export const SCENES: readonly SettingsScene[] = [
    { id: 'settings', title: 'As it opens: Usage beside the sections, and a phone’s list', group: 'Settings', world: MEMBER },

    { id: 'notifications', title: 'Each alert with its switch, some off', group: 'Notifications', world: { ...MEMBER, prefs: 'some-off' }, section: 'notifications' },
    { id: 'notifications-loading', title: 'While they’re read', group: 'Notifications', world: { ...MEMBER, prefs: 'waiting' }, section: 'notifications' },

    { id: 'billing', title: 'The plan, the balance, and a cap with what’s spent', group: 'Plan and billing', world: MEMBER, section: 'billing' },
    { id: 'billing-no-cap', title: 'New on Free: no cap yet', group: 'Plan and billing', world: { tier: 'free', balanceUsd: 0, capUsd: null, spentUsd: 3.21 }, section: 'billing' },
    { id: 'billing-cap-reached', title: 'At the cap', group: 'Plan and billing', world: { tier: 'member', balanceUsd: 0, capUsd: 20, spentUsd: 20.37 }, section: 'billing' },
    { id: 'billing-change-cap', title: 'Changing the cap', group: 'Plan and billing', world: MEMBER, section: 'billing', steps: [{ button: 'Change' }] },

    { id: 'developer', title: 'The console’s way in', group: 'Developer', world: MEMBER, section: 'developer' },
];

/** The address a scene opens at: its id, and the section it opens on. */
export function sceneSearch(scene: { id: string; section?: string }): string {
    const params = new URLSearchParams({ scene: scene.id });
    if (scene.section) params.set('section', scene.section);
    return `?${params}`;
}
