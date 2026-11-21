// Settings: one page, its sections listed in groups in a column of their own beside the open one on a laptop, and on a
// phone a list a section opens over (SettingsFrame). Each section's body is a slot (slots.ts): the app's own where it
// has one (Usage, Plan and billing, Notifications, Developer), and a host's for what only a deployment has; a section
// nobody draws isn't listed. Whoever draws the page says what it knows of the account (`SectionContext`) and where the
// open section lives (`SettingsAddress`): `/settings` keeps it in the address's `?section=` (`useSettingsAddress`). The
// app's sections read with the client and live frames `SettingsScope` hands them, acting as whoever the console context
// says (screens/console/ownerOnly.ts: one of the account's keys leaves out what only the owner may do).
import { useMemo, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { getAccount } from '@/sdk/owner';
import { WorkLiveContext, type WorkLive } from '@/sdk/live';
import { useV1 } from '@/sdk/useV1';
import { ConsoleScope } from '@/screens/console/ConsoleProviders';
import { AccountContext, type ConsoleContextValue } from '@/screens/console/hooks/useConsole';
import { TooltipProvider } from '@/ui/tooltip';
import { groupSections, visibleSections, type SectionContext, type SettingsSectionId } from './sections';
import { SettingsFrame } from './SettingsFrame';
import { useSectionBodies } from './slots';

/** Where Settings' open section lives, as its host keeps it. */
export interface SettingsAddress {
    /** The section open on a laptop (one this page doesn't show draws nothing). */
    active: string;
    select: (id: SettingsSectionId) => void;
    /** The section the address names, which a phone opens over the list; none, or one not shown here, is the list. */
    named: string | null;
    /** A phone's way back to the list. */
    closePhone: () => void;
}

/** What the app knows of the account it acts in: no organization, no members to show, no phone linking (each a
 *  deployment's own). */
export const APP_CONTEXT: SectionContext = { inOrganization: false, hasMembers: false, phoneLinking: false };

const NONE: readonly string[] = [];

/** The open section in the address's `?section=`, Usage when it names none of this page's. */
export function useSettingsAddress(sections: readonly SettingsSectionId[]): SettingsAddress {
    const [params, setParams] = useSearchParams();
    const named = params.get('section');
    const active = sections.find((id) => id === named) ?? 'usage';
    return useMemo(
        () => ({
            active,
            named,
            select: (id) =>
                setParams(
                    (prev) => {
                        const next = new URLSearchParams(prev);
                        next.set('section', id);
                        return next;
                    },
                    { replace: true }
                ),
            closePhone: () =>
                setParams(
                    (prev) => {
                        const next = new URLSearchParams(prev);
                        next.delete('section');
                        return next;
                    },
                    { replace: true }
                ),
        }),
        [active, named, setParams]
    );
}

/** The sections this page shows in `context`, less the `hidden` ones its host draws as pages of their own and those no
 *  one draws. */
export function useShownSections(context: SectionContext, hidden: readonly string[] = NONE) {
    const { bodies, unfilled } = useSectionBodies();
    const left = useMemo(() => [...hidden, ...unfilled], [hidden, unfilled]);
    const sections = useMemo(() => visibleSections(context, left), [context, left]);
    return { sections, bodies };
}

export function SettingsView({
    context,
    hidden = NONE,
    address,
    shortcutFor,
}: {
    context: SectionContext;
    /** Sections the host draws as pages of their own, left out of the list. */
    hidden?: readonly string[];
    address: SettingsAddress;
    /** The keys that open a section, shown beside it in the laptop's column. */
    shortcutFor?: (id: SettingsSectionId) => string[] | undefined;
}) {
    const { sections, bodies } = useShownSections(context, hidden);
    const phoneSection = sections.find((item) => item.id === address.named)?.id ?? null;
    const renderSection = (id: string) => {
        const Body = bodies[id as SettingsSectionId];
        return Body ? <Body /> : null;
    };
    return (
        <SettingsFrame
            groups={groupSections(sections)}
            active={address.active}
            phoneSection={phoneSection}
            onSelect={address.select}
            onClosePhone={address.closePhone}
            renderSection={renderSection}
            shortcutFor={shortcutFor}
        />
    );
}

/** What the app's own sections read under where the app draws Settings: the console's context `value` (its client, who
 *  it acts as, NoClick's site, the console's address), the account it acts in, read once and again on focus, and the
 *  account's live frames. */
export function SettingsScope({ value, children }: { value: ConsoleContextValue & { live: WorkLive }; children: ReactNode }) {
    const account = useV1('account', (signal) => getAccount(value.client, signal), { client: value.client });
    return (
        <ConsoleScope value={value}>
            <AccountContext.Provider value={account}>
                <WorkLiveContext.Provider value={value.live}>
                    <TooltipProvider delayDuration={300}>{children}</TooltipProvider>
                </WorkLiveContext.Provider>
            </AccountContext.Provider>
        </ConsoleScope>
    );
}

/** Settings as the app draws it at `/settings`: its own sections, the address's `?section=`. */
export function AppSettings() {
    const { sections } = useShownSections(APP_CONTEXT);
    const address = useSettingsAddress(useMemo(() => sections.map((s) => s.id), [sections]));
    return <SettingsView context={APP_CONTEXT} address={address} />;
}
