// Settings' frame: its sections listed in groups in a column of their own beside the open one on a laptop (rows like
// the app sidebar's). On a phone the list is the page and a section opens over it, the shell's bar going back; outside
// the phone shell the page draws its own title and its own way back. What the frame draws is all it's told: the
// groups, which section is open, and how to draw one.
import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import { cn } from '@/ui/utils';
import { HAIRLINE } from '@/ui/primitives';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { useIsMobile } from '@/ui/useIsMobile';
import { PhoneBarBack, useInPhoneShell } from '@/ui/phoneBar';
import { SidebarItem, TAP_ROW } from '@/ui/sidebarParts';
import { DISPLAY, PAGE_TITLE } from '@/ui/titles';
import type { SectionGroup, SettingsSectionId } from './sections';

/** Whether Settings is drawn for a phone: in the phone shell, or a window narrower than a small tablet. */
export function useSettingsOnPhone(): { inPhone: boolean; onPhone: boolean } {
    const inPhone = useInPhoneShell();
    const narrow = useIsMobile(640);
    return { inPhone, onPhone: inPhone || narrow };
}

export function SettingsFrame<Id extends string>({
    groups,
    active,
    phoneSection,
    onSelect,
    onClosePhone,
    renderSection,
    shortcutFor,
}: {
    groups: readonly SectionGroup[];
    /** The open section on a laptop. */
    active: Id;
    /** The open section on a phone; none is the list. */
    phoneSection: Id | null;
    onSelect: (id: SettingsSectionId) => void;
    /** A phone's way back to the list. */
    onClosePhone: () => void;
    renderSection: (id: Id) => ReactNode;
    /** The keys that open a section, shown beside it in the laptop's column. */
    shortcutFor?: (id: SettingsSectionId) => string[] | undefined;
}) {
    const { inPhone, onPhone } = useSettingsOnPhone();

    // ── Phone: the sections as one list ───────────────────────────────────────
    if (onPhone && phoneSection === null) {
        return (
            <div className="h-full overflow-y-auto scrollbar-subtle">
                <div className="mx-auto w-full max-w-[640px] px-4 pb-24 pt-3">
                    {!inPhone && <h1 className={cn('mb-5', PAGE_TITLE, 'text-[30px]')}>Settings</h1>}
                    <div className="space-y-6">
                        {groups.map((group) => (
                            <section key={group.label}>
                                <h2 className="mb-2 px-1 text-[12.5px] font-medium text-muted-foreground">{group.label}</h2>
                                <div className={cn('divide-y overflow-hidden rounded-2xl border bg-card dark:divide-foreground/[0.06] dark:bg-transparent', HAIRLINE)}>
                                    {group.items.map((item) => {
                                        const Icon = item.icon;
                                        return (
                                            <button
                                                key={item.id}
                                                type="button"
                                                onClick={() => onSelect(item.id)}
                                                className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-colors [@media(hover:hover)]:hover:bg-foreground/[0.03] focus-visible:bg-foreground/[0.03] focus-visible:outline-none ${TAP_ROW}`}
                                            >
                                                <Icon className="h-5 w-5 shrink-0 text-foreground/75" strokeWidth={1.6} />
                                                <span className="min-w-0 flex-1">
                                                    <span className="block text-[15px] text-foreground">{item.label}</span>
                                                    {/* Whole, on as many lines as it takes: a phone has no tooltip to say the rest. */}
                                                    <span className="mt-0.5 block text-[13px] leading-snug text-muted-foreground">{item.description}</span>
                                                </span>
                                                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60" />
                                            </button>
                                        );
                                    })}
                                </div>
                            </section>
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    // ── Phone: one section, the bar going back to the list ─────────────────────
    if (onPhone && phoneSection !== null) {
        return (
            <div className="h-full overflow-y-auto scrollbar-subtle">
                <PhoneBarBack label="Settings" onBack={onClosePhone} />
                <div className="px-4 pb-24 pt-3">
                    {!inPhone && (
                        <button
                            type="button"
                            onClick={onClosePhone}
                            className="-ml-1 mb-4 inline-flex items-center gap-0.5 rounded-md px-1 py-0.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
                        >
                            <ChevronRight className="h-3.5 w-3.5 rotate-180" />
                            Settings
                        </button>
                    )}
                    {renderSection(phoneSection)}
                </div>
            </div>
        );
    }

    // ── Laptop: the sections in their column beside the open one ─────────────
    return (
        <div className="flex h-full">
            <nav aria-label="Settings" className={cn('flex w-[248px] shrink-0 flex-col border-r', HAIRLINE)}>
                <div className="flex h-14 shrink-0 items-center px-5">
                    <h1 className={cn(DISPLAY, 'text-[26px] leading-none text-foreground')}>Settings</h1>
                </div>
                <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-2 pb-8 pt-1 scrollbar-subtle">
                    {groups.map((group) => (
                        <div key={group.label}>
                            <p className="px-3 pb-1.5 text-[12.5px] font-medium text-muted-foreground">{group.label}</p>
                            <div className="flex flex-col gap-0.5">
                                {group.items.map((item) => (
                                    <ShortcutTooltip key={item.id} keys={shortcutFor?.(item.id)} side="right">
                                        <div>
                                            <SidebarItem label={item.label} icon={item.icon} current={active === item.id} collapsed={false} onSelect={() => onSelect(item.id)} />
                                        </div>
                                    </ShortcutTooltip>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            </nav>

            <div className="min-w-0 flex-1 overflow-y-auto scrollbar-subtle">
                <div className="mx-auto w-full max-w-[880px] px-10 pb-24 pt-10">{renderSection(active)}</div>
            </div>
        </div>
    );
}
