// The NoClick chat's "+": add photos and files from your computer or from the
// files you've already sent it, or point it at one of your automations or
// connected accounts. The menu opens as wide as the composer and in its
// surface, so it reads as part of the box; a list opens in its place,
// searchable and keyboard-driven, and picking something puts it in the box.
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode, type RefObject } from 'react';
import { ChevronLeft, FileText, Plus, type LucideIcon } from 'lucide-react';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { NodeMark } from '~/components/dashboard/primitives';
import { Popover, PopoverAnchor, PopoverContent, PopoverTrigger } from '~/components/ui/popover';
import { Skeleton } from '~/components/ui/skeleton';
import { relativeShort } from '~/components/workflow/WorkflowBrowserCards';
import { useWorkflowBrowserDataContext } from '~/hooks/WorkflowBrowserDataProvider';
import { useCredentialList } from '~/hooks/useCachedCredentialList';
import { useChatFiles, type ChatFile } from '~/hooks/useChatFiles';
import { isImageAttachment, type AgentChatAttachment, type ChatReference } from '~/lib/agentChat';
import { scoreFields } from '~/lib/fuzzyRank';
import { cn } from '~/lib/utils';
import { workflowIconTypes } from '~/lib/workflowBrowserStore';
import { useConnectedAccounts, type ConnectedAccount } from './connections/accounts';
import { accountIcon } from './connections/ConnectedList';
import { ACTION_GLYPHS, AutomationMark } from './glyphs';
import { MENU_SURFACE } from './menus';

type View = 'menu' | 'files' | 'automations' | 'accounts';

export const MENU_ITEM =
    'flex h-11 w-full items-center gap-3.5 rounded-[18px] px-3 text-left outline-none transition-colors hover:bg-foreground/[0.07] focus-visible:bg-foreground/[0.07]';
// Icons stand on their own, no tile: line glyphs in ink, logos a touch smaller so a filled mark weighs what a line does.
const SLOT = 'grid h-5 w-5 shrink-0 place-items-center text-foreground/90';
const LOGO = 'h-[18px] w-[18px]';
const line = (Glyph: LucideIcon) => <Glyph className="h-5 w-5" strokeWidth={1.75} />;
// The accounts the menu lists as rows of their own before the full list takes over.
const QUICK_ACCOUNTS = 3;

// The composer's own surface and radius, lifted off the page.
export const MENU_PANEL = `${MENU_SURFACE} rounded-[26px] p-2`;

/** An account named the way Connections names it: the app, then the account itself. */
export function accountReference(account: ConnectedAccount): ChatReference {
    const same = account.line === account.app || /^Added /.test(account.line);
    return { kind: 'account', id: account.credential.id, label: same ? account.app : `${account.app} · ${account.line}` };
}

function rank<T>(items: T[], query: string, fields: (item: T) => (string | undefined)[]): T[] {
    const q = query.trim();
    if (!q) return items;
    return items
        .map((item) => ({ item, score: scoreFields(q, fields(item)) }))
        .filter((x) => x.score !== null)
        .sort((a, b) => (a.score as number) - (b.score as number))
        .map((x) => x.item);
}

export function MenuItem({
    icon,
    title,
    detail,
    wideOnly = false,
    href,
    trailing,
    disabled = false,
    onSelect,
}: {
    icon: ReactNode;
    title: string;
    detail: string;
    /** A gloss the title can do without where it wouldn't fit (a phone). */
    wideOnly?: boolean;
    /** Opens this in its own app or tab rather than doing something here. */
    href?: string;
    trailing?: ReactNode;
    disabled?: boolean;
    onSelect: () => void;
}) {
    const body = (
        <>
            <span className={SLOT}>{icon}</span>
            <span className="flex min-w-0 flex-1 items-baseline gap-3 text-[15px]">
                <span className="shrink-0 text-foreground">{title}</span>
                <span className={cn('truncate text-muted-foreground', wideOnly && 'hidden sm:inline')}>{detail}</span>
            </span>
            {trailing}
        </>
    );
    return href && !disabled ? (
        <a href={href} target="_blank" rel="noopener noreferrer" data-menu-item onClick={onSelect} className={MENU_ITEM}>
            {body}
        </a>
    ) : (
        <button type="button" data-menu-item disabled={disabled} onClick={onSelect} className={cn(MENU_ITEM, 'disabled:opacity-60')}>
            {body}
        </button>
    );
}

/** A list or detail in the menu's place opens on this row. With a title, the way back is the title itself, one pill
 *  ("‹ Email"); beside a search, a filled circle, so it reads as a button rather than a stray caret. */
