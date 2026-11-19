// New agent's first footer chip: the account the pick runs on. Its menu lists the accounts that run it (the one used,
// and why), the ones of yours that don't (with why), and Connect another; with none, the chip says what's missing and
// the menu asks for it as Send does. A popover on a laptop, a sheet from the bottom on a phone, each no taller than
// the room it has: the accounts scroll, the accounts that run the pick at their top, and Connect stays at its foot.
// A plan names its tier beside it and shows its usage: the one used, every window that can stop the pick (read fresh as
// the menu opens); the others, the window that stops them first; and the pill says it once the plan is nearly used.
// An agent that exists says there what it does when a plan runs out (`modelSwitching`): switch by itself or stay and
// wait for the reset, and, switching, the accounts it may move between (none checked: the platform's default rule).
import { useContext, useEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ArrowLeftRight, Check, ChevronDown, Hourglass, Plus, RotateCw } from 'lucide-react';
import type { HarnessInfo, ModelSwitching, PlanUsage } from 'noclick';
import { BrandIcon } from '@/ui/BrandIcon';
import { BUTTON_PRIMARY } from '@/ui/buttons';
import { MENU_SURFACE } from '@/ui/menus';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { cn } from '@/ui/utils';
import { useConnectionMarks } from '@/ui/connectionMark';
import { HarnessMark, harnessLabel } from '../agents/harness';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { accountChoices, accountRefusal, accountTitle, chipLabel, downWord, isPlanAccount, namesAccount, NOCLICK_KEY, routeFor, switchChoices, wayLabel, wayType, type ConnectAsk, type ModelAccount, type Way, wayShort } from './accounts';
import { useWorkFrames } from '@/sdk/live';
import { rereadAccounts } from './catalog';
import { PickerSheetHost } from './ModelPicker';
import { usePlanUsage, UsageWindows } from './PlanUsage';
import { planShortfall } from './planWords';

/** An account's or a way's mark: the app's own icon for its credential type, coloured where its brand is (Claude's
 *  spark), else in the ink around it; NoClick's for its key. */
export function AccountGlyph({ a, className = 'h-4 w-4' }: { a: Pick<ModelAccount, 'kind' | 'integration'>; className?: string }) {
    const marks = useConnectionMarks();
    if (a.kind === 'noclick') return <HarnessMark harness="sdk" className={className} />;
    const icon = marks.glyph(wayType(a));
    return <BrandIcon Icon={icon.Icon} iconColor={icon.iconColor || 'text-current'} className={cn('shrink-0', className)} />;
}

/** An account's mark on its round tile: NoClick's key on black, as NoClick's own mark always is; the others on a wash. */
function Mark({ a, size }: { a: Pick<ModelAccount, 'kind' | 'integration'>; size: 20 | 24 }) {
    const noclick = a.kind === 'noclick';
    return (
        <span
            aria-hidden
            data-mark={noclick ? 'noclick' : undefined}
            className={cn('grid shrink-0 place-items-center rounded-full', noclick ? 'bg-black' : 'bg-foreground/[0.06] ring-1 ring-inset ring-foreground/[0.06]', size === 24 ? 'h-6 w-6 max-sm:h-8 max-sm:w-8' : 'h-5 w-5')}
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
                            <div role="dialog" aria-label="Runs on" className="relative flex max-h-[85%] flex-col rounded-t-[26px] bg-composer p-2 pb-6 ring-1 ring-inset ring-border dark:ring-foreground/[0.09]">
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
                className={cn('flex max-h-[min(30rem,var(--radix-popover-content-available-height))] w-[288px] flex-col rounded-[20px] p-1', MENU_SURFACE)}
            >
                {body}
            </PopoverContent>
        </Popover>
    );
}

// At the footer chips' scale on a laptop; a step up on a phone, where the menu is a sheet.
const ROW = 'flex w-full items-center gap-2.5 rounded-[14px] px-2 py-1.5 text-left transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring max-sm:gap-3 max-sm:py-2';
const MAIN = 'block truncate text-[12.5px] font-medium leading-5 max-sm:text-[14px]';
const SUB = 'block text-[11.5px] leading-snug text-muted-foreground max-sm:text-[12.5px]';
const HEAD = 'px-2 pb-0.5 pt-1.5 text-[11.5px] text-muted-foreground max-sm:text-[12.5px]';

/** Why the account that ran the pick stopped, and what brings it back: its provider's refusal, or its sign-in. */
function lapsedLine(a: ModelAccount): string {
    if (a.down?.reason === 'signed_out' || a.kind === 'claude_plan' || a.kind === 'chatgpt_plan') return `Your ${wayLabel(a)} was signed out${a.email ? ` (${a.email})` : ''}. Sign in again and it runs on it.`;
    return `${a.down?.message || `Your ${wayLabel(a)} was disconnected.`} Reconnect it and it runs on it.`;
}

