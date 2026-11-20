// The harness and model picker, after t3code's: a pill by the box that opens a rail of harnesses, their models and the
// chosen model's reasoning, with the account it runs on, its speed and its permissions at its foot. Shared by the New
// agent draft and an agent's own box, so it only takes a value and reports changes; the harnesses, models and accounts
// it lists are the platform's (catalog.ts), and an account that can't run a model says why (accounts.ts). An agent's
// box moves it onto another harness from here, and asks in place which account it runs on there (`choice`). A costly
// model on NoClick's key that the account hasn't added the funds for says what to add, and picking it opens Add funds
// (funds.tsx).
import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, Check, ChevronUp, KeyRound, Plus, Search, Star, Zap } from 'lucide-react';
import type { HarnessInfo, HarnessName, PermissionMode } from 'noclick';
import { BrandIcon } from '@/ui/BrandIcon';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { useSlot } from '@/slots';
import { useConnectionMarks } from '@/ui/connectionMark';
import { CONNECT_MODEL } from '@/ui/slots';
import { useWorkClient } from '../client';
import type { CostlyModel } from '../slots';
import { MENU_SURFACE } from '@/ui/menus';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { cn } from '@/ui/utils';
import { TAP_AREA } from '@/ui/buttons';
import { HARNESSES, HarnessMark, harnessLabel } from '../agents/harness';
import { RailTip, tipBeside, useRailTips } from '../railTip';
import { ACCOUNT_KINDS, accountChoices, accountRefusal, accountShort, accountTitle, connectAsk, downWord, firstUsable, type ModelAccount, needsAccount, runsUnpicked, wayLabel, waysFor, wayTitle, wayType } from './accounts';
import { modelName, namedRows, PERMISSION_ICON, type HarnessModel, type ModelRow as Row, PERMISSION_MODES, modesOf, rereadAccounts, traitsOf, useHarnesses, useHarnessModels, useModelAccounts, useModelRoutes, useModelSearch } from './catalog';
import { fundsNote, fundsShort, fundsTag, useAddedFunds, useFundsThenSwitch } from './funds';

/** What the picker sets: where it runs, on which model and account, how hard it thinks, how fast, and what it may do
 *  unasked. */
export interface PickerValue {
    harness: HarnessName;
    model: string;
    /** One of the harness's efforts; null where it has none. */
    effort: string | null;
    /** One of the harness's speeds; null where it has none. */
    speed: string | null;
    permissions: PermissionMode;
    /** The account its model runs on (a model connection's name, or `noclick`); null when none it holds runs it. */
    account?: string | null;
}

/** A move onto another harness waiting on which of your accounts it runs on there: shown in place of the models. */
export interface AccountChoice {
    harness: HarnessInfo;
    accounts: ModelAccount[];
    onPick: (account: string) => void;
    onCancel: () => void;
}

export interface HarnessModelPickerProps {
    value: PickerValue;
    onChange: (next: PickerValue) => void;
    /** Which account a move onto another harness runs on, asked in place; none waits when left out. */
    choice?: AccountChoice | null;
    /** The AI accounts the account holds; given, the picker also picks the one the model runs on. */
    accounts?: ModelAccount[];
    /** The modes the harness enforces here (a conversation's settings); its usual modes when left out. */
    permissionModes?: PermissionMode[];
    /** Controlled open state (the /model command); uncontrolled when left out. */
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    triggerClassName?: string;
    /** False where a pill beside it names the account already (a conversation's footer): the model's pill names none. */
    accountInPill?: boolean;
    /** Who a pick waiting on funds belongs to (an agent, a conversation, the New agent draft), so it's made once they
     *  land even after the checkout's round trip reloads the page; on this page only when left out. */
    fundsOwner?: string;
}

export { PERMISSION_ICON } from './catalog';

/** Where the picker opens as a bottom sheet instead of a popover: a phone's screen provides it. */
export const PickerSheetHost = createContext<HTMLElement | null>(null);

/** A harness's defaults: its default model, its usual effort and first speed, and the permissions carried over when it
 *  can enforce them (Full access otherwise, else Supervised). One that takes no mode (NoClick's own runtime, whose
 *  calls the account's policy holds) is Full access, which sends none. */
export function onHarness(value: Pick<PickerValue, 'permissions'>, harness: HarnessInfo, model = harness.defaultModel): PickerValue {
    const modes = harness.permissionModes;
    const traits = traitsOf(harness);
    return {
        harness: harness.name,
        model,
        effort: traits.defaultEffort,
        speed: traits.speeds[0] ?? null,
        permissions: modes.includes(value.permissions) ? value.permissions : modes.includes('full-access') || !modes.length ? 'full-access' : 'approval-required',
    };
}

/** A new agent's starting value on a harness: Full access, its defaults. */
export const newPickerValue = (harness: HarnessInfo): PickerValue => onHarness({ permissions: 'full-access' }, harness);

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ');

// ── accounts ────────────────────────────────────────────────────────────────