export function MenuBackRow({ onBack, title, children }: { onBack: () => void; title?: string; children?: ReactNode }) {
    return (
        <div className="-mx-2 -mt-2 flex h-14 items-center gap-2 border-b border-border px-3 dark:border-foreground/[0.07]">
            {title ? (
                <button
                    type="button"
                    onClick={onBack}
                    aria-label={`Back from ${title}`}
                    className="inline-flex h-9 items-center gap-1 rounded-full pl-1.5 pr-3.5 text-[15px] font-medium text-foreground transition-colors hover:bg-foreground/[0.07] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                    <ChevronLeft className="h-[18px] w-[18px] text-muted-foreground" />
                    {title}
                </button>
            ) : (
                <button
                    type="button"
                    onClick={onBack}
                    aria-label="Back"
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-foreground/80 transition-colors hover:bg-foreground/[0.1] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                    <ChevronLeft className="h-[18px] w-[18px]" />
                </button>
            )}
            {children}
        </div>
    );
}

/** Arrow keys move between a menu's items. */
export function moveBetweenMenuItems(container: HTMLElement | null, event: KeyboardEvent) {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    const items = Array.from(container?.querySelectorAll<HTMLElement>('[data-menu-item]:not(:disabled)') ?? []);
    if (!items.length) return;
    event.preventDefault();
    const at = items.indexOf(document.activeElement as HTMLElement);
    const step = event.key === 'ArrowDown' ? 1 : -1;
    items[(at + step + items.length + (at < 0 && step < 0 ? 1 : 0)) % items.length]?.focus();
}

interface PickerRow {
    key: string;
    mark: ReactNode;
    title: string;
    meta?: string;
    pick: () => void;
}

/** A list in the menu's place: one quiet search row (with the way back), then the rows. */
function Picker({ placeholder, query, onQuery, rows, loading, empty, onBack }: { placeholder: string; query: string; onQuery: (q: string) => void; rows: PickerRow[]; loading: boolean; empty: string; onBack: () => void }) {
    const [active, setActive] = useState(0);
    const listRef = useRef<HTMLDivElement>(null);
    useEffect(() => setActive(0), [query, rows.length]);
    useEffect(() => {
        listRef.current?.querySelector<HTMLElement>(`[data-row="${active}"]`)?.scrollIntoView({ block: 'nearest' });
    }, [active]);
    const onKeyDown = (event: KeyboardEvent) => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (rows.length) setActive((i) => (i + (event.key === 'ArrowDown' ? 1 : rows.length - 1)) % rows.length);
        } else if (event.key === 'Enter') {
            event.preventDefault();
            rows[active]?.pick();
        }
    };
    return (
        <div>
            <MenuBackRow onBack={onBack}>
                <input
                    // eslint-disable-next-line jsx-a11y/no-autofocus -- the list opened to be searched
                    autoFocus
                    value={query}
                    onChange={(e) => onQuery(e.target.value)}
                    onKeyDown={onKeyDown}
                    placeholder={placeholder}
                    aria-label={placeholder}
                    className="h-full min-w-0 flex-1 bg-transparent px-1.5 text-[15px] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))]"
                />
            </MenuBackRow>
            <div ref={listRef} role="listbox" aria-label={placeholder} className="-mx-1 max-h-[320px] overflow-y-auto px-1 pt-2 scrollbar-subtle">
                {loading && !rows.length ? (
                    [0, 1, 2].map((i) => (
                        <div key={i} className="flex h-11 items-center gap-3.5 px-3">
                            <Skeleton className="h-6 w-6 rounded-[6px]" />
                            <Skeleton className={cn('h-3.5', i === 1 ? 'w-28' : 'w-44')} />
                        </div>
                    ))
                ) : rows.length ? (
                    rows.map((row, i) => (
                        <button
                            key={row.key}
                            type="button"
                            role="option"
                            aria-selected={i === active}
                            data-row={i}
                            onMouseMove={() => setActive(i)}
                            onClick={row.pick}
                            className={cn(MENU_ITEM, 'hover:bg-transparent focus-visible:bg-transparent', i === active && 'bg-foreground/[0.07] hover:bg-foreground/[0.07]')}
                        >
                            <span className={cn(SLOT, 'h-6 w-6')}>{row.mark}</span>
                            <span className="min-w-0 flex-1 truncate text-[15px] text-foreground">{row.title}</span>
                            {row.meta ? <span className="shrink-0 text-[13px] text-muted-foreground">{row.meta}</span> : null}
                        </button>
                    ))
                ) : (
                    <p className="px-4 py-7 text-center text-[14px] leading-relaxed text-muted-foreground">{empty}</p>
                )}
            </div>
        </div>
    );
}

