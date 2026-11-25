// An agent's triggers as its session's footer shows them, the item after its budget: their marks (a stopped one
// first, with a red dot), then what stopped or when it next runs; "Running now" while a turn one started runs; "Only when
// messaged" with none. It opens a popover (a phone's bottom sheet) of the same compact rows as the profile's Triggers
// tab, each opening there, with "All in its profile" and "Add a trigger".
import { useContext, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { BellOff, ChevronDown, ChevronRight, Plus, Zap } from 'lucide-react';
import type { Agent } from 'noclick';
import { useInPhoneShell } from '@/ui/phoneBar';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { MENU_SURFACE } from '@/ui/menus';
import { ShortcutTooltip } from '@/ui/ShortcutTooltip';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/ui/tooltip';
import { cn } from '@/ui/utils';
import { useWorkNav } from '../nav';
import { WorkMotion } from '../agents/AgentRing';
import { PickerSheetHost } from '../newAgent/ModelPicker';
import { nameOf, useSpaceNoClicks } from '../agents/reads';
import { KindIcon, useTriggerActions, useTriggerFrames, useTriggerItems, useTriggerNames } from './data';
import { byAttention, nextRun, shortWhen, whenOf, type TriggerItem } from './model';
import { TriggerRow } from './TriggerRow';

const FOOT =
    "inline-flex h-7 max-w-[220px] items-center gap-1.5 rounded-full px-2 relative max-md:after:absolute max-md:after:inset-x-0 max-md:after:-inset-y-1.5 max-md:after:content-[''] text-[12.5px] text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground";

/** `className`: its place in a row (the footer's item, with its dot), there only once there's a chip to show; `fold`
 *  marks it as the row's item (`data-fold`), `folded` shows its marks alone and says the rest in its tooltip. */
export function TriggersChip({ agent, className, fold, folded = false }: { agent: Agent; className?: string; fold?: number; folded?: boolean }) {
    const phone = useInPhoneShell();
    // Its sheet opens on the page's layer for sheets: drawn inside the footer, whose line scrolls sideways under a
    // faded edge, it was cut down to that line.
    const sheetHost = useContext(PickerSheetHost);
    const nav = useWorkNav();
    const { items, loading, error } = useTriggerItems(agent.id, agent.paused);
    useTriggerFrames(agent.id);
    const names = useTriggerNames();
    const [open, setOpen] = useState(false);
    const name = nameOf(agent, useSpaceNoClicks());
    // Unread, it claims nothing: its profile's tab says it couldn't read them.
    if (loading || error) return null;
    const n = items.length;
    const ordered = byAttention(items);
    const shown = ordered.slice(0, phone || n > 4 ? 3 : 4);
    const more = n - shown.length;
    const stopped = items.filter((i) => i.state === 'stopped').length;
    const next = nextRun(items);
    const running = items.some((i) => i.running);
    const go = (trigger?: string) => {
        setOpen(false);
        nav.openProfile(agent.id, { tab: 'triggers', trigger });
    };
    // Folded, the chip's own tooltip says it all: no tooltip of each mark under it.
    const icons = folded ? (
        <span className="flex shrink-0 items-center gap-1">
            {shown.slice(0, 2).map((t) => (
                <span key={t.id} className={cn('relative grid h-4 w-4 place-items-center', t.state === 'paused' && 'opacity-50')}>
                    <KindIcon item={t} className="h-3.5 w-3.5 text-current" />
                    {t.state === 'stopped' && <span aria-hidden className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-red-500 ring-[1.5px] ring-background" />}
                </span>
            ))}
        </span>
    ) : (
        <span className="flex shrink-0 items-center gap-1">
            {shown.map((t) => (
                <Tooltip key={t.id}>
                    <TooltipTrigger asChild>
                        <span className={cn('relative grid h-4 w-4 place-items-center', t.state === 'paused' && 'opacity-50')}>
                            <KindIcon item={t} className="h-3.5 w-3.5 text-current" />
                            {t.state === 'stopped' && <span aria-hidden className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-red-500 ring-[1.5px] ring-background" />}
                        </span>
                    </TooltipTrigger>
                    <TooltipContent side="top">
                        {whenOf(t, names)}
                        {t.state === 'stopped' ? ' · stopped' : t.state === 'paused' ? ' · paused' : ''}
                    </TooltipContent>
                </Tooltip>
            ))}
            {more > 0 && <span className="text-[12px] tabular-nums">+{more}</span>}
        </span>
    );
    const lead = running ? (
        <>
            <WorkMotion />
            <Zap className="work-bolt h-3.5 w-3.5 text-foreground" strokeWidth={2} />
        </>
    ) : !n ? (
        <span aria-hidden className="h-3.5 w-3.5 shrink-0 rounded-full border-[1.5px] border-dashed border-foreground/40" />
    ) : agent.paused ? (
        <BellOff className="h-3.5 w-3.5" strokeWidth={1.9} />
    ) : (
        icons
    );
    const tail: ReactNode = running ? (
        <span className="text-foreground">Running now</span>
    ) : !n ? (
        'Only when messaged'
    ) : agent.paused ? (
        'Triggers paused'
    ) : stopped ? (
        <span className="text-red-600 max-sm:hidden dark:text-red-400">· {stopped} stopped</span>
    ) : next ? (
        <span className="max-sm:hidden">Next {shortWhen(next.at)}</span>
    ) : null;
    const said = running ? 'Running now' : !n ? 'Only when messaged' : agent.paused ? 'Triggers paused' : [`${n} ${n === 1 ? 'trigger' : 'triggers'}`, stopped ? `${stopped} stopped` : next ? `next ${shortWhen(next.at)}` : null].filter(Boolean).join(' · ');
    const chip = (
        <button type="button" aria-label="Its triggers" onClick={phone ? () => setOpen(true) : undefined} data-state={open ? 'open' : 'closed'} data-testid="triggers-chip" className={cn(FOOT, folded && 'justify-center px-1.5')}>
            {lead}
            {!folded && tail && <span className="truncate">{tail}</span>}
            {!folded && <ChevronDown className="h-3 w-3 shrink-0 opacity-70" strokeWidth={2} />}
        </button>
    );
    const tipped = (trigger: ReactNode) => (folded ? <ShortcutTooltip label={said} side="top">{trigger}</ShortcutTooltip> : trigger);
    const body = <QuickTriggers agent={agent} name={name} items={ordered} phone={phone} onProfile={go} />;
    if (phone)
        return (
            <span className={className} data-fold={fold} data-folded={folded || undefined}>
                {tipped(chip)}
                {open &&
                    createPortal(
                        <div className={cn('inset-0 z-50 flex flex-col justify-end', sheetHost ? 'absolute' : 'fixed')}>
                            <button type="button" aria-label="Close" onClick={() => setOpen(false)} className="absolute inset-0 bg-black/50" />
                            <div role="dialog" aria-label="What triggers it" className="relative flex max-h-[78vh] flex-col overflow-hidden rounded-t-[26px] bg-composer pb-[max(env(safe-area-inset-bottom),16px)] ring-1 ring-border dark:ring-foreground/[0.1]">
                                <span aria-hidden className="mx-auto mb-1 mt-2 h-1 w-9 shrink-0 rounded-full bg-foreground/20" />
                                {body}
                            </div>
                        </div>,
                        sheetHost ?? document.body
                    )}
            </span>
        );
    return (
        <span className={className} data-fold={fold} data-folded={folded || undefined}>
            <Popover open={open} onOpenChange={setOpen}>
                {tipped(<PopoverTrigger asChild>{chip}</PopoverTrigger>)}
                <PopoverContent align="end" side="top" sideOffset={8} collisionPadding={12} className={cn('w-[400px] rounded-[22px] p-0', MENU_SURFACE)}>
                    {body}
                </PopoverContent>
            </Popover>
        </span>
    );
}

/** The popover: what triggers it, each row opening it in the profile, with all of them there and adding one. */
function QuickTriggers({ agent, name, items, phone, onProfile }: { agent: Agent; name: string; items: TriggerItem[]; phone: boolean; onProfile: (trigger?: string) => void }) {
    const names = useTriggerNames();
    const actions = useTriggerActions(agent, names);
    const n = items.length;
    return (
        <div className="flex min-h-0 flex-col" data-testid="quick-triggers">
            <div className="flex items-start gap-3 px-4 pb-2 pt-3.5">
                <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-semibold">{n ? `What triggers ${name}` : `${name} only answers when messaged`}</p>
                    <p className="mt-0.5 text-[12.5px] leading-snug text-muted-foreground">{n ? 'Besides your messages and @mentions.' : 'Give it a schedule, an app’s event, its own inbox or a webhook.'}</p>
                </div>
                <button type="button" onClick={() => onProfile()} className="mt-0.5 inline-flex h-7 shrink-0 items-center gap-0.5 rounded-full pl-2.5 pr-1.5 text-[12.5px] text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground">
                    All in its profile
                    <ChevronRight className="h-3.5 w-3.5" strokeWidth={2} />
                </button>
            </div>
            {agent.paused && (
                <div className="mx-3 mb-1 flex items-center gap-2 rounded-xl bg-foreground/[0.05] py-1.5 pl-3 pr-1.5 text-[12.5px] text-foreground/80" data-testid="triggers-paused">
                    <BellOff className="h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                    <span className="min-w-0 flex-1">Its triggers are paused.</span>
                    <button type="button" onClick={() => actions.setAgentPaused(false)} className={cn(BUTTON_SECONDARY, 'h-7 px-3 text-[12px]')}>
                        Resume
                    </button>
                </div>
            )}
            {n > 0 && (
                <div className={cn('min-h-0 flex-1 overflow-y-auto px-2 scrollbar-subtle', !phone && 'max-h-[420px]')}>
                    {items.map((t) => (
                        <TriggerRow key={t.id} item={t} names={names} actions={actions} phone={phone} onOpen={() => onProfile(t.id)} running={t.running} />
                    ))}
                </div>
            )}
            <div className="px-2 pb-2 pt-1">
                <button type="button" onClick={() => onProfile('add')} className="flex h-10 w-full items-center gap-3 rounded-[14px] pl-1.5 pr-2 text-left text-[13.5px] text-foreground/85 transition-colors hover:bg-foreground/[0.05] hover:text-foreground">
                    <span className="grid h-7 w-7 place-items-center rounded-full bg-foreground/[0.06]">
                        <Plus className="h-3.5 w-3.5" strokeWidth={2} />
                    </span>
                    Add a trigger
                </button>
            </div>
        </div>
    );
}
