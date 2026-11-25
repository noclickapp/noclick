// The app's frame. On a laptop: the sidebar, then (beside an open canvas) the builder chat, then the page. On a phone:
// a slim bar with the menu, the page's name and the page's own actions over the page, the sidebar under the page, which
// a swipe slides aside (on a page one level down the swipe goes back instead: PhoneDrawer), and the builder over the
// canvas while it's open. The builder is mounted once either way. What the sidebar holds is the host's: the frame draws
// it as a column on a laptop and in the drawer on a phone. A strip across the top of the page is the shell's
// `shell.banner` slot.
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Menu } from 'lucide-react';
import { useSlot } from '@/slots';
import { BuilderMark } from '@/ui/glyphs';
import { PhoneBarContext } from '@/ui/phoneBar';
import { PHONE_PAGE, SIDEBAR_ICON_BUTTON, SidebarColumn, SidebarToggle, useSidebarShortcut } from '@/ui/sidebarParts';
import { sidebarWidthFor, useSidebarResizing, useSidebarWidth } from '@/ui/sidebarPanel';
import { cn } from '@/ui/utils';
import { PhoneDrawer } from './PhoneDrawer';
import { BANNER } from './slots';

/** Where the sidebar's content is drawn: the laptop column (folded to a rail or not) or the phone's sheet. */
export interface SidebarFrame {
    collapsed: boolean;
    /** The header's control at its end (collapse on a laptop; none on a phone, where the page beside it closes it). */
    headerEnd: ReactNode;
    /** Called after any navigation, so a sheet can close itself. */
    onNavigate?: () => void;
}

export interface AppShellProps {
    isMobile: boolean;
    /** The sidebar's content, for where the frame draws it. */
    sidebar: (frame: SidebarFrame) => ReactNode;
    /** Laptop: the sidebar is an icon rail. */
    collapsed: boolean;
    onCollapsedChange: (collapsed: boolean) => void;
    /** The page's name, for the phone bar (a link where it leads somewhere). */
    title: ReactNode;
    /** The builder chat, mounted once. */
    builder: ReactNode;
    builderShown: boolean;
    /** Phone, with a canvas open: the bar's way to the builder and back. */
    builderToggle?: { open: boolean; onToggle: () => void };
    /** Laptop: the builder's width beside the sidebar. */
    builderWidth: number;
    /** False while the builder is being dragged or opened by keyboard: no easing. */
    animate: boolean;
    children: ReactNode;
}

function LaptopShell({ sidebar, collapsed, onCollapsedChange, builder, builderShown, builderWidth, animate, children }: AppShellProps) {
    const Banner = useSlot(BANNER);
    const sidebarWidth = useSidebarWidth();
    const resizing = useSidebarResizing();
    useSidebarShortcut(collapsed, onCollapsedChange);

    return (
        <>
            <SidebarColumn collapsed={collapsed} className="fixed inset-y-0 left-0 z-30" testId="app-sidebar">
                {sidebar({ collapsed, headerEnd: <SidebarToggle collapsed={collapsed} onCollapsedChange={onCollapsedChange} /> })}
            </SidebarColumn>
            <div className={builderShown ? undefined : 'hidden'}>{builder}</div>
            {/* Clip, not hidden: hidden on one axis makes the other scroll, and pages own their scrolling. */}
            <div
                className="fixed inset-y-0 right-0 flex flex-col overflow-x-clip bg-background"
                style={{
                    left: sidebarWidthFor(collapsed, sidebarWidth) + (builderShown ? builderWidth : 0),
                    transition: animate && !resizing ? 'left 200ms cubic-bezier(0.16, 1, 0.3, 1)' : 'none',
                }}
            >
                {Banner && <Banner />}
                <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
            </div>
        </>
    );
}

function PhoneShell({ sidebar, title, builder, builderShown, builderToggle, children }: AppShellProps) {
    const Banner = useSlot(BANNER);
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
    const trigger = useRef<HTMLButtonElement>(null);
    const page = useRef<HTMLDivElement>(null);
    // The bar's way back where a page one level down (or the builder's history) put one, for the swipe to press.
    const backControl = useCallback(() => {
        const holder = builderLeads ? builderLead : leadTaken ? lead : null;
        return holder?.querySelector<HTMLElement>('[data-phone-back]') ?? null;
    }, [builderLeads, builderLead, leadTaken, lead]);
    // Anything in the menu that moves to another page (the balance meter opens Usage) closes it.
    useEffect(() => {
        const onSwitch = () => setMenuOpen(false);
        window.addEventListener('noclick:switch-tab', onSwitch);
        return () => window.removeEventListener('noclick:switch-tab', onSwitch);
    }, []);
    return (
        // Clear of the notch and the home indicator, so every page's foot (a message box, a view bar) is where a thumb
        // reaches it without each page keeping clear itself.
        <div
            ref={page}
            inert={menuOpen}
            data-menu={menuOpen ? 'open' : undefined}
            className={cn('fixed inset-0 flex flex-col bg-background pb-[env(safe-area-inset-bottom)] pt-[env(safe-area-inset-top)]', PHONE_PAGE)}
        >
            {Banner && <Banner />}
            <header className="flex h-12 shrink-0 items-center gap-1 px-2">
                <button
                    ref={trigger}
                    type="button"
                    aria-label="Open menu"
                    aria-haspopup="dialog"
                    aria-expanded={menuOpen}
                    aria-controls="phone-menu"
                    onClick={() => setMenuOpen(true)}
                    className={cn(SIDEBAR_ICON_BUTTON, taken && 'hidden')}
                >
                    <Menu className="h-5 w-5" strokeWidth={1.75} />
                </button>
                <PhoneDrawer open={menuOpen} onOpenChange={setMenuOpen} back={backControl} trigger={trigger} page={page}>
                    {sidebar({ collapsed: false, headerEnd: null, onNavigate: close })}
                </PhoneDrawer>
                <span className={cn('min-w-0 flex-1 truncate px-1 text-[15px] font-semibold tracking-[-0.01em] text-foreground', taken && 'hidden')}>{title}</span>
                <div ref={setLead} className={leadTaken && !builderLeads ? 'flex min-w-0 flex-1 items-center gap-1' : 'hidden'} />
                <div ref={setBuilderLead} className={builderLeads ? 'flex min-w-0 flex-1 items-center gap-1' : 'hidden'} />
                {/* Its actions shrink before they run off the bar: a label in them truncates. */}
                <div ref={setSlot} className={cn('flex min-w-0 items-center gap-0.5', builderShown && 'hidden')} />
                <div ref={setBuilderSlot} className={cn('flex shrink-0 items-center gap-0.5', !builderShown && 'hidden')} />
                {builderToggle && (
                    <button
                        type="button"
                        onClick={builderToggle.onToggle}
                        aria-pressed={builderToggle.open}
                        className={cn(
                            'inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[13px] transition-colors',
                            builderToggle.open ? 'bg-primary text-primary-foreground' : 'text-foreground/80 hover:bg-foreground/[0.06]'
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
