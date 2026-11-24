// The harness and model picker: a pill by the box that opens the agents by name beside a search over the open agent's
// models, the picked model's effort on a slider where it has one to set, and at its foot the account it runs on, Fast
// and its permissions. A phone opens the same as a sheet, the agents on a shelf that scrolls sideways. Shared by the
// New agent draft, an agent's own box and the Chat page's, so it only takes a value and reports changes; the
// harnesses, models and accounts it lists are the platform's (catalog.ts), and an account that can't run a model says
// why (accounts.ts). An agent's box moves it onto another harness from here, and asks in place which account it runs on
// there (`choice`). A costly model on NoClick's key that the account hasn't added the funds for says what to add, and
// picking it opens Add funds (funds.tsx).
import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeft, Check, ChevronUp, KeyRound, Plus, Search, Star, X, Zap } from 'lucide-react';
import type { HarnessInfo, HarnessName, PermissionMode } from 'noclick';
import { BrandIcon } from '@/ui/BrandIcon';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { evenStops, RollText, StopSlider } from '@/ui/StopSlider';
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
    /** The efforts the harness takes on the model picked (a conversation's settings: none where the model has none to
     *  set) and the one it thinks at unasked; the harness's own for its default model when left out. */
    efforts?: readonly string[];
    defaultEffort?: string | null;
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

/** A phone's layer for the model and account sheets: over the whole page, empty until one opens. `host` goes to
 *  `PickerSheetHost`, `layer` anywhere on the page; neither on a laptop. */
