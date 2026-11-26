// New agent's first footer chip: the account the pick runs on. Its menu lists the accounts that run it, one line each
// (a plan by its email, its logo saying which plan, with its tier, a meter of what's left and a line saying how much
// is used and when it resets: the plan used read fresh as the menu opens, for the pick's model), then the ones of yours
// that don't, folded into one row (why each can't is its tooltip; a broken one says so and opens Connections), then
// Connect another; with none, the chip says what's missing and the menu asks for it as Send does. A popover on a laptop,
// a sheet from the bottom on a phone, each no taller than the room it has; the pill says it once the plan is nearly
// used. An agent that exists has one row more, what it does when a plan runs out (`modelSwitching`), which opens in
// place: switch or wait, and, switching, which accounts it may move to (every plan on and every paid key off is the
// platform's default rule). One spacing rule throughout: the menu's padding is also the gap around each divider.
import { useContext, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeftRight, Check, ChevronDown, ChevronLeft, ChevronRight, Ellipsis, Plus, RotateCw } from 'lucide-react';
import type { HarnessInfo, ModelSwitching, PlanUsage, PlanWindow } from 'noclick';
import { BrandIcon } from '@/ui/BrandIcon';
import { BUTTON_PRIMARY } from '@/ui/buttons';
import { MENU_SURFACE } from '@/ui/menus';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { cn } from '@/ui/utils';
import { useConnectionMarks } from '@/ui/connectionMark';
import { HarnessMark, harnessLabel } from '../agents/harness';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { accountChoices, accountRefusal, chipLabel, downWord, isPlanAccount, menuTitle, namesAccount, routeFor, switchChoices, wayLabel, wayType, type ConnectAsk, type ModelAccount, type Way, wayShort } from './accounts';
import { useWorkFrames } from '@/sdk/live';
import { rereadAccounts } from './catalog';
import { PickerSheetHost } from './ModelPicker';
import { useWork } from '../context';
import { useNow, usePlanUsage, UsageLine, UsageMeter } from './PlanUsage';
import { planShortfall, windowsTitle } from './planWords';

/** An account's or a way's mark: the app's own icon for its credential type, coloured where its brand is (Claude's
 *  spark), else in the ink around it; NoClick's for its key. */
export function AccountGlyph({ a, className = 'h-4 w-4' }: { a: Pick<ModelAccount, 'kind' | 'integration'>; className?: string }) {
    const marks = useConnectionMarks();
    if (a.kind === 'noclick') return <HarnessMark harness="sdk" className={className} />;
    const icon = marks.glyph(wayType(a));
    return <BrandIcon Icon={icon.Icon} iconColor={icon.iconColor || 'text-current'} className={cn('shrink-0', className)} />;
}

/** An account's mark on its round tile: NoClick's key on black, as NoClick's own mark always is; the others on a wash.
 *  A small one in a row keeps the row's lead slot (`slot`), so every name in the menu starts on one line. */
function Mark({ a, size, slot = false, className }: { a: Pick<ModelAccount, 'kind' | 'integration'>; size: 20 | 24; slot?: boolean; className?: string }) {
    const noclick = a.kind === 'noclick';
    return (
        <span
            aria-hidden
            data-mark={noclick ? 'noclick' : undefined}
            className={cn('grid shrink-0 place-items-center rounded-full', noclick ? 'bg-black' : 'bg-foreground/[0.06] ring-1 ring-inset ring-foreground/[0.06]', size === 24 ? 'h-6 w-6 max-sm:h-8 max-sm:w-8' : 'h-5 w-5', slot && size === 20 && 'mx-0.5 max-sm:mx-1.5', className)}
        >
            {/* NoClick's mark is a white glyph a light theme inverts: kept white here, on black, in either theme. */}
            <AccountGlyph a={a} className={cn(size === 24 ? 'h-[13px] w-[13px] max-sm:h-4 max-sm:w-4' : 'h-[11px] w-[11px]', noclick && '[filter:invert(0)]')} />
        </span>
    );
}

