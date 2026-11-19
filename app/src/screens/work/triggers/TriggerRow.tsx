// One trigger in one line, the same in the profile's Triggers tab and the chat footer's popover: its mark, its sentence
// clipped (whole in a tooltip), its status on the right; hovered or focused, Try it now, Pause and ⋯ take the status's
// place (only what the trigger's view lists). A stopped one holds its fix there and a second line, the provider's words.
// An app event the platform titles reads as two lines instead: its app's mark, what arrives where ("Messages to +91 …"),
// then what it hears, or, when it can't hear, what's wrong and what fixes it beside the fix itself ("Reconnect"); paused
// on its own, Resume. It never says "Live": its group does. Opened, it expands under itself (the tab) or opens the tab
// (the popover, `onOpen`).
import { useState, type ReactNode } from 'react';
import { MoreHorizontal, Pause, Play, Zap } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/ui/tooltip';
import { cn } from '@/ui/utils';
import { WorkMotion } from '../agents/AgentRing';
import { KindIcon, type TriggerActions } from './data';
import { sentenceOf, sourceLine, statusOf, type Names, type TriggerItem } from './model';

const ITEM = 'gap-2.5 rounded-lg px-2.5 py-2 text-[14px]';
const ICON_BUTTON = 'grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.08] hover:text-foreground disabled:opacity-40';

export interface TriggerRowProps {
    item: TriggerItem;
    names: Names;
    actions: TriggerActions;
    /** A phone: taller, ⋯ always there, no play or pause. */
    phone: boolean;
    /** Opened under itself. */
    open?: boolean;
    /** Opens it: in place (the tab) or in the profile (the popover). */
    onOpen: () => void;
    /** A turn it started is running now. */
    running?: boolean;
    /** Just added: a green ring, "New", and that it listens from now. */
    fresh?: boolean;
    /** What's under it when it's open. */
    children?: ReactNode;
}

