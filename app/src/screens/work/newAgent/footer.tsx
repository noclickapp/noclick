// The New agent draft's footer popups: where it runs (a cloud sandbox of its own, one of your NoClick machines, a new
// one, or a machine of your own, one line each with what it costs) and its budget (presets or your own amount). The
// budget's body is the profile's too. A new machine is bought in its own popup (`machine/BuyMachine`), which its host
// draws, as it draws Add your computer.
import { useRef, useState, type ReactNode } from 'react';
import { Box, Check, ChevronDown, CircleDollarSign, Laptop, Plus, Server } from 'lucide-react';
import { Machine, type AppTesting } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { HAIRLINE } from '@/ui/primitives';
import { MENU_SURFACE } from '@/ui/menus';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { cn } from '@/ui/utils';
import { useWorkFrames } from '@/sdk/live';
import { useWorkV1 } from '../agents/reads';
import { MACHINES_KEY, useMachines, useMachineSizes } from '../machine/reads';

const ROW = 'flex w-full items-start gap-2.5 rounded-xl px-2.5 py-2 text-left text-[13.5px] transition-colors hover:bg-foreground/[0.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring';
const LABEL = 'px-2.5 pb-1 pt-1.5 text-[12px] text-muted-foreground';

// ── where it runs ───────────────────────────────────────────────────────────

/** A sandbox of its own, shared by everyone talking to it; one of the account's machines (a new one is bought first,
 *  then picked by name). */
export type RunsValue = { kind: 'sandbox' } | { kind: 'machine'; id: string; name: string };

/** A sandbox at its rate for 1 core and 2 GiB, while it works. */
const SANDBOX_HOUR = ((0.00003942 + 2 * 0.00000667) * 3600).toFixed(2);

export const runsText = (v: RunsValue) => (v.kind === 'sandbox' ? 'Cloud sandbox' : v.name);
/** Where it runs in a word, for a phone's row of pills. */
export const runsShort = (v: RunsValue) => (v.kind === 'sandbox' ? 'Sandbox' : v.name);

/** A new agent turns app testing on and off by itself unless it says (the API's default). */
export const NEW_APP_TESTING: AppTesting = 'by_itself';

/** What the API says while agents can't run on machines here (#5441's 409 `not_available`), in its own words. */
export const NOT_ON_MACHINES = "Agents on machines aren't enabled on this deployment yet.";
/** Whether agents run on machines on this deployment; until it says so, no machine can be picked. */
const useMachinesEnabled = () => useWorkV1(`${MACHINES_KEY}:enabled`, (client) => Machine.agentsEnabledHere({ client }));

/** `note`: a muted line under its name, as wide as the row. */
function RunRow({ on, icon, title, note, price, onClick, disabled }: { on: boolean; icon: ReactNode; title: ReactNode; note?: string; price?: ReactNode; onClick: () => void; disabled?: boolean }) {
    return (
        <button type="button" role="menuitemradio" aria-checked={on} disabled={disabled} onClick={onClick} className={cn(ROW, 'flex-wrap items-center gap-y-0 py-2.5 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent')}>
            <span className="grid h-5 w-5 shrink-0 place-items-center">{icon}</span>
            <span className="min-w-0 flex-1 truncate">{title}</span>
            {price && <span className="shrink-0 text-[12.5px] tabular-nums text-muted-foreground">{price}</span>}
            <Check className={cn('h-4 w-4 shrink-0', !on && 'invisible')} />
            {note && <span className="basis-full pl-[30px] text-[12px] leading-snug text-muted-foreground">{note}</span>}
        </button>
    );
}

const SANDBOX_ICON = <Box className="h-4 w-4 text-foreground/70" strokeWidth={1.75} />;
const MACHINE_ICON = <Server className="h-4 w-4 text-foreground/70" strokeWidth={1.75} />;

/** Where it runs, one line a place: a cloud sandbox, a NoClick machine of yours or a new one, or your own machine,
 *  each with its price. `appTesting` is the agent's (a draft's is `by_itself`): unless it's `never`, the sandbox says
 *  it grows for app tests. `onNewMachine` and `onAddComputer` open buying a machine and Add your computer, which its
 *  host draws (they outlive this menu). */