/** A footer chip; on a phone the strip around it takes its taps too, so it's a finger's 40px without growing. */
export const FOOT_CHIP =
    "inline-flex h-7 max-w-[220px] items-center gap-1.5 rounded-full px-2 relative max-md:gap-1 max-md:px-1.5 max-md:after:absolute max-md:after:inset-x-0 max-md:after:-inset-y-1.5 max-md:after:content-[''] text-[12.5px] text-muted-foreground  transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground";

export interface AccountChipProps {
    harness: HarnessInfo;
    model: string;
    /** The model as a person reads it ("Sonnet 5.5"). */
    modelLabel: string;
    accounts: readonly ModelAccount[];
    /** The one it runs on; null when none runs it. */
    account: ModelAccount | null;
    /** Each id that reaches the model, the pick's own first: an account runs it by any. */
    routes: readonly string[];
    /** A free model of Zen's own tier, by name, where it runs with no account; else null. */
    free: string | null;
    /** Whether the person picked it (else it's the first that runs the pick). */
    picked: boolean;
    ask: ConnectAsk;
    ways: readonly Way[];
    onPick: (id: string) => void;
    /** Opens Connect: on the ask's way when none runs it, else to connect another. */
    onConnect: (another: boolean) => void;
    /** Its kind alone ("Claude plan"), the account itself in its tooltip and menu: a row with no room to spare. */
    compact?: boolean;
    /** Its mark alone, everything else in its tooltip: a row out of room. */
    folded?: boolean;
    /** Its kind in a word ("Claude"), the account in full in its name and menu: a phone's row, where no tooltip opens. */
    brief?: boolean;
    /** An agent that exists: what it does when a plan runs out, and the change to it (saved at once). */
    switching?: { value: Required<ModelSwitching>; onChange: (next: Required<ModelSwitching>) => void };
}

/** The account in full, as its tooltip says it: "Your Claude plan · rowan@example.com". */
const accountInFull = (a: ModelAccount) => [chipLabel(a), a.email && !a.name?.includes(a.email) ? a.email : null].filter(Boolean).join(' · ');

export function AccountChip(props: AccountChipProps) {
    const { account, ask } = props;
    const [open, setOpen] = useState(false);
    const sheet = useContext(PickerSheetHost);
    // NoClick's last reading for the pick, read again on its plan's usage frame: never judged from the accounts'
    // list, whose summaries aren't read again as a plan is used.
    const kept = usePlanUsage(account, props.model);
    const short = account && !downWord(account) ? planShortfall(kept.data) : null;
    const plain = account ? chipLabel(account) : props.free ? 'No account needed' : ask.empty;
    const label = short ? `${plain} · ${short}` : plain;
    const kind = account && (props.compact || props.folded || props.brief) ? [props.brief ? wayShort(account) : wayLabel(account), downWord(account)].filter(Boolean).join(' · ') : plain;
    const shown = short ? `${kind} · ${short}` : kind;
    const tip = props.compact || props.folded ? `Runs on ${account ? accountInFull(account) : label}` : undefined;
    const icon = account ? (
        <AccountGlyph a={account} className="h-3.5 w-3.5" />
    ) : props.free ? (
        <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" strokeWidth={2.25} />
    ) : ask.lapsed ? (
        <span className="relative">
            <AccountGlyph a={ask.lapsed} className="h-3.5 w-3.5 opacity-60" />
            <span className="absolute -bottom-0.5 -right-0.5 h-1.5 w-1.5 rounded-full bg-red-500" />
        </span>
    ) : (
        <span aria-hidden className="h-3.5 w-3.5 rounded-full border-[1.5px] border-dashed border-foreground/40" />
    );
    const trigger = (
        <button type="button" aria-label={`Runs on: ${label}`} onClick={sheet ? () => setOpen(!open) : undefined} data-state={open ? 'open' : 'closed'} className={cn(FOOT_CHIP, props.folded && 'w-7 justify-center px-0')}>
            {icon}
            {!props.folded && (
                <>
                    <span className={cn('truncate', account && (downWord(account) && props.compact ? 'text-red-600 dark:text-red-400' : short ? 'text-foreground' : 'text-foreground/85'))}>{shown}</span>
                    <ChevronDown className="h-3 w-3 shrink-0 opacity-70 max-md:hidden" strokeWidth={2} />
                </>
            )}
        </button>
    );
    const body = (
        <AccountMenu
            {...props}
            kept={kept.data}
            onPick={(id) => {
                props.onPick(id);
                setOpen(false);
            }}
            onConnect={(another) => {
                setOpen(false);
                props.onConnect(another);
            }}
            onClose={() => setOpen(false)}
        />
    );
    if (sheet)
        return (
            <>
                <ShortcutTooltip label={tip} side="top">
                    {trigger}
                </ShortcutTooltip>
                {open &&
                    createPortal(
                        <div className="absolute inset-0 z-40 flex flex-col justify-end">
                            <button type="button" aria-label="Close" onClick={() => setOpen(false)} className="absolute inset-0 bg-black/50" />
                            <div role="dialog" aria-label="Runs on" className="relative flex max-h-[85%] flex-col rounded-t-[26px] bg-composer px-1.5 pb-6 pt-2 ring-1 ring-inset ring-border dark:ring-foreground/[0.09]">
                                <span aria-hidden className="mx-auto mb-2 mt-0.5 block h-1 w-9 shrink-0 rounded-full bg-foreground/20" />
                                {body}
                            </div>
                        </div>,
                        sheet
                    )}
            </>
        );
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <ShortcutTooltip label={tip} side="top">
                <PopoverTrigger asChild>{trigger}</PopoverTrigger>
            </ShortcutTooltip>
            <PopoverContent
                role="dialog"
                aria-label="Runs on"
                align="start"
                side="bottom"
                sideOffset={8}
                collisionPadding={12}
                className={cn('flex max-h-[min(30rem,var(--radix-popover-content-available-height))] w-[288px] flex-col rounded-[20px] p-1.5', MENU_SURFACE)}
            >
                {body}
            </PopoverContent>
        </Popover>
    );
}

