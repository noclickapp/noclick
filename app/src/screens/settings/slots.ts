// Settings' slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise. A section
// whose body is the deployment's (its plan and billing, its people, linking a phone, the builder's skills, its own
// popups) is a slot a host fills; nobody stands there by default, and Settings then doesn't list the section. So is
// what a deployment kept of the keys made before its developer console.
import { useMemo, type ComponentType } from 'react';
import { slot, useSlot } from '@/slots';
import type { SettingsSectionId } from './sections';

/** A section's body, drawn when the section is open: a host's component, or null where it has none. */
export type SectionBody = ComponentType | null;

/** Plan and billing: the plan, how money is added and how much may be spent. */
export const BILLING = slot<SectionBody>('settings.billing', null);

/** Members: who's in the workspace, inviting more, how they sign in. */
export const MEMBERS = slot<SectionBody>('settings.members', null);

/** Phone: the numbers a person messages and calls from, proven theirs. */
export const PHONE = slot<SectionBody>('settings.phone', null);

/** Skills: the reusable context the deployment's builder loads. */
export const SKILLS = slot<SectionBody>('settings.skills', null);

/** Popups: which of the deployment's own popups and banners appear. */
export const POPUPS = slot<SectionBody>('settings.popups', null);

/** Under the developer console's row in Developer: keys made before the console, which still work. Nothing stands
 *  there. */
export const OLDER_KEYS = slot<ComponentType | null>('settings.developer.olderKeys', null);

/** The sections a host draws, and the ones it doesn't (no host filled their slot), which Settings leaves out. */
export function useHostSections(): { bodies: Partial<Record<SettingsSectionId, ComponentType>>; unfilled: readonly SettingsSectionId[] } {
    const billing = useSlot(BILLING);
    const organization = useSlot(MEMBERS);
    const phone = useSlot(PHONE);
    const skills = useSlot(SKILLS);
    const popups = useSlot(POPUPS);
    return useMemo(() => {
        const all: [SettingsSectionId, SectionBody][] = [
            ['billing', billing],
            ['organization', organization],
            ['phone', phone],
            ['skills', skills],
            ['popups', popups],
        ];
        const bodies: Partial<Record<SettingsSectionId, ComponentType>> = {};
        for (const [id, body] of all) if (body) bodies[id] = body;
        return { bodies, unfilled: all.filter(([, body]) => !body).map(([id]) => id) };
    }, [billing, organization, phone, skills, popups]);
}
