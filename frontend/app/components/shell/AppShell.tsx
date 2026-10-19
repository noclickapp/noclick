// The app's frame. On a laptop: the sidebar, then (beside an open canvas) the
// builder chat, then the page. On a phone: a slim bar with the menu, the page's
// name and the page's own actions over the page, the sidebar as a sheet, and
// the builder over the canvas while it's open. The builder is mounted once
// either way; its bridges answer builder events from any page.
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import * as Dialog from '@radix-ui/react-dialog';
import { ChevronLeft, Menu } from 'lucide-react';
import { cn } from '~/lib/utils';
import {
    AppSidebar,
    SIDEBAR_ICON_BUTTON,
    SIDEBAR_SHEET,
    SIDEBAR_SHEET_OVERLAY,
    SheetClose,
    SidebarContent,
    useSidebarShortcut,
    type SidebarProps,
} from './AppSidebar';
import { BuilderMark } from './glyphs';
import { sidebarWidthFor, useSidebarResizing, useSidebarWidth } from './sidebarWidth';

export interface AppShellProps {
    isMobile: boolean;
    sidebar: SidebarProps;
    /** Laptop: the sidebar is an icon rail. */
    collapsed: boolean;
    onCollapsedChange: (collapsed: boolean) => void;
    /** The page's name, for the phone bar. */
    title: string;
    /** The builder chat, mounted once. */
    builder: ReactNode;
    builderShown: boolean;
    /** Laptop: the builder's width beside the sidebar. */
    builderWidth: number;
    /** False while the builder is being dragged or opened by keyboard: no easing. */
    animate: boolean;
    /** A strip across the top of the page (hosted: the mimic banner). */
    banner?: ReactNode;
    children: ReactNode;
}


interface PhoneBar {
    /** Where the top bar takes a page's actions. */
    slot: HTMLElement | null;
    /** Where a page one level down puts its way back, in place of the menu and the page's name. */
    lead: HTMLElement | null;
    setLeadTaken: (taken: boolean) => void;
}

const PhoneBarContext = createContext<PhoneBar | null>(null);

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
 * to (`label`), the way iOS labels its back button. Nothing on a laptop.
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
                <button type="button" onClick={onBack} aria-label={label} className={SIDEBAR_ICON_BUTTON}>
                    <ChevronLeft className="h-5 w-5" strokeWidth={1.75} />
                </button>
                <span className="flex min-w-0 flex-1 items-center gap-1 text-[15px] font-semibold tracking-[-0.01em] text-foreground">{title}</span>
            </>
        ) : (
            <button
                type="button"
                onClick={onBack}
                className="-ml-0.5 inline-flex h-9 min-w-0 items-center gap-0.5 rounded-lg pl-1 pr-2.5 text-[15px] text-foreground/85 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
            >
                <ChevronLeft className="h-5 w-5 shrink-0" strokeWidth={1.75} />
                <span className="truncate">{label}</span>
            </button>
        ),
        bar.lead
    );
}

function LaptopShell({ sidebar, collapsed, onCollapsedChange, builder, builderShown, builderWidth, animate, banner, children }: AppShellProps) {
    const sidebarWidth = useSidebarWidth();
    const resizing = useSidebarResizing();
    useSidebarShortcut(collapsed, onCollapsedChange);

    return (
        <>
            <AppSidebar {...sidebar} collapsed={collapsed} onCollapsedChange={onCollapsedChange} />
            <div className={builderShown ? undefined : 'hidden'}>{builder}</div>
            <div
                className="fixed inset-y-0 right-0 flex flex-col overflow-x-hidden bg-background"
                style={{
                    left: sidebarWidthFor(collapsed, sidebarWidth) + (builderShown ? builderWidth : 0),
                    transition: animate && !resizing ? 'left 200ms cubic-bezier(0.16, 1, 0.3, 1)' : 'none',
                }}
            >
                {banner}
                <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
            </div>
        </>
    );
}