export function RunsBody({
    value,
    appTesting,
    onChange,
    onNewMachine,
    onAddComputer,
}: {
    value: RunsValue;
    appTesting: AppTesting;
    onChange: (v: RunsValue) => void;
    onNewMachine?: () => void;
    onAddComputer?: () => void;
}) {
    const machines = useMachines();
    // Read as the menu opens, so buying one opens on its sizes.
    useMachineSizes();
    const enabled = useMachinesEnabled();
    const noclick = (machines.data ?? []).filter((m) => m.kind !== 'own');
    const own = (machines.data ?? []).filter((m) => m.kind === 'own');
    // A machine is picked only once the deployment says agents run on one: nothing here fails later.
    const off: Off = enabled.data === true ? null : { note: enabled.data === false ? 'Not enabled yet' : enabled.error !== undefined ? 'Couldn’t check' : '' };
    return (
        <div className="flex flex-col" role="menu" aria-label="Runs in">
            <RunRow
                on={value.kind === 'sandbox'}
                icon={SANDBOX_ICON}
                onClick={() => onChange({ kind: 'sandbox' })}
                title="Cloud sandbox"
                note={appTesting === 'never' ? undefined : 'Grows for app tests'}
                price={`$${SANDBOX_HOUR}/hr while working`}
            />
            {enabled.data === false && <p className={cn(LABEL, 'pt-1')}>{NOT_ON_MACHINES}</p>}
            {noclick.map((m) => (
                <RunRow
                    key={m.id}
                    on={value.kind === 'machine' && value.id === m.id}
                    disabled={!!off}
                    icon={MACHINE_ICON}
                    onClick={() => onChange({ kind: 'machine', id: m.id, name: m.name })}
                    title={m.name}
                    price={off ? off.note : m.monthlyUsd !== null ? `$${m.monthlyUsd.toFixed(2)}/mo` : undefined}
                />
            ))}
            {onNewMachine && (
                <button type="button" role="menuitem" disabled={!!off} onClick={onNewMachine} className={cn(ROW, 'items-center py-2.5 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent')}>
                    <span className="grid h-5 w-5 shrink-0 place-items-center">{MACHINE_ICON}</span>
                    <span className="min-w-0 flex-1 truncate">{noclick.length ? 'Another machine…' : 'A new machine…'}</span>
                    {off && <span className="shrink-0 text-[12.5px] text-muted-foreground">{off.note}</span>}
                    <span aria-hidden className="h-4 w-4 shrink-0" />
                </button>
            )}
            <OwnMachines machines={own} value={value} onChange={onChange} off={off} onAdd={onAddComputer} />
        </div>
    );
}

/** While machines can't be picked: what each one says in place of its price. */
type Off = { note: string } | null;

/** OWN_MACHINE.md's "Your own machine": each with a status dot, then "Add your computer", which opens its dialog. */
function OwnMachines({ machines, value, onChange, off, onAdd }: { machines: Machine[]; value: RunsValue; onChange: (v: RunsValue) => void; off: Off; onAdd?: () => void }) {
    // A machine coming online, going offline or being removed reads the list again.
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'machine') invalidateV1(MACHINES_KEY);
    });
    return (
        <>
            <p className={cn(LABEL, 'flex items-center border-t pt-2', HAIRLINE)}>Your own machine</p>
            {machines.map((m) => {
                const up = m.status === 'running';
                return (
                    <RunRow
                        key={m.id}
                        on={value.kind === 'machine' && value.id === m.id}
                        disabled={!!off}
                        icon={<span className={cn('h-2 w-2 rounded-full', up ? 'bg-emerald-500' : 'bg-foreground/30')} />}
                        onClick={() => onChange({ kind: 'machine', id: m.id, name: m.name })}
                        title={
                            <>
                                {m.name} <span className="text-muted-foreground">· {up ? 'online' : m.status === 'provisioning' ? 'waiting for it' : 'offline'}</span>
                            </>
                        }
                        price={off ? off.note : 'Free'}
                    />
                );
            })}
            {onAdd && (
                <button type="button" disabled={!!off} onClick={onAdd} className={cn(ROW, 'items-center text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-muted-foreground')}>
                    <Laptop className="h-4 w-4 shrink-0" strokeWidth={1.75} />
                    <span className="flex-1">Add your computer</span>
                    {off ? <span className="shrink-0 text-[12.5px] text-muted-foreground">{off.note}</span> : <Plus className="h-4 w-4 shrink-0" strokeWidth={2} />}
                </button>
            )}
        </>
    );
}