/** An account's mark: the app's own logo for its kind, NoClick's for NoClick's key. */
export function AccountMark({ account, className = 'h-4 w-4' }: { account: ModelAccount; className?: string }) {
    const marks = useConnectionMarks();
    if (account.kind === 'noclick') return <HarnessMark harness="sdk" className={className} />;
    const type = account.kind === 'key' ? `agent_${account.integration}` : ACCOUNT_KINDS[account.kind].credentialType;
    const mark = marks.aiGlyph(type);
    return mark ? <BrandIcon Icon={mark.Icon} iconColor={mark.iconColor} className={cn('shrink-0', className)} /> : <KeyRound className={cn('shrink-0 text-muted-foreground', className)} strokeWidth={1.75} />;
}

/** How the connect popup opens: to connect `another` account beside those that run the pick, or `on` one kind of
 *  account (a failed turn's, whose provider refused it) rather than the pick's best way. */
export interface ConnectOptions {
    another?: boolean;
    on?: Pick<ModelAccount, 'kind' | 'integration'> | null;
}

/** Connecting the AI account a pick needs, in the app's own AI dialog (Connections'), on one way that runs it at a time
 *  (the plan signed out, else the best), the others as "Or run it on" pills. What lands is picked (`credential:<id>`,
 *  the ref an agent takes it by) as soon as the account list reads it connected. The state lives in the host, which
 *  outlives the dialog. */
export function useConnectAi(onPicked: (account: string) => void): { connect: (harness: HarnessInfo, model: string, options?: ConnectOptions) => void; dialog: ReactNode } {
    const Connect = useSlot(CONNECT_MODEL);
    const client = useWorkClient();
    const { accounts, labels } = useModelAccounts();
    const [open, setOpen] = useState<{ harness: HarnessInfo; model: string; another: boolean } | null>(null);
    const [focus, setFocus] = useState<string | null>(null);
    const [landed, setLanded] = useState<string | null>(null);
    const picked = useRef(onPicked);
    picked.current = onPicked;
    const done = landed ? accounts?.find((a) => a.id === landed && a.connected) : undefined;
    useEffect(() => {
        if (!done) return;
        setLanded(null);
        picked.current(done.id);
    }, [done]);
    const { routes } = useModelRoutes(open?.harness, open?.model ?? '');
    const ways = open ? waysFor(open.harness, open.model, labels, routes) : [];
    const ask = open ? connectAsk(accounts ?? [], open.harness, open.model, ways, routes) : null;
    const way = ways.find((w) => w.id === focus) ?? ask?.lead ?? null;
    // The account it replaces says why it stopped: who was signed out, or its provider's refusal.
    const lapsed = ask?.lapsed && way?.kind === ask.lapsed.kind ? ask.lapsed : null;
    const why = lapsed ? (lapsed.down?.reason !== 'refused' && lapsed.email ? `${lapsed.email} was signed out.` : lapsed.down?.message || null) : null;
    const dialog = (
        <Connect
            credentialType={open && way ? wayType(way) : null}
            integration={open && way ? way.integration : null}
            title={way && ask ? (open?.another ? 'Connect another account' : wayTitle(way, ask)) : undefined}
            description={why ?? undefined}
            others={ways.filter((w) => w.id !== way?.id).map((w) => ({ key: w.id, label: wayLabel(w), credentialType: wayType(w), onPick: () => setFocus(w.id) }))}
            client={client}
            onOpenChange={(o) => !o && setOpen(null)}
            onConnected={(id) => {
                setLanded(`credential:${id}`);
                rereadAccounts();
            }}
        />
    );
    return {
        connect: (harness, model, { another = false, on = null } = {}) => {
            setFocus(on ? `way:${on.kind}:${on.integration}` : null);
            setOpen({ harness, model, another });
        },
        dialog,
    };
}

// ── favourites ──────────────────────────────────────────────────────────────

const FAVORITES_KEY = 'nc-work-model-favorites';
const keyOf = (harness: HarnessName, model: string) => `${harness}::${model}`;

function useFavorites() {
    const [favorites, setFavorites] = useState<string[]>([]);
    useEffect(() => {
        try {
            const saved = JSON.parse(localStorage.getItem(FAVORITES_KEY) ?? '[]');
            if (Array.isArray(saved)) setFavorites(saved.filter((k): k is string => typeof k === 'string'));
        } catch {
            // Private windows and blocked storage start with none.
        }
    }, []);
    const toggle = (key: string) =>
        setFavorites((prev) => {
            const next = prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key];
            try {
                localStorage.setItem(FAVORITES_KEY, JSON.stringify(next));
            } catch {
                // Kept for this visit only.
            }
            return next;
        });
    return { favorites, toggle };
}

/** Shown before Show more: a harness's newest few, as t3code keeps the long tail behind it. */
const FIRST_MODELS = 8;

/** The pill by the box: the harness's mark, the model, then its effort muted (and Fast's bolt), and the account where
 *  more than one could run it. */
