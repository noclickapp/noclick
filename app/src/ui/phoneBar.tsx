// The phone shell's top bar as the pages under it see it: whether they're in it,
// and where they put their actions and their way back. AppShell provides it;
// these read no app state, so any page can import them.
import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft } from 'lucide-react';

interface PhoneBar {
    /** Where the top bar takes a page's actions. */
    slot: HTMLElement | null;
    /** Where a page one level down puts its way back, in place of your picture (which opens the menu). */
    lead: HTMLElement | null;
    /** Where it puts the open thing's name, in place of the page's, centred on the bar. Without one (a lab's bar), the
     *  name goes beside the way back. */
    title?: HTMLElement | null;
    setLeadTaken: (taken: boolean) => void;
}

export const PhoneBarContext = createContext<PhoneBar | null>(null);

/** True inside the phone shell, whose top bar already names the page. */
export function useInPhoneShell(): boolean {
    return useContext(PhoneBarContext) !== null;
}

/** Hands what's under it a phone bar's slots, the way the phone shell does (a design lab): `slot` for its actions,
 *  `lead` for its way back (with `setLeadTaken` telling the bar it's in use), `title` for the open thing's name. */
export function PhoneBarSlotProvider({ slot, lead, title, setLeadTaken, children }: PhoneBar & { children: ReactNode }) {
    const bar = useMemo(() => ({ slot, lead, title, setLeadTaken }), [slot, lead, title, setLeadTaken]);
    return <PhoneBarContext.Provider value={bar}>{children}</PhoneBarContext.Provider>;
}

/** A page's actions, moved into the phone's top bar; nothing on a laptop. */
export function PhoneBarActions({ children }: { children: ReactNode }) {
    const bar = useContext(PhoneBarContext);
    return bar?.slot ? createPortal(children, bar.slot) : null;
}

/** The bar's round buttons, a thumb's 44px. */
export const PHONE_BAR_BUTTON =
    'inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-foreground transition-colors [-webkit-touch-callout:none] [@media(hover:hover)]:hover:bg-foreground/[0.06] [@media(hover:none)]:active:bg-foreground/[0.1] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/**
 * The phone bar's way back from a page one level down: a round back button with
 * the open thing's name (`title`) centred on the bar, or with no title the chevron
 * and where it goes back to (`label`), the way iOS labels its back button. A swipe across the page presses it
 * (`data-phone-back`). Nothing on a laptop.
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
    if (!title) {
        return createPortal(
            <button
                type="button"
                onClick={onBack}
                data-phone-back
                className="inline-flex h-11 min-w-0 items-center gap-0.5 rounded-full pl-1.5 pr-3 text-[17px] tracking-[-0.01em] text-foreground transition-colors [-webkit-touch-callout:none] [@media(hover:hover)]:hover:bg-foreground/[0.06] [@media(hover:none)]:active:bg-foreground/[0.1]"
            >
                <ChevronLeft className="h-6 w-6 shrink-0" strokeWidth={1.9} />
                <span className="truncate">{label}</span>
            </button>,
            bar.lead
        );
    }
    const back = (
        <button type="button" onClick={onBack} aria-label={label} data-phone-back className={PHONE_BAR_BUTTON}>
            <ChevronLeft className="h-6 w-6" strokeWidth={1.9} />
        </button>
    );
    const name = <span className="flex min-w-0 items-center justify-center gap-1.5 text-[17px] font-semibold tracking-[-0.015em] text-foreground">{title}</span>;
    if (!bar.title) return createPortal(<>{back}{name}</>, bar.lead);
    return (
        <>
            {createPortal(back, bar.lead)}
            {createPortal(name, bar.title)}
        </>
    );
}