// ── its budget ──────────────────────────────────────────────────────────────

/** Dollars a month; null: no cap of its own (the account's cap still holds). */
export type BudgetValue = number | null;
export const NEW_BUDGET: BudgetValue = 10;
export const budgetLabel = (v: BudgetValue) => (v === null ? 'No cap' : `$${v} a month`);
/** Its budget as a phone's row of pills says it. */
export const budgetShort = (v: BudgetValue) => (v === null ? 'No cap' : `$${v}/mo`);

const PRESETS = [5, 10, 25, 50];
const PILL = 'inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-[13px] transition-colors';

/** Its budget: a preset, no cap of its own, or any amount (`budget_usd_per_month`); the account's cap still holds. */
/** `noCap`: whether No cap is offered (not where none set comes to a cap of its own). */
export function BudgetBody({ value, onChange, noCap = true }: { value: BudgetValue; onChange: (v: BudgetValue) => void; noCap?: boolean }) {
    const custom = value !== null && !PRESETS.includes(value);
    return (
        <div className="flex flex-col">
            <p className={LABEL}>A month</p>
            <div className="flex flex-wrap gap-1.5 px-2.5 py-2" role="radiogroup" aria-label="A month">
                {[...PRESETS, ...(noCap ? [null] : [])].map((b) => (
                    <button key={String(b)} type="button" role="radio" aria-checked={value === b} onClick={() => onChange(b)} className={cn(PILL, value === b ? 'bg-foreground text-background' : 'bg-foreground/[0.05] text-foreground/80 hover:bg-foreground/[0.09] hover:text-foreground')}>
                        {b === null ? 'No cap' : `$${b}`}
                    </button>
                ))}
            </div>
            <label className="flex items-center gap-2 px-2.5 pb-2 text-[13px] text-muted-foreground">
                Or
                <span className={cn('flex items-center gap-0.5 rounded-full px-3', custom ? 'bg-foreground/[0.1] text-foreground' : 'bg-foreground/[0.05]')}>
                    $
                    <input
                        inputMode="decimal"
                        placeholder="40"
                        defaultValue={custom ? String(value) : ''}
                        aria-label="Your own amount a month"
                        onChange={(e) => {
                            const n = Number(e.target.value);
                            if (n > 0) onChange(Math.round(n));
                        }}
                        className="h-8 w-14 bg-transparent text-[13px] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))]"
                    />
                </span>
                a month
            </label>
            <p className={cn('border-t px-2.5 pb-1.5 pt-2 text-[11.5px] text-muted-foreground', HAIRLINE)}>It stops there and asks you for more. Your account’s own cap still holds.</p>
        </div>
    );
}

// ── in the draft's footer ───────────────────────────────────────────────────

/** A footer's row: a dot between neighbours on a line, none at a wrap. Each item draws its dot in the gap before it
 *  (`FOOT_ITEM` reaches back over the gap); the row clips the dot of whichever item starts a line. */
export const FOOT_ROW = 'flex flex-wrap items-center gap-x-2 overflow-x-clip [overflow-clip-margin:2px] max-md:gap-y-1';
export const FOOT_ITEM =
    "relative -ml-2 flex min-w-0 items-center pl-2 before:pointer-events-none before:absolute before:left-0 before:top-1/2 before:w-2 before:-translate-y-1/2 before:text-center before:text-[12px] before:leading-none before:text-muted-foreground/50 before:content-['·']";

// On a phone a little tighter and without the chevron, so a row's account, place and budget fit a 360px screen side
// by side, with room for a longer kind ("ChatGPT") or budget ("$100/mo").
const FOOT =
    "inline-flex h-7 max-w-[200px] items-center gap-1.5 rounded-full px-2 relative max-md:gap-1 max-md:px-1.5 max-md:after:absolute max-md:after:inset-x-0 max-md:after:-inset-y-1.5 max-md:after:content-[''] text-[12.5px] text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.05] data-[state=open]:text-foreground";