function Trigger({ pick: value, label, account, className, ...rest }: { pick: PickerValue; label: string; account?: ModelAccount; className?: string } & ButtonHTMLAttributes<HTMLButtonElement>) {
    return (
        <ShortcutTooltip label="Model, reasoning, speed and permissions">
            <button
                type="button"
                aria-label={`Model: ${label}${value.effort ? `, ${value.effort}` : ''}${value.speed === 'fast' ? ', fast' : ''}${account ? `, on ${accountTitle(account)}` : ''}`}
                className={cn(
                    'relative inline-flex h-7 min-w-0 items-center gap-1.5 rounded-full px-2.5 text-sm font-medium text-foreground/85 transition-[background-color,color,transform] duration-150 hover:bg-foreground/[0.05] hover:text-foreground active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70 data-[state=open]:bg-foreground/[0.07] data-[state=open]:text-foreground',
                    TAP_AREA,
                    className
                )}
                {...rest}
            >
                <HarnessMark harness={value.harness} className="h-4 w-4" />
                {/* Left-aligned: a button centres its text, and the name's old minimum width centred a short one away
                    from the mark. */}
                <span className="min-w-0 truncate text-left">{label}</span>
                {value.effort && <span className="shrink-0 font-normal text-muted-foreground">{capital(value.effort)}</span>}
                {value.speed === 'fast' && <Zap className="h-3 w-3 shrink-0 fill-current text-muted-foreground" strokeWidth={0} aria-hidden />}
                {/* Short of room, the account gives way before the model's name. */}
                {account && <span className={cn('min-w-0 max-w-[7rem] shrink-[4] truncate font-normal', downWord(account) ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>· {accountShort(account)}</span>}
            </button>
        </ShortcutTooltip>
    );
}

/** A model's plain name from its harness's list (`modelParts`), its id's last part until the list is read. */
export function useModelLabel(harness: HarnessInfo | undefined, model: string): string {
    const models = useHarnessModels(harness);
    return modelName(models.data?.find((m) => m.id === model)?.label, model);
}

/** t3code's model picker, on NoClick's harnesses, models and accounts. */
export function HarnessModelPicker({ value, onChange, choice, accounts, permissionModes, open: openProp, onOpenChange, triggerClassName, accountInPill = true, fundsOwner }: HarnessModelPickerProps) {
    const harnesses = useHarnesses();
    const harness = harnesses.data?.find((h) => h.name === value.harness);
    const label = useModelLabel(harness, value.model);
    const [ownOpen, setOwnOpen] = useState(false);
    const open = openProp ?? ownOpen;
    const setOpen = (o: boolean) => {
        setOwnOpen(o);
        onOpenChange?.(o);
    };
    const connecting = useConnectAi((account) => onChange({ ...value, account }));
    const connect = (on: HarnessInfo) => {
        setOpen(false);
        connecting.connect(on, value.model, { another: true });
    };
    const funds = useAddedFunds();
    // A pick that lacks funds opens Add funds in its place, and is made by itself once they land.
    const adding = useFundsThenSwitch<PickerValue>(fundsOwner ? `picker:${fundsOwner}` : null, async (next) => onChange(next));
    const needFunds = (model: CostlyModel, next: PickerValue) => {
        setOpen(false);
        adding.open(model, next);
    };
    // The pill names the account where there's a choice of more than one, and always one that stopped working.
    const usable = accounts && harness ? accountChoices(accounts, harness).filter((a) => !accountRefusal(a, harness, value.model, label)) : [];
    const down = accounts?.find((a) => a.id === value.account && downWord(a));
    const shownAccount = !accountInPill ? undefined : (down ?? (usable.length > 1 ? usable.find((a) => a.id === value.account) : undefined));
    const sheetHost = useContext(PickerSheetHost);
    const dialog = (
        <>
            {connecting.dialog}
            {adding.dialog}
        </>
    );
    const body = (sheet?: boolean) =>
        harnesses.data ? (
            <PickerBody
                value={value}
                onChange={onChange}
                harnesses={harnesses.data}
                choice={choice}
                accounts={accounts}
                permissionModes={permissionModes}
                onConnect={connect}
                onClose={() => setOpen(false)}
                funds={funds}
                onNeedsFunds={needFunds}
                sheet={sheet}
            />
        ) : (
            <p className="w-[300px] p-4 text-sm text-muted-foreground">{harnesses.error !== undefined ? 'Couldn’t load the harnesses.' : 'Loading…'}</p>
        );
    if (sheetHost)
        return (
            <>
                <Trigger pick={value} label={label} account={shownAccount} className={triggerClassName} data-state={open ? 'open' : 'closed'} onClick={() => setOpen(!open)} />
                {open &&
                    createPortal(
                        <div className="absolute inset-0 z-40 flex flex-col justify-end">
                            <button type="button" aria-label="Close" onClick={() => setOpen(false)} className="absolute inset-0 bg-black/50" />
                            <div role="dialog" aria-label="Model" className="relative flex max-h-[78%] flex-col rounded-t-[26px] bg-composer pb-[env(safe-area-inset-bottom)] ring-1 ring-inset ring-border dark:ring-foreground/[0.09]">
                                <span aria-hidden className="mx-auto mt-2 h-1 w-9 shrink-0 rounded-full bg-foreground/20" />
                                {body(true)}
                            </div>
                        </div>,
                        sheetHost
                    )}
                {dialog}
            </>
        );
    return (
        <>
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger asChild>
                    <Trigger pick={value} label={label} account={shownAccount} className={triggerClassName} data-state={open ? 'open' : 'closed'} />
                </PopoverTrigger>
                <PopoverContent side="top" align="end" sideOffset={10} className={cn('work-rise w-auto overflow-hidden rounded-2xl p-0', MENU_SURFACE)}>
                    {body()}
                </PopoverContent>
            </Popover>
            {dialog}
        </>
    );
}

function PickerBody({
    value,
    onChange,
    harnesses,
    choice,
    accounts,
    permissionModes,
    onConnect,
    onClose,
    funds,
    onNeedsFunds,
    sheet,
}: {
    value: PickerValue;
    onChange: (next: PickerValue) => void;
    harnesses: HarnessInfo[];
    choice?: AccountChoice | null;
    accounts?: ModelAccount[];
    permissionModes?: PermissionMode[];
    onConnect: (harness: HarnessInfo) => void;
    onClose: () => void;
    /** The funds the account added (`useAddedFunds`). */
    funds: number | null | undefined;
    /** A pick that lacks them (`next`, its costly `model`): Add funds opens in its place. */
    onNeedsFunds: (model: CostlyModel, next: PickerValue) => void;
    sheet?: boolean;
}) {
    const { favorites, toggle } = useFavorites();
    const ordered = useMemo(() => HARNESSES.flatMap(({ id }) => harnesses.filter((h) => h.name === id)), [harnesses]);
    const current = ordered.find((h) => h.name === value.harness) ?? ordered[0];
    const [rail, setRail] = useState<HarnessName | 'favorites'>(value.harness);
    // The harness whose models are listed; null on Favourites.
    const shown = rail === 'favorites' ? null : (ordered.find((h) => h.name === rail) ?? null);
    const [query, setQuery] = useState('');
    const [more, setMore] = useState<Partial<Record<HarnessName, boolean>>>({});
    const [active, setActive] = useState(0);
    const search = useRef<HTMLInputElement>(null);
    const searching = query.trim().length > 0;
    const listed = useHarnessModels(shown ?? undefined);
    const found = useModelSearch(ordered, query);

    const rows: Row[] = useMemo(() => {
        const row = (harness: HarnessName, m: Pick<HarnessModel, 'id' | 'label' | 'canonical' | 'noclickKey'>): Row => ({
            harness, model: m.id, label: m.label ?? m.id, canonical: m.canonical, needsFunds: m.noclickKey?.needsFundsUsd ?? null, outputUsdPerMillion: m.noclickKey?.outputUsdPerMillion ?? null,
        });
        if (searching) return namedRows(found.data ?? [], (x) => row(x.harness, x.model)).sort((a, b) => Number(favorites.includes(keyOf(b.harness, b.model))) - Number(favorites.includes(keyOf(a.harness, a.model))));
        if (!shown)
            return favorites.flatMap((k) => {
                const [harness, model] = k.split('::') as [HarnessName, string];
                return ordered.some((h) => h.name === harness) ? [{ harness, model, label: modelName(null, model) }] : [];
            });
        const all = namedRows(listed.data ?? [], (m) => row(shown.name, m));
        return more[shown.name] ? all : all.slice(0, FIRST_MODELS);
    }, [searching, found.data, shown, listed.data, more, favorites, ordered]);
    const hasMore = !searching && !!shown && (listed.data?.length ?? 0) > FIRST_MODELS;

    // What picking a row lacks: the funds its model needs on NoClick's key, when the account `pick` takes is that key.
    // The model already picked lacks nothing: an agent on it keeps running.
    const lacks = (row: Row): number | null => {
        const target = ordered.find((h) => h.name === row.harness);
        if (!target || !row.needsFunds || (row.harness === value.harness && row.model === value.model)) return null;
        return fundsShort(row.needsFunds, accounts ? firstUsable(accounts, target, row.model, value.account) : runsUnpicked(target, null), funds);
    };
    const pick = (row: Row) => {
        const target = ordered.find((h) => h.name === row.harness);
        if (!target) return;
        const next: PickerValue = row.harness === value.harness ? { ...value, model: row.model } : onHarness(value, target, row.model);
        // The account it was on while that still runs it, else the first that does.
        if (accounts) next.account = firstUsable(accounts, target, next.model, value.account)?.id ?? null;
        const short = lacks(row);
        if (short) return onNeedsFunds({ name: modelName(row.label, row.model), outputUsdPerMillion: row.outputUsdPerMillion ?? null, needsUsd: short }, next);
        onChange(next);
    };
    useEffect(() => setActive(0), [query, rail]);
    useEffect(() => {
        search.current?.focus();
    }, []);

    // ⌘1–⌘9 pick the models listed, while the picker is open.
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (!(e.metaKey || e.ctrlKey) || e.altKey || e.shiftKey || !/^[1-9]$/.test(e.key)) return;
            const row = rows[Number(e.key) - 1];
            if (!row) return;
            e.preventDefault();
            e.stopPropagation();
            pick(row);
        };
        window.addEventListener('keydown', onKey, true);
        return () => window.removeEventListener('keydown', onKey, true);
    });

    const traits = current ? traitsOf(current) : { label: 'Effort', efforts: [], defaultEffort: null, speeds: [] };
    const currentName = useModelLabel(current, value.model);
    const { modes, note: modesNote } = modesOf(current, permissionModes);
    const mode = PERMISSION_MODES.find((m) => m.id === value.permissions) ?? PERMISSION_MODES[3];
    const ModeIcon = PERMISSION_ICON[mode.id];
    // The rail's selection bar follows the selected mark.
    const railRef = useRef<HTMLDivElement>(null);
    const [bar, setBar] = useState<number | null>(null);
    useLayoutEffect(() => {
        const item = railRef.current?.querySelector<HTMLElement>(`[data-rail="${searching ? '' : rail}"]`);
        setBar(item ? (sheet ? item.offsetLeft + item.offsetWidth / 2 - 10 : item.offsetTop + item.offsetHeight / 2 - 10) : null);
    }, [rail, searching, sheet]);

    // Each harness names itself past the picker's left edge, away from the models, with what the accounts say of it: not
    // connected (no account you hold runs it), or on NoClick's key (only that does). A phone's sheet has none.
    const tips = useRailTips();
    const stateOf = (name: HarnessName | null): string | null => {
        const harness = name && ordered.find((h) => h.name === name);
        if (!harness || !accounts) return null;
        const runs = accountChoices(accounts, harness).filter((a) => !accountRefusal(a, harness, harness.defaultModel, harness.defaultModel));
        return !runs.length ? 'not connected' : runs.every((a) => a.kind === 'noclick') ? 'on NoClick’s key' : null;
    };
    const tipFor = (el: HTMLElement, name: string, harness: HarnessName | null) => {
        const frame = el.closest('[data-radix-popper-content-wrapper]')?.firstElementChild ?? el.closest('[data-model-picker]') ?? el;
        return tipBeside(el, frame.getBoundingClientRect().left, 'left', name, stateOf(harness));
    };
    const railButton = (id: HarnessName | 'favorites', harness: HarnessName | null, content: ReactNode, name: string) => (
        <button
            key={id}
            type="button"
            data-rail={id}
            aria-label={name}
            aria-pressed={!searching && rail === id}
            onClick={() => {
                setRail(id);
                setQuery('');
                choice?.onCancel();
            }}
            onPointerEnter={(e) => !sheet && e.pointerType === 'mouse' && tips.hover(tipFor(e.currentTarget, name, harness))}
            onPointerLeave={() => tips.hide()}
            onPointerDown={() => tips.press()}
            onFocus={(e) => !sheet && e.currentTarget.matches(':focus-visible') && tips.focus(tipFor(e.currentTarget, name, harness))}
            onBlur={() => tips.hide()}
            className={cn(
                'relative grid h-8 w-8 shrink-0 place-items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70',
                !searching && rail === id ? 'bg-foreground/[0.09]' : 'hover:bg-foreground/[0.06]'
            )}
        >
            {content}
        </button>
    );

    const railEl = (
        <div ref={railRef} aria-label="Harnesses" className={cn('relative flex shrink-0 gap-1', sheet ? 'items-center overflow-x-auto px-3 py-2 scrollbar-hide' : 'w-12 flex-col items-center overflow-y-auto bg-foreground/[0.03] px-2 py-2 scrollbar-hide')}>
            {bar !== null && (
                <span
                    aria-hidden
                    className={cn('pointer-events-none absolute rounded-full bg-foreground transition-[top,left] duration-200 ease-out', sheet ? 'bottom-0.5 h-[3px] w-5' : 'right-0.5 h-5 w-[3px]')}
                    style={sheet ? { left: bar } : { top: bar }}
                />
            )}
            {railButton('favorites', null, <Star className="h-4 w-4 fill-current" strokeWidth={1.75} />, 'Favourites')}
            <span aria-hidden className={cn('shrink-0 bg-border dark:bg-foreground/[0.08]', sheet ? 'mx-1 h-5 w-px' : 'my-1 h-px w-6')} />
            {ordered.map((h) => railButton(h.name, h.name, <HarnessMark harness={h.name} className="h-4 w-4" />, harnessLabel(h.name)))}
        </div>
    );

    const loading = searching ? found.data === undefined && found.error === undefined : !!shown && listed.data === undefined && listed.error === undefined;
    const listEl = (
        <div className={cn('flex min-w-0 flex-1 flex-col', !sheet && 'w-[300px]')}>
            <label className="flex h-10 shrink-0 items-center gap-2 border-b border-border px-3.5 transition-colors focus-within:border-foreground/30 dark:border-foreground/[0.08] dark:focus-within:border-foreground/30">
                <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                <input
                    ref={search}
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                            e.preventDefault();
                            const n = rows.length;
                            if (n) setActive((i) => (i + (e.key === 'ArrowDown' ? 1 : n - 1)) % n);
                        } else if (e.key === 'Enter') {
                            e.preventDefault();
                            if (rows[active]) pick(rows[active]);
                        } else if (e.key === 'Escape') {
                            e.preventDefault();
                            onClose();
                        }
                    }}
                    placeholder="Search models…"
                    aria-label="Search models"
                    aria-controls="work-model-list"
                    aria-activedescendant={rows[active] ? `work-model-${active}` : undefined}
                    className="h-7 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70"
                />
            </label>
            <div id="work-model-list" role="listbox" aria-label="Models" className={cn('min-h-0 flex-1 overflow-y-auto p-1.5 scrollbar-subtle', sheet && 'max-h-[260px]')}>
                {rows.map((row, at) => {
                    const fav = favorites.includes(keyOf(row.harness, row.model));
                    const isCurrent = row.harness === value.harness && row.model === value.model;
                    const short = lacks(row);
                    return (
                        <div
                            key={keyOf(row.harness, row.model)}
                            id={`work-model-${at}`}
                            role="option"
                            tabIndex={-1}
                            aria-selected={isCurrent}
                            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && pick(row)}
                            onMouseMove={() => at !== active && setActive(at)}
                            onClick={() => pick(row)}
                            className={cn('group/row flex h-8 cursor-pointer items-center gap-2 rounded-xl pl-2 pr-1 text-sm', at === active && 'bg-foreground/[0.06]')}
                        >
                            <HarnessMark harness={row.harness} className="h-4 w-4" />
                            <span title={row.label} className={cn('min-w-0 truncate', row.note && 'max-w-[80%] shrink-0', isCurrent ? 'text-foreground' : 'text-foreground/85')}>{row.label}</span>
                            {row.note && <span className="min-w-0 truncate text-xs text-muted-foreground">{row.note}</span>}
                            {isCurrent && <Check className="h-3.5 w-3.5 shrink-0" strokeWidth={2.25} aria-hidden />}
                            <span className="ml-auto flex shrink-0 items-center gap-1">
                                {short && <span className="text-xs text-muted-foreground">{fundsTag(short)}</span>}
                                <button
                                    type="button"
                                    aria-label={fav ? `Remove ${row.label} from favourites` : `Add ${row.label} to favourites`}
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        toggle(keyOf(row.harness, row.model));
                                    }}
                                    className="grid h-6 w-6 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.08] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70"
                                >
                                    <Star
                                        className={cn('h-3 w-3', fav ? 'fill-current text-foreground' : 'opacity-0 group-hover/row:opacity-100 group-focus-visible/row:opacity-100 [@media(pointer:coarse)]:opacity-100', rail === 'favorites' && !searching && 'opacity-0 group-hover/row:opacity-100')}
                                        strokeWidth={2}
                                    />
                                </button>
                            </span>
                        </div>
                    );
                })}
                {hasMore && (
                    <button
                        type="button"
                        onClick={() => shown && setMore((m) => ({ ...m, [shown.name]: !m[shown.name] }))}
                        className="flex h-8 w-full items-center rounded-xl px-2 text-left text-sm text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70"
                    >
                        {shown && more[shown.name] ? 'Show less' : 'Show more'}
                    </button>
                )}
                {!rows.length && (
                    <p className="px-3 pb-6 pt-3 text-xs leading-relaxed text-muted-foreground">
                        {loading ? 'Loading…' : searching ? `No model matches “${query.trim()}”.` : shown ? 'It lists no models.' : 'Star a model to keep it here.'}
                    </p>
                )}
            </div>
        </div>
    );

    const effortEl = traits.efforts.length > 0 && (
        <div className={cn('flex shrink-0 flex-col bg-foreground/[0.02]', sheet ? 'border-t border-border dark:border-foreground/[0.08]' : 'w-48 border-l border-border dark:border-foreground/[0.08]')}>
            <p className={cn('flex shrink-0 items-center gap-2 px-3.5 text-xs', sheet ? 'h-8 pt-1' : 'h-10 border-b border-border dark:border-foreground/[0.08]')}>
                <span className="font-medium">{traits.label}</span>
                <span className="ml-auto truncate text-muted-foreground">{currentName}</span>
            </p>
            <div role="radiogroup" aria-label={traits.label} className={cn(sheet ? 'flex flex-wrap gap-1 px-3 pb-2' : 'min-h-0 flex-1 overflow-y-auto p-1.5 scrollbar-subtle')}>
                {traits.efforts.map((l) => {
                    const on = l === value.effort;
                    return (
                        <button
                            key={l}
                            type="button"
                            role="radio"
                            aria-checked={on}
                            onClick={() => onChange({ ...value, effort: l })}
                            className={cn(
                                'items-center text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70',
                                sheet ? cn('inline-flex h-7 rounded-full px-3', on ? 'bg-foreground text-background' : 'bg-foreground/[0.05] text-foreground/85') : cn('flex h-8 w-full gap-2 rounded-xl px-2.5 text-left hover:bg-foreground/[0.06]', on ? 'text-foreground' : 'text-foreground/80')
                            )}
                        >
                            <span className="min-w-0 truncate">{capital(l)}</span>
                            {!sheet && l === traits.defaultEffort && !on && <span className="text-[11px] text-muted-foreground/70">Default</span>}
                            {!sheet && on && <Check className="ml-auto h-3.5 w-3.5 shrink-0" strokeWidth={2.25} aria-hidden />}
                        </button>
                    );
                })}
            </div>
        </div>
    );

    const footerEl = (
        <div className={cn('flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1.5 border-t border-border bg-foreground/[0.02] px-3 py-2 dark:border-foreground/[0.08]', sheet && 'pb-5')}>
            {accounts && current && <AccountMenu value={value} harness={current} accounts={accounts} onChange={onChange} onConnect={onConnect} funds={funds} onNeedsFunds={onNeedsFunds} />}
            {traits.speeds.length > 1 && (
                <span role="radiogroup" aria-label="Speed" className="flex rounded-full bg-foreground/[0.06] p-0.5">
                    {traits.speeds.map((speed) => (
                        <button
                            key={speed}
                            type="button"
                            role="radio"
                            aria-checked={value.speed === speed}
                            onClick={() => onChange({ ...value, speed })}
                            className={cn(
                                'inline-flex h-6 items-center gap-1 rounded-full px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70',
                                value.speed === speed ? 'bg-foreground/[0.1] text-foreground' : 'text-muted-foreground hover:text-foreground'
                            )}
                        >
                            {speed === 'fast' && <Zap className="h-3 w-3 fill-current" strokeWidth={0} aria-hidden />}
                            {capital(speed)}
                        </button>
                    ))}
                </span>
            )}
            {modes.length > 0 && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        aria-label={`Permissions: ${mode.label}`}
                        className="ml-auto inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium text-foreground/85 transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70 data-[state=open]:bg-foreground/[0.07]"
                    >
                        <ModeIcon className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
                        {mode.label}
                        <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent side="top" align="end" sideOffset={8} className={cn('work-rise z-[90] w-[280px] rounded-2xl p-1.5', MENU_SURFACE)}>
                        {modesNote && <p className="px-2.5 pb-1.5 pt-1 text-xs leading-snug text-muted-foreground">{modesNote}</p>}
                        {modes.map((m) => {
                            const Icon = PERMISSION_ICON[m.id];
                            return (
                                <DropdownMenuItem key={m.id} onSelect={() => onChange({ ...value, permissions: m.id })} className="items-start gap-2.5 rounded-[10px] px-2.5 py-2">
                                    <Icon className="mt-0.5 h-4 w-4 text-muted-foreground" strokeWidth={2} />
                                    <span className="min-w-0 flex-1">
                                        <span className="block text-sm">{m.label}</span>
                                        <span className="block text-xs leading-snug text-muted-foreground">{m.note}</span>
                                    </span>
                                    {m.id === value.permissions && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2.25} />}
                                </DropdownMenuItem>
                            );
                        })}
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    );

    // Which of your accounts a move onto another harness runs on: in place of the models (and of the footer, which is
    // the harness it runs on now) until it's answered or another harness is opened.
    const choiceEl = choice && (
        <div role="group" aria-label={`Run ${harnessLabel(choice.harness.name)} on`} data-testid="account-choice" className={cn('flex min-w-0 flex-1 flex-col', !sheet && 'w-[300px]')}>
            <p className="flex h-10 shrink-0 items-center gap-1.5 border-b border-border pl-1.5 pr-3.5 text-sm dark:border-foreground/[0.08]">
                <button
                    type="button"
                    aria-label="Back to the models"
                    onClick={choice.onCancel}
                    className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70"
                >
                    <ArrowLeft className="h-3.5 w-3.5" strokeWidth={2} />
                </button>
                <HarnessMark harness={choice.harness.name} className="h-4 w-4" />
                <span className="min-w-0 truncate font-medium">Run {harnessLabel(choice.harness.name)} on</span>
            </p>
            <div className={cn('min-h-0 flex-1 overflow-y-auto p-1.5 scrollbar-subtle', sheet && 'max-h-[260px]')}>
                {choice.accounts.map((a) => (
                    <button
                        key={a.id}
                        type="button"
                        onClick={() => choice.onPick(a.id)}
                        className="flex w-full items-start gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors hover:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70"
                    >
                        <span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center">
                            <AccountMark account={a} className="h-4 w-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm">{accountTitle(a)}</span>
                            <span className="block truncate text-xs leading-snug text-muted-foreground">{a.note}</span>
                        </span>
                    </button>
                ))}
            </div>
        </div>
    );
    const panes = choiceEl ? (
        <>
            {railEl}
            {choiceEl}
        </>
    ) : (
        <>
            {railEl}
            {listEl}
            {effortEl}
        </>
    );

    return (
        <div className="relative flex flex-col" data-model-picker>
            {sheet ? panes : <div className="flex h-[300px]">{panes}</div>}
            {!choiceEl && footerEl}
            <RailTip tip={tips.tip} />
        </div>
    );
}