function PhoneShell({ sidebar, title, builder, builderShown, banner, children }: AppShellProps) {
    const [menuOpen, setMenuOpen] = useState(false);
    const [slot, setSlot] = useState<HTMLElement | null>(null);
    const [builderSlot, setBuilderSlot] = useState<HTMLElement | null>(null);
    const [lead, setLead] = useState<HTMLElement | null>(null);
    const [leadTaken, setLeadTaken] = useState(false);
    const [builderLead, setBuilderLead] = useState<HTMLElement | null>(null);
    const [builderLeadTaken, setBuilderLeadTaken] = useState(false);
    const bar = useMemo(() => ({ slot, lead, setLeadTaken }), [slot, lead]);
    // The builder over the page has slots of its own, shown in place of the page's while it's open: its actions, and
    // its way back (out of its history), which is the builder's, not the page's.
    const builderBar = useMemo(() => ({ slot: builderSlot, lead: builderLead, setLeadTaken: setBuilderLeadTaken }), [builderSlot, builderLead]);
    const builderLeads = builderShown && builderLeadTaken;
    const taken = builderLeads || leadTaken;
    const close = () => setMenuOpen(false);
    // Anything in the menu that moves to another page (the balance meter opens Usage) closes it.
    useEffect(() => {
        const onSwitch = () => setMenuOpen(false);
        window.addEventListener('noclick:switch-tab', onSwitch);
        return () => window.removeEventListener('noclick:switch-tab', onSwitch);
    }, []);
    return (
        <div className="fixed inset-0 flex flex-col bg-background pt-[env(safe-area-inset-top)]">
            {banner}
            <header className="flex h-12 shrink-0 items-center gap-1 px-2">
                <Dialog.Root open={menuOpen} onOpenChange={setMenuOpen}>
                    <Dialog.Trigger aria-label="Open menu" className={cn(SIDEBAR_ICON_BUTTON, taken && 'hidden')}>
                        <Menu className="h-5 w-5" strokeWidth={1.75} />
                    </Dialog.Trigger>
                    <Dialog.Portal>
                        <Dialog.Overlay className={SIDEBAR_SHEET_OVERLAY} />
                        <Dialog.Content className={SIDEBAR_SHEET}>
                            <Dialog.Title className="sr-only">Menu</Dialog.Title>
                            <Dialog.Description className="sr-only">Pages and your account</Dialog.Description>
                            <SidebarContent {...sidebar} headerEnd={<SheetClose onClose={close} />} onNavigate={close} />
                        </Dialog.Content>
                    </Dialog.Portal>
                </Dialog.Root>
                <span className={cn('min-w-0 flex-1 truncate px-1 text-[15px] font-semibold tracking-[-0.01em] text-foreground', taken && 'hidden')}>{title}</span>
                <div ref={setLead} className={leadTaken && !builderLeads ? 'flex min-w-0 flex-1 items-center gap-1' : 'hidden'} />
                <div ref={setBuilderLead} className={builderLeads ? 'flex min-w-0 flex-1 items-center gap-1' : 'hidden'} />
                <div ref={setSlot} className={cn('flex shrink-0 items-center gap-0.5', builderShown && 'hidden')} />
                <div ref={setBuilderSlot} className={cn('flex shrink-0 items-center gap-0.5', !builderShown && 'hidden')} />
                {sidebar.builder && (
                    <button
                        type="button"
                        onClick={sidebar.builder.onToggle}
                        aria-pressed={sidebar.builder.open}
                        className={cn(
                            'inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[13px] transition-colors',
                            sidebar.builder.open ? 'bg-primary text-primary-foreground' : 'text-foreground/80 hover:bg-foreground/[0.06]'
                        )}
                    >
                        <BuilderMark className="h-4 w-4" />
                        Builder
                    </button>
                )}
            </header>
            <main className="relative min-h-0 flex-1 overflow-hidden">
                <PhoneBarContext.Provider value={bar}>{children}</PhoneBarContext.Provider>
                <div className={builderShown ? 'absolute inset-0 z-20 flex flex-col bg-background' : 'hidden'}>
                    <PhoneBarContext.Provider value={builderBar}>{builder}</PhoneBarContext.Provider>
                </div>
            </main>
        </div>
    );
}

export function AppShell(props: AppShellProps) {
    return props.isMobile ? <PhoneShell {...props} /> : <LaptopShell {...props} />;
}