/** An account's name in a row, with its plan's tier beside it ("Ultra", "Plus") where NoClick has read one. */
function RowTitle({ a, className }: { a: ModelAccount; className: string }) {
    const tier = isPlanAccount(a) ? a.plan?.label : null;
    return (
        <span className="flex min-w-0 items-center gap-1.5">
            <span className={cn(className, 'min-w-0')}>{chipLabel(a)}</span>
            {tier && <span className="h-[18px] shrink-0 rounded-full bg-foreground/[0.07] px-[7px] text-[11.5px] font-normal leading-[18px] text-foreground/70">{tier}</span>}
        </span>
    );
}

/** A plan's window that stops it first, for a row that isn't the one used. */
const tightestOf = (a: ModelAccount) => (isPlanAccount(a) && a.usage?.tightest ? [a.usage.tightest] : []);

/** The accounts that run the pick (the one used, and why), the ones that don't (with why), then Connect another. */
const SWITCH_MODES = [
    { mode: 'switch', label: 'Switch', note: 'Moves to another of your plans by itself, asks before a paid key', Icon: ArrowLeftRight },
    { mode: 'stay', label: 'Stay', note: 'Waits for the reset', Icon: Hourglass },
] as const;

/** What it does when a plan runs out: Switch or Stay, and, switching, only between the accounts checked (none: any of
 *  your plans, and a paid key once you say so). The choices are what it could move to (`switchChoices`); anything else
 *  the set names (an account no longer connected, one shared with you) stays a checked row of its own, so unchecking
 *  it, and the last, gets back to the default rule. */
function SwitchingSection({ accounts, harness, value, onChange }: { accounts: readonly ModelAccount[]; harness: HarnessInfo; value: Required<ModelSwitching>; onChange: (next: Required<ModelSwitching>) => void }) {
    const allowed = value.allowed ?? [];
    const choices = switchChoices(accounts, harness);
    const rows = [
        ...choices.map((a) => ({ key: a.id, account: a as ModelAccount | null, title: accountTitle(a), refs: allowed.filter((ref) => namesAccount(a, ref)) })),
        ...allowed
            .filter((ref) => !choices.some((a) => namesAccount(a, ref)))
            .map((ref) => {
                const held = accounts.find((a) => namesAccount(a, ref)) ?? null;
                return { key: ref, account: held, title: held ? accountTitle(held) : `${ref} (not connected)`, refs: [ref] };
            }),
    ];
    const toggle = (row: (typeof rows)[number]) => {
        const next = row.refs.length ? allowed.filter((ref) => !row.refs.includes(ref)) : [...allowed, row.key];
        onChange({ mode: value.mode, allowed: next.length ? next : null });
    };
    return (
        <div role="group" aria-label="When a plan runs out" data-testid="when-a-plan-runs-out">
            <p className={cn(HEAD, 'mt-0.5 border-t border-border pt-2 dark:border-foreground/[0.08]')}>When a plan runs out</p>
            {SWITCH_MODES.map(({ mode, label, note, Icon }) => (
                <button key={mode} type="button" role="menuitemradio" aria-checked={value.mode === mode} onClick={() => mode !== value.mode && onChange({ mode, allowed: value.allowed })} className={ROW}>
                    <span aria-hidden className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-foreground/[0.06] ring-1 ring-inset ring-foreground/[0.06] max-sm:h-8 max-sm:w-8">
                        <Icon className="h-3.5 w-3.5" strokeWidth={2} />
                    </span>
                    <span className="min-w-0 flex-1">
                        <span className={MAIN}>{label}</span>
                        <span className={SUB}>{note}</span>
                    </span>
                    <Check className={cn('h-3.5 w-3.5 shrink-0', value.mode !== mode && 'invisible')} strokeWidth={2.25} />
                </button>
            ))}
            {value.mode === 'switch' && (
                <>
                    <p className={cn(HEAD, 'pt-2')}>Only switch between</p>
                    {rows.map((row) => (
                        <label key={row.key} className={cn(ROW, 'cursor-pointer')}>
                            <input type="checkbox" checked={row.refs.length > 0} onChange={() => toggle(row)} className="h-[15px] w-[15px] shrink-0 accent-foreground" />
                            {row.account ? <Mark a={row.account} size={20} /> : <span aria-hidden className="h-5 w-5 shrink-0 rounded-full border-[1.5px] border-dashed border-foreground/40" />}
                            <span className="min-w-0 flex-1 truncate text-[12.5px] leading-5 max-sm:text-[14px]">{row.title}</span>
                        </label>
                    ))}
                    <p className="px-2 pb-1.5 pt-0.5 text-[11.5px] leading-snug text-muted-foreground max-sm:text-[12.5px]">
                        {allowed.length ? 'Only these, a paid key among them without asking' : 'None checked: any of your plans, and a paid key once you say so'}
                    </p>
                </>
            )}
        </div>
    );
}

