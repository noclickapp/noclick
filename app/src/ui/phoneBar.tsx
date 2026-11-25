// The phone shell's top bar as the pages under it see it: whether they're in it,
// and where they put their actions and their way back. AppShell provides it;
// these read no app state, so any page can import them.
import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft } from 'lucide-react';
import { SIDEBAR_ICON_BUTTON } from '@/ui/sidebarParts';

interface PhoneBar {
    /** Where the top bar takes a page's actions. */
    slot: HTMLElement | null;
    /** Where a page one level down puts its way back, in place of the menu and the page's name. */
    lead: HTMLElement | null;
    setLeadTaken: (taken: boolean) => void;
}

export const PhoneBarContext = createContext<PhoneBar | null>(null);

/** True inside the phone shell, whose top bar already names the page. */
export function useInPhoneShell(): boolean {
    return useContext(PhoneBarContext) !== null;
}

/** Hands what's under it a phone bar's slots, the way the phone shell does (a design lab): `slot` for its actions,
 *  `lead` for its way back (with `setLeadTaken` telling the bar it's in use). */
export function PhoneBarSlotProvider({ slot, lead, setLeadTaken, children }: PhoneBar & { children: ReactNode }) {
    const bar = useMemo(() => ({ slot, lead, setLeadTaken }), [slot, lead, setLeadTaken]);
    return <PhoneBarContext.Provider value={bar}>{children}</PhoneBarContext.Provider>;
}

/** A page's actions, moved into the phone's top bar; nothing on a laptop. */
export function PhoneBarActions({ children }: { children: ReactNode }) {
    const bar = useContext(PhoneBarContext);
    return bar?.slot ? createPortal(children, bar.slot) : null;
}

/**
 * The phone bar's way back from a page one level down: a chevron and the open
 * thing's name (`title`), or with no title the chevron and where it goes back
 * to (`label`), the way iOS labels its back button. A swipe across the page presses it (`data-phone-back`). Nothing
 * on a laptop.
 */
export function PhoneBarBack({ label, title, onBack }: { label: string; title?: ReactNode; onBack: () => void }) {
    const bar = useContext(PhoneBarContext);
    const take = bar?.setLeadTaken;
    useEffect(() => {
        if (!take) return;
        take(true);
        return () => take(false);
    }, [take]);
    if (!bar?.lead) return null;
    return createPortal(
        title ? (
            <>
                <button type="button" onClick={onBack} aria-label={label} data-phone-back className={SIDEBAR_ICON_BUTTON}>
                    <ChevronLeft className="h-5 w-5" strokeWidth={1.75} />
                </button>
                <span className="flex min-w-0 flex-1 items-center gap-1 text-[15px] font-semibold tracking-[-0.01em] text-foreground">{title}</span>
            </>
        ) : (
            <button
                type="button"
                onClick={onBack}
                data-phone-back
                className="-ml-0.5 inline-flex h-10 min-w-0 items-center gap-0.5 rounded-lg pl-1 pr-2.5 text-[15px] text-foreground/85 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
            >
                <ChevronLeft className="h-5 w-5 shrink-0" strokeWidth={1.75} />
                <span className="truncate">{label}</span>
            </button>
        ),
        bar.lead
    );
}