// At the footer chips' scale on a laptop; a step up on a phone, where the menu is a sheet. Rows round at 14px inside
// the menu's 20px corner and 6px padding, so a highlight sits evenly inside the curve.
const ROW = 'flex w-full items-center gap-2.5 rounded-[14px] px-2 py-1.5 text-left transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring max-sm:gap-3 max-sm:py-2';
const MAIN = 'block truncate text-[12.5px] font-medium leading-5 max-sm:text-[14px]';
const HEAD = 'px-2 pb-0.5 pt-1.5 text-[11.5px] text-muted-foreground max-sm:text-[12.5px]';
const VALUE = 'shrink-0 text-[12.5px] text-muted-foreground max-sm:text-[14px]';
/** A rule between the menu's parts, edge to edge, with the menu's own padding above and below it. */
const DIVIDER = '-mx-1.5 my-1.5 h-px shrink-0 bg-border dark:bg-foreground/[0.08]';
const TILE = 'grid h-6 w-6 shrink-0 place-items-center rounded-full bg-foreground/[0.06] ring-1 ring-inset ring-foreground/[0.06] max-sm:h-8 max-sm:w-8';

/** Why the account that ran the pick stopped, and what brings it back: its provider's refusal, or its sign-in. */
function lapsedLine(a: ModelAccount): string {
    if (a.down?.reason === 'signed_out' || a.kind === 'claude_plan' || a.kind === 'chatgpt_plan') return `Your ${wayLabel(a)} was signed out${a.email ? ` (${a.email})` : ''}. Sign in again and it runs on it.`;
    return `${a.down?.message || `Your ${wayLabel(a)} was disconnected.`} Reconnect it and it runs on it.`;
}

/** A plan's tier beside its name ("Ultra", "Plus"), where NoClick has read one. */
function Tier({ a }: { a: ModelAccount }) {
    const tier = isPlanAccount(a) ? a.plan?.label : null;
    return tier ? <span className="h-[18px] shrink-0 rounded-full bg-foreground/[0.07] px-[7px] text-[11.5px] font-normal leading-[18px] text-foreground/70">{tier}</span> : null;
}