function FilesPicker({ list, onBack, onAttach }: { list: (query: string) => Promise<ChatFile[]>; onBack: () => void; onAttach: (attachment: AgentChatAttachment) => void }) {
    const [query, setQuery] = useState('');
    const { files, loading } = useChatFiles(list, query);
    const rows = files.map(
        (file): PickerRow => ({
            key: file.resourceId,
            mark: isImageAttachment(file) ? <img src={file.url} alt="" className="h-6 w-6 rounded-[6px] object-cover ring-1 ring-foreground/10" /> : line(FileText),
            title: file.name,
            meta: relativeShort(file.createdAt),
            pick: () => onAttach(file),
        })
    );
    return (
        <Picker
            placeholder="Search your files"
            query={query}
            onQuery={setQuery}
            rows={rows}
            loading={loading}
            empty={query.trim() ? 'No file matches.' : 'Files you send NoClick, here or on WhatsApp and email, show up here.'}
            onBack={onBack}
        />
    );
}

function AutomationsPicker({ onBack, onReference }: { onBack: () => void; onReference: (reference: ChatReference) => void }) {
    const [query, setQuery] = useState('');
    const { loadAllWorkflows, getAllWorkflows } = useWorkflowBrowserDataContext();
    const [loading, setLoading] = useState(true);
    // Once per open, so names and marks are current (the ⌘K palette does the same).
    const loadRef = useRef(loadAllWorkflows);
    useEffect(() => {
        void Promise.resolve(loadRef.current(true)).finally(() => setLoading(false));
    }, []);
    const workflows = useMemo(() => [...getAllWorkflows()].sort((a, b) => (b.updated_at ?? '').localeCompare(a.updated_at ?? '')), [getAllWorkflows]);
    const rows = rank(workflows, query, (w) => [w.name]).map((w): PickerRow => {
        const type = workflowIconTypes(w)[0];
        return {
            key: w.id,
            mark: type ? <NodeMark type={type} size="md" /> : <AutomationMark className="h-5 w-5" />,
            title: w.name || 'Untitled',
            meta: w.updated_at ? relativeShort(w.updated_at) : undefined,
            pick: () => onReference({ kind: 'automation', id: w.id, label: w.name || 'Untitled' }),
        };
    });
    return (
        <Picker
            placeholder="Search your automations"
            query={query}
            onQuery={setQuery}
            rows={rows}
            loading={loading}
            empty={query.trim() ? 'No automation matches.' : 'You have no automations yet.'}
            onBack={onBack}
        />
    );
}

/** An account's app logo, in its own colours. */
function AccountGlyph({ account }: { account: ConnectedAccount }) {
    const { Icon, iconColor } = accountIcon(account.credential);
    return <BrandIcon Icon={Icon} iconColor={iconColor} className={LOGO} />;
}

function AccountsPicker({ accounts, loaded, onBack, onReference }: { accounts: ConnectedAccount[]; loaded: boolean; onBack: () => void; onReference: (reference: ChatReference) => void }) {
    const [query, setQuery] = useState('');
    const rows = rank(accounts, query, (a) => [a.app, a.line, a.credential.name]).map(
        (account): PickerRow => ({
            key: account.credential.id,
            mark: <AccountGlyph account={account} />,
            title: account.app,
            meta: account.line === account.app ? undefined : account.line,
            pick: () => onReference(accountReference(account)),
        })
    );
    return (
        <Picker
            placeholder="Search your accounts"
            query={query}
            onQuery={setQuery}
            rows={rows}
            loading={!loaded}
            empty={query.trim() ? 'No account matches.' : 'Connect an app in Connections and it shows up here.'}
            onBack={onBack}
        />
    );
}