export function usePickerSheets(phone: boolean): { host: HTMLElement | null; layer: ReactNode } {
    const [layer, setLayer] = useState<HTMLElement | null>(null);
    return { host: phone ? layer : null, layer: phone ? <div ref={setLayer} className="pointer-events-none fixed inset-0 z-50 [&>*]:pointer-events-auto" /> : null };
}

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
 *  (the plan signed out, else the best), the others as "Or run it on" pills. What lands is picked (by the ref the dialog
 *  hands back, the one an agent takes it by: `credential:<id>`, or a named connection's name) as soon as the account
 *  list reads it connected. The state lives in the host, which outlives the dialog. */
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
            onConnected={({ ref }) => {
                setLanded(ref);
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

/** Shown before Show more: a harness's newest few, the long tail kept behind it. */
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

export function HarnessModelPicker({ value, onChange, choice, accounts, permissionModes, efforts, defaultEffort, open: openProp, onOpenChange, triggerClassName, accountInPill = true, fundsOwner }: HarnessModelPickerProps) {
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
                efforts={efforts}
                defaultEffort={defaultEffort}
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
                <PopoverContent side="top" align="end" sideOffset={10} className={cn('work-rise w-auto overflow-hidden rounded-[20px] p-0', MENU_SURFACE)}>
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
    efforts: modelEfforts,
    defaultEffort,
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
    efforts?: readonly string[];
    defaultEffort?: string | null;
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
    // A laptop opens in the search. A sheet, or a touch screen, opens on its models: the search there would raise the
    // keyboard over them.
    useEffect(() => {
        if (!sheet && !window.matchMedia('(pointer: coarse)').matches) search.current?.focus();
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
    // The picked model's own efforts where they're known (a conversation's), else its harness's.
    const efforts = modelEfforts ?? traits.efforts;
    const usualEffort = (modelEfforts ? defaultEffort : undefined) ?? traits.defaultEffort;
    const { modes, note: modesNote } = modesOf(current, permissionModes);
    const mode = PERMISSION_MODES.find((m) => m.id === value.permissions) ?? PERMISSION_MODES[3];
    const ModeIcon = PERMISSION_ICON[mode.id];
    // The highlight slides to the open agent: over its row on a laptop, behind its tab on a phone's shelf, which keeps it
    // in view.
    const railRef = useRef<HTMLDivElement>(null);
    const [lit, setLit] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
    const shelved = useRef(false);
    useLayoutEffect(() => {
        const item = railRef.current?.querySelector<HTMLElement>(`[data-rail="${searching ? '' : rail}"]`);
        setLit(item ? { x: item.offsetLeft, y: item.offsetTop, w: item.offsetWidth, h: item.offsetHeight } : null);
        if (sheet && item) railRef.current?.scrollTo?.({ left: item.offsetLeft - 44, behavior: shelved.current ? 'smooth' : 'auto' });
        shelved.current = true;
    }, [rail, searching, sheet, ordered.length]);

    // An agent's name is on its row. What the accounts say of it shows past the picker's left edge on hover: not
    // connected (no account you hold runs it), or on NoClick's key (only that does). A phone's sheet has none.
    const tips = useRailTips();
    const stateOf = (name: HarnessName | null): string | null => {
        const harness = name && ordered.find((h) => h.name === name);
        if (!harness || !accounts || sheet) return null;
        const runs = accountChoices(accounts, harness).filter((a) => !accountRefusal(a, harness, harness.defaultModel, harness.defaultModel));
        return !runs.length ? 'not connected' : runs.every((a) => a.kind === 'noclick') ? 'on NoClick’s key' : null;
    };
    const tipFor = (el: HTMLElement, name: string, state: string) => {
        const frame = el.closest('[data-radix-popper-content-wrapper]')?.firstElementChild ?? el.closest('[data-model-picker]') ?? el;
        return tipBeside(el, frame.getBoundingClientRect().left, 'left', name, state);
    };
    const railButton = (id: HarnessName | 'favorites', harness: HarnessName | null, face: ReactNode, name: string) => {
        const on = !searching && rail === id;
        const state = stateOf(harness);
        return (
            <button
                key={id}
                type="button"
                data-rail={id}
                aria-label={name}
                aria-pressed={on}
                onClick={() => {
                    setRail(id);
                    setQuery('');
                    choice?.onCancel();
                }}
                onPointerEnter={(e) => state && e.pointerType === 'mouse' && tips.hover(tipFor(e.currentTarget, name, state))}
                onPointerLeave={() => tips.hide()}
                onPointerDown={() => tips.press()}
                onFocus={(e) => state && e.currentTarget.matches(':focus-visible') && tips.focus(tipFor(e.currentTarget, name, state))}
                onBlur={() => tips.hide()}
                className={cn(
                    'relative z-[1] flex shrink-0 items-center whitespace-nowrap text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70',
                    // On the shelf Starred is its star alone; an agent is its mark and its name.
                    sheet ? cn('h-9 gap-[7px] rounded-full font-medium', harness ? 'px-3' : 'w-9 justify-center') : 'h-[34px] w-full gap-2.5 rounded-[14px] px-2.5 text-left',
                    on ? 'text-foreground' : 'text-foreground/70 hover:text-foreground'
                )}
            >
                <span className="grid h-4 w-4 shrink-0 place-items-center">{face}</span>
                {(harness || !sheet) && <span className="truncate">{name}</span>}
            </button>
        );
    };

    const railEl = (
        <div
            ref={railRef}
            aria-label="Harnesses"
            className={cn(
                'relative flex shrink-0 scrollbar-hide',
                sheet
                    ? '-mx-2 items-center gap-0.5 overflow-x-auto px-2 py-1.5 [mask-image:linear-gradient(90deg,#000_calc(100%-28px),transparent)]'
                    : 'w-[168px] flex-col overflow-y-auto border-r border-border p-1.5 dark:border-foreground/[0.08]'
            )}
        >
            {lit && (
                <span
                    aria-hidden
                    className={cn(
                        'pointer-events-none absolute left-0 top-0 duration-300 [transition-timing-function:cubic-bezier(.3,.8,.3,1)] motion-reduce:transition-none',
                        sheet ? 'rounded-full bg-foreground/[0.1] transition-[transform,width]' : 'rounded-[14px] bg-foreground/[0.06] transition-transform'
                    )}
                    style={{ transform: `translate(${lit.x}px, ${lit.y}px)`, width: lit.w, height: lit.h }}
                />
            )}
            {railButton('favorites', null, <Star className="h-4 w-4 fill-current" strokeWidth={1.75} />, 'Starred')}
            {ordered.map((h) => railButton(h.name, h.name, <HarnessMark harness={h.name} className="h-4 w-4" />, harnessLabel(h.name)))}
        </div>
    );

    const loading = searching ? found.data === undefined && found.error === undefined : !!shown && listed.data === undefined && listed.error === undefined;
    const searchEl = (
        <label
            className={cn(
                'flex shrink-0 items-center gap-2 rounded-full bg-foreground/[0.06] pl-3 pr-1 text-muted-foreground transition-[background-color,box-shadow] focus-within:bg-foreground/[0.08] focus-within:shadow-[inset_0_0_0_1px_hsl(var(--foreground)/0.16)]',
                sheet ? 'h-10' : 'h-[34px]'
            )}
        >
            <Search className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
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
                placeholder="Search models"
                aria-label="Search models"
                aria-controls="work-model-list"
                aria-activedescendant={rows[active] ? `work-model-${active}` : undefined}
                // 16px on a phone, so iOS doesn't zoom the page in when it's tapped.
                className={cn('h-7 min-w-0 flex-1 bg-transparent text-foreground outline-none placeholder:text-muted-foreground/70', sheet ? 'text-base' : 'text-sm')}
            />
            {query && (
                <button
                    type="button"
                    aria-label="Clear the search"
                    onClick={() => {
                        setQuery('');
                        search.current?.focus();
                    }}
                    className="grid h-[26px] w-[26px] shrink-0 place-items-center rounded-full transition-colors hover:bg-foreground/[0.1] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70"
                >
                    <X className="h-3.5 w-3.5" strokeWidth={2} />
                </button>
            )}
        </label>
    );
    const ROW = sheet ? 'h-11 pl-3 text-[15px]' : 'h-[34px] pl-2.5 text-sm';
    const rowsEl = (
        <div id="work-model-list" role="listbox" aria-label="Models" className={cn('overflow-y-auto scrollbar-subtle', sheet ? 'mt-0.5 max-h-[264px]' : 'mt-1.5 min-h-0 flex-1')}>
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
                        // Under a thumb nothing is "the row the keys are on" until a search is typed.
                        className={cn('group/row flex cursor-pointer items-center gap-2 rounded-[14px] pr-1', ROW, at === active && (!sheet || searching) && 'bg-foreground/[0.06]')}
                    >
                        <HarnessMark harness={row.harness} className="h-4 w-4" />
                        <span title={row.label} className={cn('min-w-0 truncate', row.note && 'max-w-[80%] shrink-0', isCurrent ? 'text-foreground' : 'text-foreground/85')}>{row.label}</span>
                        {row.note && <span className="min-w-0 truncate text-xs text-muted-foreground">{row.note}</span>}
                        {isCurrent && <Check className="h-3.5 w-3.5 shrink-0" strokeWidth={2.25} aria-hidden />}
                        <span className="ml-auto flex shrink-0 items-center gap-1">
                            {short && <span className="text-xs text-muted-foreground">{fundsTag(short)}</span>}
                            <button
                                type="button"
                                aria-label={fav ? `Remove ${row.label} from starred` : `Star ${row.label}`}
                                aria-pressed={fav}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    toggle(keyOf(row.harness, row.model));
                                }}
                                className={cn(
                                    'grid place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.08] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/70',
                                    sheet ? 'h-[34px] w-[34px]' : 'h-7 w-7'
                                )}
                            >
                                <Star
                                    className={cn(
                                        sheet ? 'h-4 w-4' : 'h-3.5 w-3.5',
                                        fav ? 'fill-current text-foreground' : 'opacity-0 group-hover/row:opacity-100 group-focus-visible/row:opacity-100 [@media(pointer:coarse)]:opacity-100',
                                        rail === 'favorites' && !searching && 'opacity-0 group-hover/row:opacity-100'
                                    )}
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
                    className={cn(
                        'flex w-full items-center rounded-[14px] text-left text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70',
                        ROW
                    )}
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
    );

    const effortEl = (
        <EffortSlider
            label={traits.label}
            efforts={efforts}
            value={value.effort ?? usualEffort}
            scope={`${value.harness}:${value.model}`}
            onChange={(effort) => onChange({ ...value, effort })}
            sheet={sheet}
        />
    );

    // The foot holds the account, Fast and the permissions; a harness with none of them has no foot.
    const fast = traits.speeds.includes('fast') && traits.speeds.length > 1;
    const footerEl = ((accounts && current) || fast || modes.length > 0) && (
        <div className={cn('flex shrink-0 items-center border-t border-border dark:border-foreground/[0.08]', sheet ? 'gap-1.5 px-2 pb-5 pt-2' : 'gap-1 p-1.5')}>
            {accounts && current && <AccountMenu value={value} harness={current} accounts={accounts} onChange={onChange} onConnect={onConnect} funds={funds} onNeedsFunds={onNeedsFunds} sheet={sheet} />}
            {fast && (
                <button
                    type="button"
                    aria-pressed={value.speed === 'fast'}
                    onClick={() => onChange({ ...value, speed: value.speed === 'fast' ? (traits.speeds.find((s) => s !== 'fast') ?? null) : 'fast' })}
                    className={cn(footChip(sheet), value.speed === 'fast' && 'bg-foreground/[0.1] text-foreground hover:bg-foreground/[0.1]')}
                >
                    <Zap className={cn('h-3 w-3 fill-current', value.speed !== 'fast' && 'text-muted-foreground')} strokeWidth={0} aria-hidden />
                    Fast
                </button>
            )}
            {modes.length > 0 && (
                <DropdownMenu>
                    <DropdownMenuTrigger aria-label={`Permissions: ${mode.label}`} className={cn(footChip(sheet), 'ml-auto')}>
                        <ModeIcon className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />
                        {mode.label}
                        {!sheet && <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />}
                    </DropdownMenuTrigger>
                    <DropdownMenuContent side="top" align="end" sideOffset={8} className={cn('work-rise z-[90] w-[280px] rounded-[20px] p-1.5', MENU_SURFACE)}>
                        {modesNote && <p className="px-2.5 pb-1.5 pt-1 text-xs leading-snug text-muted-foreground">{modesNote}</p>}
                        {modes.map((m) => {
                            const Icon = PERMISSION_ICON[m.id];
                            return (
                                <DropdownMenuItem key={m.id} onSelect={() => onChange({ ...value, permissions: m.id })} className="items-start gap-2.5 rounded-[14px] px-2.5 py-2">
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

    // Which of your accounts a move onto another harness runs on: in place of the search, the models and the effort (and
    // of the foot, which is the harness it runs on now) until it's answered or another harness is opened.
    const choiceEl = choice && (
        <div role="group" aria-label={`Run ${harnessLabel(choice.harness.name)} on`} data-testid="account-choice" className={cn('flex min-w-0 flex-1 flex-col', !sheet && 'p-1.5')}>
            <p className="flex h-[34px] shrink-0 items-center gap-1.5 text-sm">
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
            <div className={cn('mt-1.5 min-h-0 flex-1 overflow-y-auto scrollbar-subtle', sheet && 'max-h-[264px]')}>
                {choice.accounts.map((a) => (
                    <button
                        key={a.id}
                        type="button"
                        onClick={() => choice.onPick(a.id)}
                        className="flex w-full items-start gap-2.5 rounded-[14px] px-2.5 py-2 text-left transition-colors hover:bg-foreground/[0.06] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70"
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

    return (
        <div className={cn('relative flex flex-col', sheet ? !choiceEl && !footerEl && 'pb-4' : 'w-[504px]')} data-model-picker>
            {sheet ? (
                // A phone's sheet: the search, the agents on a shelf that scrolls sideways, then the models and the effort.
                <div className={cn('flex min-h-0 flex-col px-2 pt-1.5', choiceEl && 'pb-4')}>
                    {!choiceEl && searchEl}
                    {railEl}
                    {choiceEl ?? (
                        <>
                            {rowsEl}
                            {effortEl}
                        </>
                    )}
                </div>
            ) : (
                // A laptop's popover: the agents by name, then the search over the open agent's models and the effort.
                <div className="flex h-[330px]">
                    {railEl}
                    {choiceEl ?? (
                        <div className="flex min-w-0 flex-1 flex-col p-1.5">
                            {searchEl}
                            {rowsEl}
                            {effortEl}
                        </div>
                    )}
                </div>
            )}
            {!choiceEl && footerEl}
            <RailTip tip={tips.tip} />
        </div>
    );
}

/** A chip in the picker's foot: bare on a laptop, on a wash of its own under a thumb. */
const footChip = (sheet?: boolean) =>
    cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full font-medium text-foreground/85 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/70 data-[state=open]:text-foreground',
        sheet ? 'h-[34px] bg-foreground/[0.05] px-2.5 text-[13.5px] data-[state=open]:bg-foreground/[0.1]' : 'h-7 px-2.5 text-xs hover:bg-foreground/[0.06] data-[state=open]:bg-foreground/[0.07]'
    );

/** The picked model's effort, set on the slider where the model has one to set. Without, it folds away, keeping what it
 *  showed while it goes. A level let go on shows until the value read back says it, or doesn't take it. */
function EffortSlider({ label, efforts, value, scope, onChange, sheet }: { label: string; efforts: readonly string[]; value: string | null; /** What the effort is of: a level sent for one model never shows on another. */ scope: string; onChange: (effort: string) => void; sheet?: boolean }) {
    const [preview, setPreview] = useState<string | null>(null);
    const [sent, setSent] = useState<{ level: string; scope: string } | null>(null);
    useEffect(() => {
        if (!sent) return;
        if (sent.level === value || sent.scope !== scope) {
            setSent(null);
            return;
        }
        const t = setTimeout(() => setSent(null), 4000);
        return () => clearTimeout(t);
    }, [sent, value, scope]);
    const open = efforts.length > 0;
    const at = preview ?? (sent?.scope === scope ? sent.level : null) ?? value;
    const kept = useRef<{ label: string; efforts: readonly string[]; value: string } | null>(null);
    if (open) kept.current = { label, efforts, value: at !== null && efforts.includes(at) ? at : efforts[0] };
    const shown = kept.current;
    return (
        <div
            data-testid="effort"
            data-open={open}
            className={cn(
                'grid shrink-0 motion-reduce:transition-none',
                open
                    ? 'visible grid-rows-[1fr] opacity-100 [transition:grid-template-rows_.32s_cubic-bezier(.3,.8,.3,1),opacity_.24s_ease]'
                    : 'invisible grid-rows-[0fr] opacity-0 [transition:grid-template-rows_.32s_cubic-bezier(.3,.8,.3,1),opacity_.24s_ease,visibility_0s_.32s]'
            )}
        >
            <div className="min-h-0 overflow-hidden">
                {shown && (
                    <div className={cn('mt-1.5 border-t border-border px-4 pb-0.5 pt-2.5 dark:border-foreground/[0.08]', sheet ? '-mx-2' : '-mx-1.5')}>
                        <p className="flex items-baseline gap-2 text-xs">
                            <span className="text-muted-foreground">{shown.label}</span>
                            <RollText className="ml-auto text-foreground" text={capital(shown.value)} order={shown.efforts.indexOf(shown.value)} testId="effort-level" />
                        </p>
                        <StopSlider
                            stops={evenStops(shown.efforts)}
                            value={shown.value}
                            onPreview={setPreview}
                            onCommit={(level) => {
                                setPreview(null);
                                if (level === value) return;
                                setSent({ level, scope });
                                onChange(level);
                            }}
                            label={shown.label}
                            valueText={capital(shown.value)}
                        />
                    </div>
                )}
            </div>
        </div>
    );
}

/** The account it runs on, in the foot, opening every account the account holds for this harness and model: those that run it,
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
    sheet,
}: {
    value: PickerValue;
    harness: HarnessInfo;
    accounts: ModelAccount[];
    onChange: (next: PickerValue) => void;
    onConnect: (harness: HarnessInfo) => void;
    funds: number | null | undefined;
    onNeedsFunds: (model: CostlyModel, next: PickerValue) => void;
    sheet?: boolean;
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
            <DropdownMenuItem key={a.id} disabled={!!why} onSelect={() => (short ? onNeedsFunds({ name: label, outputUsdPerMillion, needsUsd: short }, { ...value, account: a.id }) : onChange({ ...value, account: a.id }))} className="items-start gap-2.5 rounded-[14px] px-2.5 py-2">
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
            <DropdownMenuTrigger aria-label={`Runs on: ${current ? accountTitle(current) : 'no account yet'}`} className={cn(footChip(sheet), 'min-w-0 max-w-[16rem] shrink')}>
                {current ? <AccountMark account={current} className="h-3.5 w-3.5" /> : <span aria-hidden className="h-3.5 w-3.5 shrink-0 rounded-full border-[1.5px] border-dashed border-foreground/40" />}
                <span className={cn('truncate', !current && 'text-muted-foreground')}>{current ? accountTitle(current) : 'Connect an account'}</span>
                {!sheet && <ChevronUp className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />}
            </DropdownMenuTrigger>
            {/* However many accounts there are, it fits the screen: the heading and Connect stay, the accounts scroll. */}
            <DropdownMenuContent
                side="top"
                align="start"
                sideOffset={8}
                collisionPadding={12}
                className={cn('work-rise z-[90] flex max-h-[min(28rem,var(--radix-dropdown-menu-content-available-height))] w-[340px] flex-col rounded-[20px] p-1.5', MENU_SURFACE)}
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
                <DropdownMenuItem onSelect={() => onConnect(harness)} className="shrink-0 gap-2.5 rounded-[14px] px-2.5 py-2 text-sm text-muted-foreground">
                    <Plus className="h-4 w-4" strokeWidth={2} />
                    Connect another…
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