export function TriggerRow({ item, names, actions, phone, open = false, onOpen, running = false, fresh = false, children }: TriggerRowProps) {
    const [hover, setHover] = useState(false);
    const [menu, setMenu] = useState(false);
    const sentence = sentenceOf(item, names);
    const can = (a: TriggerItem['actions'][number]) => item.actions.includes(a);
    const live = item.state === 'live';
    const status = running
        ? { text: 'Running…', tone: 'running' as const }
        : fresh && live
          ? { text: item.nextAt ? statusOf(item).text : 'Listening from now', tone: 'ok' as const }
          : statusOf(item);
    const showActions = !phone && (hover || menu);
    const line = sourceLine(item);
    // Beside its own words for what's wrong, reconnecting needs no app's name.
    const fixLabel = item.state !== 'live' ? (line && item.fix?.action === 'connect' ? 'Reconnect' : actions.label(item)) : null;
    const stopped = item.state === 'stopped';
    const resumable = !!line && item.state === 'paused' && item.pausedItself && can('resume');
    const openInApp = item.kind === 'app';
    const menuItems = [
        (can('update') || openInApp) && (
            <DropdownMenuItem key="change" onSelect={openInApp ? () => actions.fix({ ...item, fix: { action: 'open_in_app' } }) : onOpen} className={ITEM}>
                {openInApp ? 'Open in the app' : 'Change it'}
            </DropdownMenuItem>
        ),
        can('test') && live && (
            <DropdownMenuItem key="test" onSelect={() => actions.test(item)} className={ITEM}>
                Try it now
            </DropdownMenuItem>
        ),
        can('pause') && !item.pausedItself && (
            <DropdownMenuItem key="pause" onSelect={() => actions.pause(item)} className={ITEM}>
                Pause
            </DropdownMenuItem>
        ),
        can('resume') && (
            <DropdownMenuItem key="resume" onSelect={() => actions.resume(item)} className={ITEM}>
                Resume
            </DropdownMenuItem>
        ),
    ].filter(Boolean);
    const removes = can('remove') || can('cancel');
    const more =
        menuItems.length || removes ? (
            <DropdownMenu onOpenChange={setMenu}>
                <DropdownMenuTrigger aria-label={`More for: ${sentence}`} className={cn(ICON_BUTTON, 'data-[state=open]:bg-foreground/[0.08] data-[state=open]:text-foreground')}>
                    <MoreHorizontal className="h-4 w-4" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" sideOffset={4} className="min-w-[200px] rounded-xl p-1">
                    {menuItems}
                    {removes && (
                        <>
                            {menuItems.length > 0 && <DropdownMenuSeparator className="mx-1 bg-border dark:bg-foreground/[0.08]" />}
                            <DropdownMenuItem onSelect={() => actions.remove(item)} className={cn(ITEM, 'text-red-600 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400')}>
                                {can('cancel') ? 'Cancel it' : 'Remove'}
                            </DropdownMenuItem>
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        ) : null;
    const quick = (label: string, icon: ReactNode, onClick: () => void) => (
        <Tooltip>
            <TooltipTrigger asChild>
                <button type="button" aria-label={label} onClick={onClick} className={ICON_BUTTON}>
                    {icon}
                </button>
            </TooltipTrigger>
            <TooltipContent side="top">{label}</TooltipContent>
        </Tooltip>
    );
    return (
        <div
            data-trigger={item.id}
            data-state={item.state}
            onMouseEnter={() => setHover(true)}
            onMouseLeave={() => setHover(false)}
            onFocus={() => setHover(true)}
            onBlur={(e) => !e.currentTarget.contains(e.relatedTarget as Node | null) && setHover(false)}
            className={cn(
                'rounded-[14px] transition-colors',
                (open || hover || menu) && 'bg-foreground/[0.04]',
                running && 'work-trigger-running',
                fresh && 'bg-emerald-500/5 ring-1 ring-inset ring-emerald-500/25'
            )}
        >
            {running && <WorkMotion />}
            <div className={cn('flex items-center gap-2.5 px-2', phone ? 'min-h-[52px]' : 'min-h-[44px]')}>
                <Tooltip>
                    <TooltipTrigger asChild>
                        <button type="button" onClick={onOpen} aria-expanded={open} className="flex min-w-0 flex-1 items-center gap-2.5 self-stretch text-left focus-visible:outline-none">
                            <span className={cn('relative grid h-7 w-7 shrink-0 place-items-center rounded-full bg-foreground/[0.06]', line && item.state === 'paused' && 'opacity-60')}>
                                <KindIcon item={item} className={line ? 'h-4 w-4' : 'h-3.5 w-3.5'} />
                                {running && <span aria-hidden className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-emerald-500 ring-2 ring-background" />}
                            </span>
                            {line ? (
                                <span className={cn('flex min-w-0 flex-1 flex-col py-1.5', item.state === 'paused' && 'opacity-60')}>
                                    <span data-sentence className="truncate text-[13.5px] text-foreground/90 max-sm:text-[14.5px]">
                                        {item.title}
                                    </span>
                                    {(line.warn || line.text) && (
                                        <span data-source-line className={cn('text-[12px] leading-snug text-muted-foreground', !line.warn && 'truncate')}>
                                            {line.warn && <span className="text-red-600 dark:text-red-400">{line.warn}</span>}
                                            {line.warn && line.text && ' · '}
                                            {line.text}
                                        </span>
                                    )}
                                </span>
                            ) : (
                                <span data-sentence className={cn('min-w-0 flex-1 truncate text-[13.5px] max-sm:text-[14.5px]', item.state === 'paused' ? 'text-foreground/55' : 'text-foreground/90')}>
                                    {sentence}
                                </span>
                            )}
                            {fresh && <span className="shrink-0 rounded-full bg-emerald-500/15 px-1.5 text-[11px] font-medium leading-[18px] text-emerald-700 dark:text-emerald-300">New</span>}
                        </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" align="start" className="max-w-[300px] leading-snug">
                        {sentence}
                    </TooltipContent>
                </Tooltip>
                {/* Opened, its fix is in what's under it. */}
                {((stopped && fixLabel) || resumable) && !open ? (
                    <span className="flex shrink-0 items-center gap-0.5">
                        {resumable ? (
                            <button type="button" onClick={() => actions.resume(item)} className="inline-flex h-7 shrink-0 items-center rounded-full bg-foreground/[0.06] px-3 text-[12px] font-medium text-foreground transition-colors hover:bg-foreground/[0.1]">
                                Resume
                            </button>
                        ) : (
                            <button type="button" onClick={() => actions.fix(item)} className="inline-flex h-7 shrink-0 items-center rounded-full bg-foreground px-3 text-[12px] font-medium text-background">
                                {fixLabel}
                            </button>
                        )}
                        {!phone && more && <span className={cn('transition-opacity', showActions ? 'opacity-100' : 'pointer-events-none opacity-0')}>{more}</span>}
                    </span>
                ) : (
                    <span className={cn('relative flex shrink-0 items-center justify-end', !phone && 'min-w-[88px]')}>
                        <span
                            data-status
                            className={cn(
                                'inline-flex items-center gap-1 text-[12px] tabular-nums transition-opacity',
                                status.tone === 'stopped' ? 'text-red-600 dark:text-red-400' : status.tone === 'running' ? 'text-foreground' : 'text-muted-foreground',
                                showActions && 'opacity-0'
                            )}
                        >
                            {status.tone === 'running' && <Zap className="work-bolt h-3 w-3" strokeWidth={2.25} />}
                            {status.tone === 'paused' && <Pause className="h-3 w-3" strokeWidth={2.25} />}
                            {status.text}
                        </span>
                        {!phone && (
                            <span className={cn('absolute inset-y-0 right-0 flex items-center transition-opacity', showActions ? 'opacity-100' : 'pointer-events-none opacity-0')}>
                                {can('resume') && item.pausedItself ? (
                                    quick('Resume', <Play className="h-3.5 w-3.5" strokeWidth={2} />, () => actions.resume(item))
                                ) : (
                                    <>
                                        {can('test') && live && quick('Try it now', <Play className="h-3.5 w-3.5" strokeWidth={2} />, () => actions.test(item))}
                                        {can('pause') && quick('Pause', <Pause className="h-3.5 w-3.5" strokeWidth={2} />, () => actions.pause(item))}
                                    </>
                                )}
                                {more}
                            </span>
                        )}
                    </span>
                )}
                {phone && more}
            </div>
            {stopped && !open && item.reason && !line && (
                <p className="-mt-1 pb-2.5 pl-[46px] pr-2 text-[12px] leading-snug text-red-600 dark:text-red-400" data-reason>
                    {item.reason}
                </p>
            )}
            {open && children && <div className="pb-3 pl-[46px] pr-2 pt-1">{children}</div>}
        </div>
    );
}