export function ComposerAddMenu({
    anchorRef,
    side = 'top',
    disabled,
    onAddFiles,
    listFiles,
    onAttach,
    onReference,
}: {
    /** The composer card: the menu opens against it, as wide as it. */
    anchorRef: RefObject<HTMLElement | null>;
    /** Above the box once it sits at the foot of a thread; below it while it's the middle of an empty page. */
    side?: 'top' | 'bottom';
    disabled?: boolean;
    onAddFiles: (files: File[]) => void;
    /** The files sent before, by name; without it (or `onAttach`) the menu doesn't offer them. */
    listFiles?: (query: string) => Promise<ChatFile[]>;
    /** A file sent before, picked again. */
    onAttach?: (attachment: AgentChatAttachment) => void;
    onReference: (reference: ChatReference) => void;
}) {
    const [open, setOpen] = useState(false);
    const [view, setView] = useState<View>('menu');
    const fileInput = useRef<HTMLInputElement>(null);
    const { credentials, loaded } = useCredentialList();
    const all = useConnectedAccounts(credentials);
    // Only accounts that work are worth pointing at; the newest first.
    const accounts = useMemo(
        () => all.filter((a) => !a.problem).sort((a, b) => (b.credential.created_at ?? '').localeCompare(a.credential.created_at ?? '')),
        [all]
    );
    const menuRef = useRef<HTMLDivElement>(null);

    const close = () => setOpen(false);
    const pick = <T,>(fn: (value: T) => void) => (value: T) => {
        fn(value);
        close();
    };

    return (
        <Popover
            open={open}
            onOpenChange={(next) => {
                setOpen(next);
                if (next) setView('menu');
            }}
        >
            <input
                ref={fileInput}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                    if (e.target.files?.length) onAddFiles(Array.from(e.target.files));
                    // The same file picked twice should land twice.
                    e.target.value = '';
                }}
            />
            <PopoverTrigger asChild>
                <button
                    type="button"
                    disabled={disabled}
                    aria-label="Add files, automations or accounts"
                    data-testid="composer-add-button"
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-foreground/80 transition-colors hover:bg-foreground/[0.07] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40 data-[state=open]:bg-foreground/[0.08] data-[state=open]:text-foreground"
                >
                    <Plus className="h-5 w-5" strokeWidth={1.75} />
                </button>
            </PopoverTrigger>
            {/* After the trigger: Radix keeps the anchor that registered last, and this one is the box. */}
            <PopoverAnchor virtualRef={anchorRef as RefObject<HTMLElement>} />
            <PopoverContent
                side={side}
                align="start"
                sideOffset={8}
                data-testid="composer-add-menu"
                className={cn('w-[var(--radix-popover-trigger-width)]', MENU_PANEL)}
                onEscapeKeyDown={(event) => {
                    // Escape steps back out of a list before it closes the menu.
                    if (view !== 'menu') {
                        event.preventDefault();
                        setView('menu');
                    }
                }}
            >
                {view === 'files' && listFiles && onAttach ? (
                    <FilesPicker list={listFiles} onBack={() => setView('menu')} onAttach={pick(onAttach)} />
                ) : view === 'automations' ? (
                    <AutomationsPicker onBack={() => setView('menu')} onReference={pick(onReference)} />
                ) : view === 'accounts' ? (
                    <AccountsPicker accounts={accounts} loaded={loaded} onBack={() => setView('menu')} onReference={pick(onReference)} />
                ) : (
                    // eslint-disable-next-line jsx-a11y/no-static-element-interactions -- arrow keys move between the items
                    <div ref={menuRef} onKeyDown={(event) => moveBetweenMenuItems(menuRef.current, event)}>
                        <MenuItem
                            icon={line(ACTION_GLYPHS.upload)}
                            title="Add photos & files"
                            detail="Upload from your computer"
                            wideOnly
                            onSelect={() => {
                                close();
                                fileInput.current?.click();
                            }}
                        />
                        {listFiles && onAttach && (
                            <MenuItem icon={line(ACTION_GLYPHS.files)} title="Add from your files" detail="Anything you’ve sent NoClick" wideOnly onSelect={() => setView('files')} />
                        )}
                        <MenuItem icon={<AutomationMark className="h-5 w-5" />} title="Point at an automation" detail="Ask about it, change it, run it" wideOnly onSelect={() => setView('automations')} />
                        {/* Your accounts are rows of their own, each in its app's logo; the full list opens from a last row
                            once there are more than fit. */}
                        {accounts.slice(0, QUICK_ACCOUNTS).map((account) => (
                            <MenuItem
                                key={account.credential.id}
                                icon={<AccountGlyph account={account} />}
                                title={account.app}
                                detail={account.line === account.app ? 'Use this account' : account.line}
                                onSelect={() => pick(onReference)(accountReference(account))}
                            />
                        ))}
                        {accounts.length === 0 ? (
                            <MenuItem icon={line(ACTION_GLYPHS.account)} title="Use an account" detail="Say which one NoClick acts through" wideOnly onSelect={() => setView('accounts')} />
                        ) : accounts.length > QUICK_ACCOUNTS ? (
                            <MenuItem
                                icon={line(ACTION_GLYPHS.account)}
                                title="All accounts"
                                detail={`${accounts.length - QUICK_ACCOUNTS} more`}
                                onSelect={() => setView('accounts')}
                            />
                        ) : null}
                    </div>
                )}
            </PopoverContent>
        </Popover>
    );
}