function AccountMenu({ harness, model, modelLabel, accounts, account, routes, free, ask, ways, onPick, onConnect, onClose, kept, switching }: AccountChipProps & { kept?: PlanUsage; onClose: () => void }) {
    // The plan used, read fresh as the menu opens: the windows that can stop this model, the tightest on its row. The
    // other plans show their summaries, read again as it opens and, while it's open, as another plan's usage moves (a
    // usage frame re-reads the list only here, and never for the plan used, whose own read follows it).
    const fresh = usePlanUsage(account, model, { fresh: true });
    useEffect(() => {
        rereadAccounts();
    }, []);
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'plan_usage' && frame.id !== account?.connectionId && frame.id !== account?.id) rereadAccounts();
    });
    const now = useNow();
    const { openPage } = useWork();
    const used = fresh.data ?? kept;
    // The window that stops a plan first, and every window its meter's title names.
    const windowOf = (a: ModelAccount) => (!isPlanAccount(a) || downWord(a) ? null : (a.id === account?.id ? used?.tightest : null) ?? a.usage?.tightest ?? null);
    const windowsOf = (a: ModelAccount) => (a.id === account?.id && used?.windows.length ? used.windows : [windowOf(a)].filter((w) => !!w));
    const runs = accountChoices(accounts, harness).filter((a) => routeFor(a, harness, routes));
    const not = accounts.filter((a) => !runs.some((r) => r.id === a.id));
    const broken = not.filter((a) => downWord(a)).length;
    // Folded unless nothing runs the pick, when they're what there is to see.
    const [othersOpen, setOthersOpen] = useState(() => !runs.length);
    const [view, setView] = useState<'accounts' | 'switching'>('accounts');
    // Coming back from the switching view, the accounts slide in from the left and its row has focus again.
    const [returned, setReturned] = useState(false);
    const switchingRow = useRef<HTMLButtonElement>(null);
    useEffect(() => {
        if (view === 'accounts' && returned) switchingRow.current?.focus();
    }, [view, returned]);
    // Only a coding harness runs on a plan; a rule already set stays reachable to undo.
    const showSwitching = !!switching && harness.name !== 'sdk' && (accounts.some(isPlanAccount) || switching.value.mode === 'stay' || !!switching.value.allowed);
    const any = new Intl.ListFormat('en', { type: 'disjunction' }).format(ways.map((w) => (isPlanAccount(w) ? `a ${wayLabel(w)}` : `${/^[aeiou]/i.test(wayLabel(w)) ? 'an' : 'a'} ${wayLabel(w)}`)));

    if (view === 'switching' && switching)
        return (
            <SwitchingView
                accounts={accounts}
                harness={harness}
                account={account}
                value={switching.value}
                onChange={switching.onChange}
                onBack={() => {
                    setReturned(true);
                    setView('accounts');
                }}
            />
        );
    return (
        <>
            <div className={cn('-mx-1.5 min-h-0 flex-1 overflow-y-auto px-1.5 scrollbar-subtle', returned && 'animate-in fade-in slide-in-from-left-2 duration-200 motion-reduce:animate-none')}>
                <p className={HEAD}>Runs on</p>
                {free && !runs.length && (
                    <div className={cn(ROW, 'hover:bg-transparent')}>
                        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-emerald-500/[0.12] max-sm:h-8 max-sm:w-8">
                            <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" strokeWidth={2.25} />
                        </span>
                        <span className="min-w-0 flex-1">
                            <span className={MAIN}>No account needed</span>
                            <span className="block text-[11.5px] leading-snug text-muted-foreground max-sm:text-[12.5px]">{free} is free on OpenCode Zen</span>
                        </span>
                    </div>
                )}
                {runs.map((a) => {
                    const w = windowOf(a);
                    return (
                        <button key={a.id} type="button" role="menuitemradio" aria-checked={a.id === account?.id} onClick={() => onPick(a.id)} className={cn(ROW, w && 'items-start')}>
                            <Mark a={a} size={24} />
                            <span className="min-w-0 flex-1">
                                <span className="flex min-h-6 items-center gap-1.5 max-sm:min-h-8">
                                    <span className={cn(MAIN, 'min-w-0')}>{menuTitle(a)}</span>
                                    <Tier a={a} />
                                    <span className="flex-1" />
                                    {w ? <UsageMeter w={w} title={windowsTitle(windowsOf(a), now)} /> : !isPlanAccount(a) && <span className={VALUE}>Per use</span>}
                                </span>
                                {w && <UsageLine w={w} now={now} />}
                            </span>
                            <Check className={cn('h-3.5 w-3.5 shrink-0', w && 'mt-[5px] max-sm:mt-[9px]', a.id !== account?.id && 'invisible')} strokeWidth={2.25} />
                        </button>
                    );
                })}
                {!runs.length && !free && (
                    <p className="px-2 pb-1.5 pt-0.5 text-[12.5px] leading-snug text-foreground/90 max-sm:text-[13.5px]">
                        {ask.lapsed
                            ? lapsedLine(ask.lapsed)
                            : ways.length
                              ? `Nothing you’ve connected runs it yet. It runs on ${any}.`
                              : 'Nothing you’ve connected runs it yet.'}
                    </p>
                )}
                {not.length > 0 && (
                    <>
                        <div className={DIVIDER} />
                        <button type="button" aria-expanded={othersOpen} onClick={() => setOthersOpen(!othersOpen)} className={ROW}>
                            <span className={cn(TILE, 'relative')}>
                                <Ellipsis className="h-3.5 w-3.5" strokeWidth={2} />
                                {broken > 0 && <span aria-hidden className="absolute -bottom-px -right-px h-2 w-2 rounded-full bg-red-500 ring-2 ring-composer" />}
                            </span>
                            <span className={cn(MAIN, 'min-w-0 flex-1')}>
                                {not.length === 1 ? '1 other can’t run this' : `${not.length} others can’t run this`}
                                {broken > 0 && <span className="sr-only">{`, ${broken} stopped working`}</span>}
                            </span>
                            <span className="flex shrink-0">
                                {not.slice(0, 3).map((a, i) => (
                                    <span key={a.id} className={cn('rounded-full ring-2 ring-composer', i > 0 && '-ml-[7px]')}>
                                        <Mark a={a} size={20} />
                                    </span>
                                ))}
                            </span>
                            <ChevronDown className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-300 motion-reduce:transition-none', othersOpen && 'rotate-180')} strokeWidth={2} />
                        </button>
                        <div className={cn('grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none', othersOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')} inert={!othersOpen} data-testid="others">
                            <div className="min-h-0 overflow-hidden">
                                {not.map((a) => (
                                    <OtherRow
                                        key={a.id}
                                        a={a}
                                        w={windowOf(a)}
                                        now={now}
                                        why={accountRefusal(a, harness, model, modelLabel)}
                                        onFix={
                                            openPage
                                                ? () => {
                                                      onClose();
                                                      openPage('connections', { view: 'connected', account: null });
                                                  }
                                                : undefined
                                        }
                                    />
                                ))}
                            </div>
                        </div>
                    </>
                )}
                {showSwitching && (
                    <>
                        <div className={DIVIDER} />
                        <button ref={switchingRow} type="button" onClick={() => setView('switching')} className={ROW}>
                            <span className={TILE}>
                                <ArrowLeftRight className="h-3.5 w-3.5" strokeWidth={2} />
                            </span>
                            <span className={cn(MAIN, 'min-w-0 flex-1')}>When a plan runs out</span>
                            <span className={VALUE}>{switching!.value.mode === 'stay' ? 'Waits' : 'Switches'}</span>
                            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" strokeWidth={2} />
                        </button>
                    </>
                )}
            </div>
            <div className={DIVIDER} />
            <div className="shrink-0" data-testid="account-menu-foot">
                {runs.length || free ? (
                    <button type="button" onClick={() => onConnect(true)} className={cn(ROW, 'text-foreground/85 hover:text-foreground')}>
                        <span className={TILE}>
                            <Plus className="h-3.5 w-3.5" strokeWidth={2} />
                        </span>
                        <span className="text-[12.5px] font-medium max-sm:text-[14px]">Connect another</span>
                    </button>
                ) : (
                    <button type="button" onClick={() => onConnect(false)} className={cn(BUTTON_PRIMARY, 'h-8 w-full justify-center text-[12.5px] max-sm:h-10 max-sm:text-[14px]')}>
                        {ask.lapsed ? <RotateCw className="h-3.5 w-3.5" strokeWidth={2} /> : null}
                        {ask.send.replace(/ to start$/, '')}
                    </button>
                )}
            </div>
        </>
    );
}

/** One of yours that can't run the pick, under the folded row: its name (a plan its usage line too), why it can't as
 *  its tooltip, and one that stopped working a way to fix it in Connections (else the word for how it stopped). */
function OtherRow({ a, w, now, why, onFix }: { a: ModelAccount; w: PlanWindow | null; now: Date; why: string | null; onFix?: () => void }) {
    const down = downWord(a);
    return (
        <div title={why ?? undefined} className={cn('flex min-h-8 gap-2.5 px-2 py-1 max-sm:gap-3 max-sm:py-1.5', w ? 'items-start' : 'items-center')}>
            <Mark a={a} size={20} slot className={cn(!down && 'opacity-60', w && 'mt-0.5')} />
            <span className="min-w-0 flex-1">
                <span className="flex min-h-6 items-center gap-1.5">
                    <span className={cn('min-w-0 truncate text-[12.5px] leading-5 max-sm:text-[13.5px]', down ? 'text-foreground' : 'text-muted-foreground')}>{menuTitle(a)}</span>
                    <Tier a={a} />
                </span>
                {w && <UsageLine w={w} now={now} />}
                {why && <span className="sr-only">{why}</span>}
            </span>
            {down &&
                (onFix ? (
                    <button type="button" onClick={onFix} className="h-[22px] shrink-0 rounded-full bg-foreground/[0.06] px-2.5 text-[11.5px] font-medium ring-1 ring-inset ring-foreground/[0.06] transition-colors hover:bg-foreground/[0.11]">
                        {a.down?.reason === 'signed_out' || isPlanAccount(a) ? 'Sign in' : 'Reconnect'}
                    </button>
                ) : (
                    <span className="shrink-0 text-[11.5px] text-red-600 dark:text-red-400">{down}</span>
                ))}
        </div>
    );
}

const MODES = [
    { mode: 'switch', label: 'Switch' },
    { mode: 'stay', label: 'Wait' },
] as const;

/** What it does when a plan runs out, opened from its row: Switch or Wait, and, switching, the accounts it may move to,
 *  each a toggle. Every plan on and every paid key off is the platform's default rule (`allowed` null: any of your
 *  plans, a paid key once you say so); anything else is the set it moves between freely, a paid key among them without
 *  asking. Anything the set names that it couldn't move to now (an account no longer connected) stays a row of its own,
 *  so it can be turned off; turning the last one off is Wait. */
function SwitchingView({ accounts, harness, account, value, onChange, onBack }: { accounts: readonly ModelAccount[]; harness: HarnessInfo; account: ModelAccount | null; value: Required<ModelSwitching>; onChange: (next: Required<ModelSwitching>) => void; onBack: () => void }) {
    const backButton = useRef<HTMLButtonElement>(null);
    useEffect(() => backButton.current?.focus(), []);
    const allowed = value.allowed ?? [];
    const choices = switchChoices(accounts, harness);
    const rows = [
        ...choices.map((a) => ({ key: a.id, account: a as ModelAccount | null, title: menuTitle(a), refs: allowed.filter((ref) => namesAccount(a, ref)), plan: isPlanAccount(a), gone: false })),
        ...allowed
            .filter((ref) => !choices.some((a) => namesAccount(a, ref)))
            .map((ref) => {
                const held = accounts.find((a) => namesAccount(a, ref)) ?? null;
                return { key: ref, account: held, title: held ? menuTitle(held) : ref, refs: [ref], plan: !!held && isPlanAccount(held), gone: true };
            }),
    ];
    type Row = (typeof rows)[number];
    const isOn = (row: Row) => (value.allowed ? row.refs.length > 0 : row.plan && !row.gone);
    const toggle = (row: Row) => {
        const on = rows.filter((r) => (r === row ? !isOn(r) : isOn(r)));
        if (!on.length) return onChange({ ...value, mode: 'stay' });
        const plans = rows.filter((r) => r.plan && !r.gone);
        const theDefault = on.length === plans.length && on.every((r) => plans.includes(r));
        onChange({ ...value, mode: 'switch', allowed: theDefault ? null : on.flatMap((r) => (r.refs.length ? r.refs : [r.key])) });
    };
    const note = (row: Row) => (row.gone ? 'Not connected' : row.account && account?.id === row.account.id ? 'In use now' : row.plan ? null : isOn(row) ? 'Used without asking' : 'Asks you first');
    return (
        <div role="group" aria-label="When a plan runs out" data-testid="when-a-plan-runs-out" className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle animate-in fade-in slide-in-from-right-2 duration-200 motion-reduce:animate-none">
            <div className="flex items-center gap-2 py-0.5 pl-1.5">
                <button ref={backButton} type="button" aria-label="Back" onClick={onBack} className="grid h-7 w-7 shrink-0 place-items-center rounded-full transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring max-sm:h-8 max-sm:w-8">
                    <ChevronLeft className="h-4 w-4" strokeWidth={2} />
                </button>
                <span className={MAIN}>When a plan runs out</span>
            </div>
            <div role="radiogroup" aria-label="When a plan runs out" className="relative my-1 grid grid-cols-2 rounded-full bg-foreground/[0.06] p-0.5">
                <span aria-hidden className={cn('absolute inset-y-0.5 left-0.5 w-[calc(50%-2px)] rounded-full bg-composer shadow-[0_1px_2px_rgba(0,0,0,0.12)] transition-transform duration-300 ease-out motion-reduce:transition-none dark:bg-foreground/[0.11] dark:shadow-none dark:ring-1 dark:ring-inset dark:ring-foreground/[0.07]', value.mode === 'stay' && 'translate-x-full')} />
                {MODES.map(({ mode, label }) => (
                    <button key={mode} type="button" role="radio" aria-checked={value.mode === mode} onClick={() => mode !== value.mode && onChange({ ...value, mode })} className={cn('relative h-7 rounded-full text-[12.5px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring max-sm:h-9 max-sm:text-[14px]', value.mode === mode ? 'text-foreground' : 'text-muted-foreground hover:text-foreground')}>
                        {label}
                    </button>
                ))}
            </div>
            {value.mode === 'switch' ? (
                <>
                    <p className={HEAD}>Can switch to</p>
                    {rows.map((row) => {
                        const on = isOn(row);
                        const sub = note(row);
                        return (
                            <button key={row.key} type="button" role="switch" aria-checked={on} aria-label={row.title} onClick={() => toggle(row)} className={ROW}>
                                {row.account ? <Mark a={row.account} size={20} slot /> : <span aria-hidden className="mx-0.5 h-5 w-5 shrink-0 rounded-full border-[1.5px] border-dashed border-foreground/40 max-sm:mx-1.5" />}
                                <span className="min-w-0 flex-1">
                                    <span className="block truncate text-[12.5px] leading-5 max-sm:text-[14px]">{row.title}</span>
                                    {sub && <span className="block text-[11.5px] leading-snug text-muted-foreground max-sm:text-[12.5px]">{sub}</span>}
                                </span>
                                <span aria-hidden className={cn('relative h-4 w-7 shrink-0 rounded-full transition-colors', on ? 'bg-foreground' : 'bg-foreground/[0.16]')}>
                                    <span className={cn('absolute left-0.5 top-0.5 h-3 w-3 rounded-full transition-transform duration-200 motion-reduce:transition-none', on ? 'translate-x-3 bg-composer' : 'bg-composer shadow-[0_1px_2px_rgba(0,0,0,0.2)] dark:bg-foreground dark:shadow-none')} />
                                </span>
                            </button>
                        );
                    })}
                </>
            ) : (
                <p className="px-2 pb-1.5 pt-1 text-[11.5px] leading-snug text-muted-foreground max-sm:text-[12.5px]">Waits for the plan to reset, then carries on where it stopped.</p>
            )}
        </div>
    );
}