function AccountMenu({ harness, model, modelLabel, accounts, account, routes, free, picked, ask, ways, onPick, onConnect, kept, switching }: AccountChipProps & { kept?: PlanUsage }) {
    // The plan used, read fresh as the menu opens: only the windows that can stop this model. The other plans' bars
    // are the accounts' summaries, read again as it opens and, while it's open, as another plan's usage moves (a
    // usage frame re-reads the list only here, and never for the plan used, whose own read follows it).
    const fresh = usePlanUsage(account, model, { fresh: true });
    useEffect(() => {
        rereadAccounts();
    }, []);
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'plan_usage' && frame.id !== account?.connectionId && frame.id !== account?.id) rereadAccounts();
    });
    const usedWindows = (fresh.data ?? kept)?.windows ?? [];
    const barsOf = (a: ModelAccount) => (a.id === account?.id ? usedWindows : tightestOf(a));
    const runs = accountChoices(accounts, harness).filter((a) => routeFor(a, harness, routes));
    const not = accounts.filter((a) => !runs.some((r) => r.id === a.id));
    const why = (a: ModelAccount): ReactNode => {
        if (a.id !== account?.id) return null;
        if (a.id === NOCLICK_KEY) return picked ? 'Used: you picked it' : harness.name === 'sdk' ? 'Used unless you pick one of yours' : 'Used: nothing of yours runs it';
        if (runs.length === 1) return 'The only one you have that runs it';
        return picked ? 'Used: you picked it' : 'Used: the first you connected that runs it';
    };
    const any = new Intl.ListFormat('en', { type: 'disjunction' }).format(ways.map((w) => (isPlanAccount(w) ? `a ${wayLabel(w)}` : `${/^[aeiou]/i.test(wayLabel(w)) ? 'an' : 'a'} ${wayLabel(w)}`)));
    return (
        <>
            <div className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
                <p className={HEAD}>
                    Runs {harnessLabel(harness.name)} on {modelLabel} on
                </p>
                {free && !runs.length && (
                    <div className={cn(ROW, 'hover:bg-transparent')}>
                        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-emerald-500/[0.12] max-sm:h-8 max-sm:w-8">
                            <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" strokeWidth={2.25} />
                        </span>
                        <span className="min-w-0 flex-1">
                            <span className={MAIN}>No account needed</span>
                            <span className={SUB}>{free} is free on OpenCode Zen</span>
                        </span>
                    </div>
                )}
                {runs.map((a) => (
                    <button key={a.id} type="button" role="menuitemradio" aria-checked={a.id === account?.id} onClick={() => onPick(a.id)} className={cn(ROW, barsOf(a).length > 0 && 'items-start')}>
                        <Mark a={a} size={24} />
                        <span className="min-w-0 flex-1">
                            <RowTitle a={a} className={MAIN} />
                            <span className={SUB}>
                                {a.note}
                                {why(a) && <span className="block text-foreground/70">{why(a)}</span>}
                            </span>
                            <UsageWindows windows={barsOf(a)} />
                        </span>
                        <Check className={cn('h-3.5 w-3.5 shrink-0', barsOf(a).length > 0 && 'mt-[5px]', a.id !== account?.id && 'invisible')} strokeWidth={2.25} />
                    </button>
                ))}
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
                        <p className={cn(HEAD, 'mt-0.5 border-t border-border pt-2 dark:border-foreground/[0.08]')}>Yours, but not for this</p>
                        {not.map((a) => (
                            <div key={a.id} className={cn('flex gap-2.5 px-2 py-1 opacity-60 max-sm:gap-3 max-sm:py-1.5', tightestOf(a).length ? 'items-start' : 'items-center')}>
                                <Mark a={a} size={20} />
                                <span className="min-w-0 flex-1">
                                    <RowTitle a={a} className="block truncate text-[12px] leading-5 max-sm:text-[13.5px]" />
                                    <span className={SUB}>{accountRefusal(a, harness, model, modelLabel)}</span>
                                    <UsageWindows windows={tightestOf(a)} />
                                </span>
                            </div>
                        ))}
                    </>
                )}
                {/* Only a coding harness runs on a plan; a rule already set stays reachable to undo. */}
                {switching && harness.name !== 'sdk' && (accounts.some(isPlanAccount) || switching.value.mode === 'stay' || !!switching.value.allowed) && (
                    <SwitchingSection accounts={accounts} harness={harness} value={switching.value} onChange={switching.onChange} />
                )}
            </div>
            <div className="mt-0.5 shrink-0 border-t border-border pt-1 dark:border-foreground/[0.08]" data-testid="account-menu-foot">
                {runs.length || free ? (
                    <button type="button" onClick={() => onConnect(true)} className={cn(ROW, 'text-foreground/85 hover:text-foreground')}>
                        <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-foreground/[0.06] ring-1 ring-inset ring-foreground/[0.06] max-sm:h-8 max-sm:w-8">
                            <Plus className="h-3.5 w-3.5" strokeWidth={2} />
                        </span>
                        <span className="text-[12.5px] font-medium max-sm:text-[14px]">Connect another</span>
                    </button>
                ) : (
                    <div className="p-1">
                        <button type="button" onClick={() => onConnect(false)} className={cn(BUTTON_PRIMARY, 'h-8 w-full justify-center text-[12.5px] max-sm:h-10 max-sm:text-[14px]')}>
                            {ask.lapsed ? <RotateCw className="h-3.5 w-3.5" strokeWidth={2} /> : null}
                            {ask.send.replace(/ to start$/, '')}
                        </button>
                    </div>
                )}
            </div>
        </>
    );
}