/** "Runs on" in the footer, opening every account the account holds for this harness and model: those that run it,
 *  NoClick's key where it reaches the harness (saying what to add when it runs a costly model the account hasn't the
 *  funds for, and opening Add funds when picked), then the rest greyed with why, then Connect another. */
function AccountMenu({
    value,
    harness,
    accounts,
    onChange,
    onConnect,
    funds,
    onNeedsFunds,
}: {
    value: PickerValue;
    harness: HarnessInfo;
    accounts: ModelAccount[];
    onChange: (next: PickerValue) => void;
    onConnect: (harness: HarnessInfo) => void;
    funds: number | null | undefined;
    onNeedsFunds: (model: CostlyModel, next: PickerValue) => void;
}) {
    const { labels } = useModelAccounts();
    const label = useModelLabel(harness, value.model);
    const { needsFunds, outputUsdPerMillion } = useModelRoutes(harness, value.model);
    const choices = accountChoices(accounts, harness);
    const refusal = (a: ModelAccount) => accountRefusal(a, harness, value.model, label);
    const runs = choices.filter((a) => !refusal(a) && a.kind !== 'noclick');
    const noclick = choices.find((a) => a.kind === 'noclick' && !refusal(a));
    // With none picked, the one it runs on, as the chip under the box names it.
    const current = value.account ? (choices.find((a) => a.id === value.account) ?? null) : runsUnpicked(harness, runs[0] ?? noclick ?? null);
    const refused = choices.filter((a) => !!refusal(a));
    const RULE = '-mx-1.5 my-1.5 bg-border dark:bg-foreground/[0.08]';
    const item = (a: ModelAccount) => {
        const why = refusal(a);
        // A move onto NoClick's key from another account is a switch onto it.
        const short = a.kind === 'noclick' && current?.kind !== 'noclick' ? fundsShort(needsFunds, a, funds) : null;
        return (
            <DropdownMenuItem key={a.id} disabled={!!why} onSelect={() => (short ? onNeedsFunds({ name: label, outputUsdPerMillion, needsUsd: short }, { ...value, account: a.id }) : onChange({ ...value, account: a.id }))} className="items-start gap-2.5 rounded-[10px] px-2.5 py-2">
                <span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center">
                    <AccountMark account={a} className="h-4 w-4" />
                </span>
                <span className="min-w-0 flex-1">
                    <span className="block text-sm">{a.kind === 'noclick' ? 'NoClick’s key · at cost' : accountTitle(a)}</span>
                    <span className="block text-xs leading-snug text-muted-foreground">{why ?? (short ? fundsNote(short) : a.note)}</span>
                </span>
                {a.id === value.account && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2.25} />}
            </DropdownMenuItem>
        );
    };
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                aria-label={`Runs on: ${current ? accountTitle(current) : 'no account yet'}`}
                className="inline-flex h-7 min-w-0 max-w-[16rem] items-center gap-1.5 rounded-full px-2.5 text-xs font-medium text-foreground/85 transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70 data-[state=open]:bg-foreground/[0.07]"
            >
                <span className="shrink-0 font-normal text-muted-foreground">Runs on</span>
                {current && <AccountMark account={current} className="h-3.5 w-3.5" />}
                <span className={cn('truncate', !current && 'text-muted-foreground')}>{current ? accountTitle(current) : 'Connect an account'}</span>
                <ChevronUp className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
            </DropdownMenuTrigger>
            {/* However many accounts there are, it fits the screen: the heading and Connect stay, the accounts scroll. */}
            <DropdownMenuContent
                side="top"
                align="start"
                sideOffset={8}
                collisionPadding={12}
                className={cn('work-rise z-[90] flex max-h-[min(28rem,var(--radix-dropdown-menu-content-available-height))] w-[340px] flex-col rounded-2xl p-1.5', MENU_SURFACE)}
            >
                <DropdownMenuLabel className="flex shrink-0 items-center gap-1.5 px-2.5 pb-1 pt-1 text-xs font-normal text-muted-foreground">
                    <HarnessMark harness={value.harness} className="h-3.5 w-3.5" />
                    {runs.length || noclick ? `${harnessLabel(value.harness)} · ${label}` : `${needsAccount(harness, value.model, label, labels)}.`}
                </DropdownMenuLabel>
                <div className="-mx-1.5 min-h-0 flex-1 overflow-y-auto px-1.5 scrollbar-subtle">
                    {runs.map(item)}
                    {noclick && runs.length > 0 && <DropdownMenuSeparator className={RULE} />}
                    {noclick && item(noclick)}
                    {refused.length > 0 && <DropdownMenuSeparator className={RULE} />}
                    {refused.map(item)}
                </div>
                <DropdownMenuSeparator className={cn(RULE, 'shrink-0')} />
                <DropdownMenuItem onSelect={() => onConnect(harness)} className="shrink-0 gap-2.5 rounded-[10px] px-2.5 py-2 text-sm text-muted-foreground">
                    <Plus className="h-4 w-4" strokeWidth={2} />
                    Connect another…
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