/** A popup's full height (30rem, the lab's popovers' cap). */
const POPUP_TALL = 480;

/** Which side of its button a popup opens on: below where its full height fits, else wherever there's more room. */
export function sideFor(button: { top: number; bottom: number }, viewportHeight: number): 'top' | 'bottom' {
    const below = viewportHeight - button.bottom;
    return below >= POPUP_TALL || below >= button.top ? 'bottom' : 'top';
}

/** One of the draft's footer buttons, opening its popup: no taller than the room on its side (it opens above when
 *  there's more room there), the whole body scrolling unless the body keeps its own top in place (`scrolls={false}`). */
export function FootPopover({
    label,
    icon,
    text,
    width = 320,
    scrolls = true,
    folded = false,
    short,
    onOpenChange,
    children,
}: {
    label: string;
    icon: ReactNode;
    text: string;
    /** What it says in a phone's row, where no tooltip opens: its name then says it in full ("Budget: $25 a month"). */
    short?: string;
    width?: number;
    scrolls?: boolean;
    /** Its icon alone, its label and text in its tooltip: a row out of room. */
    folded?: boolean;
    /** As it opens or closes (a change saved as its popup closes). */
    onOpenChange?: (open: boolean) => void;
    children: ReactNode;
}) {
    const button = useRef<HTMLButtonElement>(null);
    const [side, setSide] = useState<'top' | 'bottom'>('bottom');
    return (
        <Popover
            onOpenChange={(open) => {
                if (open && button.current) setSide(sideFor(button.current.getBoundingClientRect(), window.innerHeight));
                onOpenChange?.(open);
            }}
        >
            <ShortcutTooltip label={folded ? `${label}: ${text}` : undefined} side="top">
                <PopoverTrigger ref={button} className={cn(FOOT, folded && 'w-7 justify-center px-0')} aria-label={short ? `${label}: ${text}` : label}>
                    {icon}
                    {!folded && (
                        <>
                            <span className="truncate">{short ?? text}</span>
                            <ChevronDown className="h-3 w-3 shrink-0 opacity-70 max-md:hidden" strokeWidth={2} />
                        </>
                    )}
                </PopoverTrigger>
            </ShortcutTooltip>
            <PopoverContent
                align="start"
                side={side}
                sideOffset={6}
                collisionPadding={12}
                style={{ width }}
                className={cn('flex max-h-[min(30rem,var(--radix-popover-content-available-height))] flex-col overflow-hidden rounded-2xl p-1.5', MENU_SURFACE)}
            >
                {scrolls ? <div className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle">{children}</div> : children}
            </PopoverContent>
        </Popover>
    );
}

/** A footer item shown but not changed here, as a button would read without its popup; `tip` says why. */
/** `short`: what it says in a phone's row, its full text kept for a screen reader. */
export function FootFact({ icon, text, tip, folded = false, short }: { icon: ReactNode; text: string; tip: string; folded?: boolean; short?: string }) {
    return (
        <ShortcutTooltip label={folded ? `${text}. ${tip}` : tip} side="top">
            <span className={cn(FOOT, 'cursor-default hover:bg-transparent hover:text-muted-foreground', folded && 'w-7 justify-center px-0')}>
                {icon}
                {!folded &&
                    (short ? (
                        <>
                            <span aria-hidden className="truncate">
                                {short}
                            </span>
                            <span className="sr-only">{text}</span>
                        </>
                    ) : (
                        <span className="truncate">{text}</span>
                    ))}
            </span>
        </ShortcutTooltip>
    );
}

export const FOOT_ICONS = {
    runs: (v: RunsValue) => (v.kind === 'sandbox' ? <Box className="h-3.5 w-3.5" strokeWidth={1.75} /> : <Server className="h-3.5 w-3.5" strokeWidth={1.75} />),
    budget: <CircleDollarSign className="h-3.5 w-3.5" strokeWidth={1.75} />,
};
