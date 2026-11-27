// Settings' slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise. Every
// section's body is one. Where the app has a section of its own, it stands there (Usage, Workstreams, Plan and billing,
// Notifications, Phone, Popups, Skills, Developer), so a host fills one only to draw its own. A section whose body is
// only the deployment's (its people) has nobody standing there, and Settings then doesn't list it. So is what a
// deployment kept of the keys made before its developer console. Skills has two more: the editor a skill opens in, and
// a way to share one.
import { useMemo, type ComponentType } from 'react';
import { slot, useSlot } from '@/slots';
import { UsagePage } from '@/screens/usage/UsagePage';
import { BillingStandard } from './billing';
import { DeveloperSection } from './developer';
import { NotificationsSection } from './notifications';
import { PhoneSection } from './phone';
import { PopupsSection } from './popups';
import { SkillWordsEditor } from './skillEditor';
import { SkillsSection, type SkillEditorProps, type SkillShareProps } from './skills';
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

/** In Notifications, notifications on this device: a host whose app sends them to browsers (Web Push) draws turning
 *  them on and off. Nobody stands there. */
export const NOTIFICATIONS_DEVICE = slot<SectionBody>('settings.notifications.device', null);

/** Developer: the way into the developer console. The standard opens it at the address of the console context the
 *  page is drawn in. */
export const DEVELOPER = slot<SectionBody>('settings.developer', DeveloperSection);

/** Members: who's in the workspace, inviting more, how they sign in. */
export const MEMBERS = slot<SectionBody>('settings.members', null);

/** Phone: the numbers the account's owner messages and calls NoClick from, proven theirs. The standard reads, links
 *  and unlinks them with the client and live frames the page is drawn under (the owner's, or a key's that names
 *  `account:phones`: Settings lists it only where the page may). */
export const PHONE = slot<SectionBody>('settings.phone', PhoneSection);

/** Skills: the skills NoClick's builder loads for the account. The standard lists, makes, switches and deletes them
 *  with the client the page is drawn under. */
export const SKILLS = slot<SectionBody>('settings.skills', SkillsSection);

/** In Skills, the editor a skill opens in, in place of the list. The standard edits its words (name, description,
 *  text); a host with a workflow canvas draws the skill's workflow too. */
export const SKILL_EDITOR = slot<ComponentType<SkillEditorProps>>('settings.skills.editor', SkillWordsEditor);

/** In Skills, a way to share one of the account's skills with people. Nobody stands there, and no row offers it. */
export const SKILL_SHARE = slot<ComponentType<SkillShareProps> | null>('settings.skills.share', null);

/** Popups: which of the app's popups and banners appear. The standard reads and switches them with the client and
 *  live frames the page is drawn under. */
export const POPUPS = slot<SectionBody>('settings.popups', PopupsSection);

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
