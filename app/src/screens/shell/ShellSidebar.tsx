// The app's one navigation, as the frame (AppShell) draws it: the workspace and search atop it, then the pages, and at
// the foot what the host keeps there (a card, a balance) and the account. On a laptop it is a column that folds to an
// icon rail; on a phone the same content is the menu's sheet. Its parts hold no data: the host hands it the workspace,
// the foot and the account, and says how to go to a page.
import { useEffect, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { ChevronRight } from 'lucide-react';
import { KINDS, type KindId } from '@/screens/resources/kinds';
import { BuilderMark } from '@/ui/glyphs';
import { HAIRLINE } from '@/ui/primitives';
import { SIDEBAR_CURRENT, SidebarHeader, SidebarItem } from '@/ui/sidebarParts';
import { cn } from '@/ui/utils';
import type { SidebarFrame } from './AppShell';
import type { ShellPage, ShellPageId } from './pages';

const RESOURCES_OPEN_KEY = 'nc-sidebar-resources-open';

function storedOpen(): boolean {
    try {
        return window.localStorage.getItem(RESOURCES_OPEN_KEY) === '1';
    } catch {
        return false;
    }
}

/** Resources, with a row per kind under it: the page is an overview, a kind is its list. One row, as in
 *  Cloudflare's sidebar: it opens onto the overview, and clicked again while open it folds its kinds away (the
 *  chevron only shows which). The choice is remembered. The kind open is the address's `kind`. */
export function ResourcesNav({
    page,
    current,
    collapsed,
    onKind,
    onNavigate,
}: {
    page: ShellPage;
    current: boolean;
    collapsed: boolean;
    /** Goes to Resources' overview (null) or one kind's list. */
    onKind: (kind: KindId | null) => void;
    onNavigate?: () => void;
}) {
    const [params] = useSearchParams();
    const activeKind = current ? (params.get('kind') as KindId | null) : null;
    const [open, setOpen] = useState(false);
    useEffect(() => setOpen(storedOpen()), []);
    useEffect(() => {
        if (current) setOpen(true);
    }, [current]);
    const remember = (next: boolean) => {
        setOpen(next);
        try {
            window.localStorage.setItem(RESOURCES_OPEN_KEY, next ? '1' : '0');
        } catch {
            // Not remembered this time.
        }
    };
    const go = (kind: KindId | null) => {
        onKind(kind);
        onNavigate?.();
    };
    const select = () => {
        if (current && open) return remember(false);
        remember(true);
        go(null);
    };
    if (collapsed) return <SidebarItem label={page.label} icon={page.icon} current={current} collapsed onSelect={() => go(null)} />;
    return (
        <div>
            <SidebarItem
                label={page.label}
                icon={page.icon}
                current={current && (!activeKind || !open)}
                collapsed={false}
                onSelect={select}
                expanded={open}
                trailing={<ChevronRight className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200', open && 'rotate-90')} strokeWidth={1.8} />}
            />
            {open && (
                // Text rows on a guide line hung from the Resources icon; each lines up with the parent's label.
                <div className="relative mt-0.5 flex flex-col gap-0.5 pl-8" role="group" aria-label="Resource kinds">
                    <span aria-hidden className="absolute bottom-1.5 left-[21.5px] top-1.5 w-px bg-foreground/15" />
                    {KINDS.map((kind) => {
                        const here = activeKind === kind.id;
                        return (
                            <button
                                key={kind.id}
                                type="button"
                                onClick={() => go(kind.id)}
                                aria-current={here ? 'page' : undefined}
                                className={cn(
                                    'flex h-9 w-full items-center gap-2 rounded-xl px-3 text-left text-[14.5px] transition-colors',
                                    here ? SIDEBAR_CURRENT : 'text-foreground/75 hover:bg-foreground/[0.05] hover:text-foreground'
                                )}
                            >
                                <span className="min-w-0 truncate">{kind.label}</span>
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

export interface ShellSidebarProps extends SidebarFrame {
    /** Atop it, beside search: the workspace (its name, or a way to switch it). */
    workspace: ReactNode;
    onSearch: () => void;
    /** With a canvas open: the builder chat beside it, and its toggle. */
    builder?: { open: boolean; onToggle: () => void };
    pages: readonly ShellPage[];
    /** The page open now. */
    current: string;
    onPage: (id: ShellPageId) => void;
    /** Goes to Resources' overview (null) or one kind's list. */
    onKind: (kind: KindId | null) => void;
    /** At the foot, above the account: a card shown while the sidebar is open, the balance (kept mounted on the rail,
     *  hidden), and a row under it. */
    card?: ReactNode;
    balance?: ReactNode;
    belowBalance?: ReactNode;
    /** The account, last. */
    account: ReactNode;
}

/** The sidebar's content, for the laptop column and the phone sheet alike. */
export function ShellSidebarContent({
    collapsed,
    headerEnd,
    onNavigate,
    workspace,
    onSearch,
    builder,
    pages,
    current,
    onPage,
    onKind,
    card,
    balance,
    belowBalance,
    account,
}: ShellSidebarProps) {
    const go = (id: ShellPageId) => {
        onPage(id);
        onNavigate?.();
    };
    const search = () => {
        onNavigate?.();
        onSearch();
    };
    return (
        <div className="flex h-full min-h-0 flex-col">
            <SidebarHeader collapsed={collapsed} title={workspace} onSearch={search} end={headerEnd} />

            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pb-3 scrollbar-subtle">
                {builder && (
                    <div className={cn('mb-2 border-b pb-2', HAIRLINE)}>
                        <SidebarItem label="Builder" icon={BuilderMark} current={builder.open} collapsed={collapsed} onSelect={builder.onToggle} />
                    </div>
                )}
                <nav aria-label="Main" className="flex flex-col gap-0.5">
                    {pages.map((page) =>
                        page.id === 'resources' ? (
                            <ResourcesNav key={page.id} page={page} current={current === page.id} collapsed={collapsed} onKind={onKind} onNavigate={onNavigate} />
                        ) : (
                            <SidebarItem key={page.id} label={page.label} icon={page.icon} current={current === page.id} collapsed={collapsed} onSelect={() => go(page.id)} />
                        )
                    )}
                </nav>
            </div>

            {/* No rule above the foot: its card and account stand on the column's own surface. */}
            <div className="flex shrink-0 flex-col gap-0.5 p-2">
                {!collapsed && card}
                {/* Mounted even on the rail: what's in it may listen for the app's events (a balance opens its way to
                    add funds when work runs out of them). */}
                {balance && (
                    <div className={cn(collapsed && 'hidden')} data-onboarding="balance">
                        {balance}
                    </div>
                )}
                {!collapsed && belowBalance}
                {account}
            </div>
        </div>
    );
}
