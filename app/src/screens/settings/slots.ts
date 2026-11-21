// Settings' slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise. Every
// section's body is one. Where the app has a section of its own, it stands there (Usage, Workstreams, Plan and billing,
// Notifications, Developer), so a host fills one only to draw its own. A section whose body is only the deployment's
// (its people, linking a phone, the builder's skills, its own popups) has nobody standing there, and Settings then
// doesn't list it. So is what a deployment kept of the keys made before its developer console.
import { useMemo, type ComponentType } from 'react';
import { slot, useSlot } from '@/slots';
import { UsagePage } from '@/screens/usage/UsagePage';
import { BillingStandard } from './billing';
import { DeveloperSection } from './developer';
import { NotificationsSection } from './notifications';
import type { SettingsSectionId } from './sections';
import { WorkstreamsSection } from './workstreams';

/** A section's body, drawn when the section is open: a component, or null where there's none. */
export type SectionBody = ComponentType | null;

/** Usage: what each thing cost, as it was used. The standard is the app's Usage page, read with the client and live
 *  frames the page is drawn under. */
export const USAGE = slot<SectionBody>('settings.usage', UsagePage);

/** Workstreams: the lines of work the account's spend is counted under, renamed and archived. The standard reads and
 *  changes them with the client and live frames the page is drawn under. */
export const WORKSTREAMS = slot<SectionBody>('settings.workstreams', WorkstreamsSection);

/** Plan and billing: the plan, how money is added and how much may be spent. The standard shows the plan and the
 *  balance as the account reads them, with NoClick's pages for changing them, and the monthly spending cap. */
export const BILLING = slot<SectionBody>('settings.billing', BillingStandard);

/** Notifications: the email alerts sent to the account's owner. The standard reads and switches them with the client
 *  and live frames the page is drawn under. */
export const NOTIFICATIONS = slot<SectionBody>('settings.notifications', NotificationsSection);

/** Developer: the way into the developer console. The standard opens it at the address of the console context the
 *  page is drawn in. */
export const DEVELOPER = slot<SectionBody>('settings.developer', DeveloperSection);

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

/** Each section's body as it stands, and the sections with none (no host filled a section that is only a
 *  deployment's), which Settings leaves out. */
export function useSectionBodies(): { bodies: Partial<Record<SettingsSectionId, ComponentType>>; unfilled: readonly SettingsSectionId[] } {
    const usage = useSlot(USAGE);
    const workstreams = useSlot(WORKSTREAMS);
    const billing = useSlot(BILLING);
    const organization = useSlot(MEMBERS);
    const skills = useSlot(SKILLS);
    const notifications = useSlot(NOTIFICATIONS);
    const phone = useSlot(PHONE);
    const popups = useSlot(POPUPS);
    const developer = useSlot(DEVELOPER);
    return useMemo(() => {
        const all: [SettingsSectionId, SectionBody][] = [
            ['usage', usage],
            ['workstreams', workstreams],
            ['billing', billing],
            ['organization', organization],
            ['skills', skills],
            ['notifications', notifications],
            ['phone', phone],
            ['popups', popups],
            ['developer', developer],
        ];
        const bodies: Partial<Record<SettingsSectionId, ComponentType>> = {};
        for (const [id, body] of all) if (body) bodies[id] = body;
        return { bodies, unfilled: all.filter(([, body]) => !body).map(([id]) => id) };
    }, [usage, workstreams, billing, organization, skills, notifications, phone, popups, developer]);
}
