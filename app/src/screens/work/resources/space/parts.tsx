// The parts a space's Resources tab draws its lists and pages with: rows (each opening its page, its menu on hover),
// an item's mark, who here uses it, the way back, facts, and the one menu of everything that can be done to it.
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { ArrowLeft, ArrowUpRight, BookOpen, Brain, ChevronRight, Hash, Mail, MoreHorizontal, Pencil, Plug, Server, Trash2, UsersRound, X } from 'lucide-react';
import type { Connection } from 'noclick';
import { BrandIcon } from '@/ui/BrandIcon';
import { useInPhoneShell } from '@/ui/phoneBar';
import { standing } from '@/slots';
import { CONNECTION_MARK } from '@/ui/slots';
import { MENU_SURFACE } from '@/ui/menus';
import { Surface } from '@/screens/resources/ui';
import { PAGE_TITLE } from '@/ui/titles';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/ui/dropdown-menu';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../../client';
import { useWorkNav } from '../../nav';
import { Faces } from '../knowledge/parts';
import { PlaceIcon } from '../machines';
import { changeLevel, deleteRefusal, givable, removable, removeFromSpace, renamable, titleFor } from './actions';
import { kindOf, levelWords, type SpaceKind, type SpaceLink, type Thing } from './data';
import type { Pane } from './pane';

export const list = (names: string[]) => new Intl.ListFormat('en', { type: 'conjunction' }).format(names);
/** "a", "a and b", "a, b and 3 more". */
export const few = (names: string[], max = 2) => (names.length <= max ? list(names) : `${names.slice(0, max).join(', ')} and ${names.length - max} more`);
export const plural = (n: number, [one, many]: [string, string]) => `${n} ${n === 1 ? one : many}`;

export const enterOpens = (onOpen: () => void) => (event: KeyboardEvent) => {
    if (event.target !== event.currentTarget || (event.key !== 'Enter' && event.key !== ' ')) return;
    event.preventDefault();
    onOpen();
};

/** Its mark, drawn the same in a row, a picker and its page. */
export function markOf(t: Thing, connection?: Connection, className = 'h-4 w-4'): ReactNode {
    if (t.kind === 'connections') {
        if (!connection) return <Plug className={cn(className, 'text-foreground/70')} strokeWidth={1.75} />;
        const { Icon, iconColor } = standing(CONNECTION_MARK).accountGlyph({ credential_type: connection.credentialType ?? connection.integration, metadata: {} });
        return <BrandIcon Icon={Icon} iconColor={iconColor} className={className} />;
    }
    if (t.kind === 'skills' || t.kind === 'memories') {
        const Icon = t.kind === 'skills' ? BookOpen : Brain;
        return <Icon className={cn(className, 'text-foreground/75')} strokeWidth={1.75} />;
    }
    if (t.kind === 'machines') return t.place ? <PlaceIcon place={t.place} className={className} /> : <Server className={cn(className, 'text-foreground/75')} strokeWidth={1.75} />;
    const Icon = kindOf(t.kind).icon;
    return <Icon className={cn(className, 'text-foreground/75')} strokeWidth={1.75} />;
}

export function Lead({ mark }: { mark: ReactNode }) {
    return <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground/[0.06]">{mark}</span>;
}

export function List({ children }: { children: ReactNode }) {
    return <div className="divide-y divide-border overflow-hidden rounded-[20px] border border-border bg-card dark:divide-foreground/[0.06] dark:border-foreground/[0.08] dark:bg-foreground/[0.02]">{children}</div>;
}

export function Chip({ children }: { children: ReactNode }) {
    return <span className="inline-flex h-5 shrink-0 items-center rounded-full bg-foreground/[0.06] px-2 text-[11.5px] text-muted-foreground">{children}</span>;
}

/** "Also in Wirefern": the same one reaches agents in another space, so a change here shows there. Home, where every
 *  agent is, says where each is ("In Wirefern"). */
export function Also({ names, lead = 'Also in' }: { names: string[]; lead?: string }) {
    const unique = [...new Set(names)];
    return unique.length ? (
        <Chip>
            {lead} {list(unique)}
        </Chip>
    ) : null;
}

export function Count({ n }: { n: number }) {
    return <span className="grid h-[18px] min-w-[18px] shrink-0 place-items-center rounded-full bg-foreground px-1.5 text-[11px] font-semibold tabular-nums leading-none text-background">{n}</span>;
}

/** The agents here that use it, as faces and names. */
export function UsedBy({ pane, agentIds, note, extra }: { pane: Pane; agentIds: string[]; note?: string; extra?: string }) {
    const agents = agentIds.map((id) => pane.share.agent(id) ?? { id, name: '' }).filter((a) => a.name);
    const names = agents.length > 2 ? `${agents.length} agents` : list(agents.map((a) => a.name));
    return (
        <span className="hidden w-[190px] shrink-0 items-center gap-2 text-[12.5px] text-muted-foreground @2xl:flex">
            {agents.length ? <Faces agents={agents} /> : null}
            <span className="min-w-0 truncate">{agents.length ? [names, note, extra].filter(Boolean).join(' ') : pane.share.home ? 'No agent uses it' : 'No agent here uses it'}</span>
        </span>
    );
}

/** A quiet line under a list: the account owns these, and its page lists all of them. */
export function Owned({ what, lead, onOpen }: { what: string; lead?: string; onOpen: () => void }) {
    return (
        <p className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-muted-foreground">
            {lead}
            <button type="button" onClick={onOpen} className="inline-flex items-center gap-1 text-foreground/85 underline-offset-2 hover:underline">
                {what.charAt(0).toUpperCase() + what.slice(1)}
                <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={1.9} />
            </button>
        </p>
    );
}

export function Empty({ kind, home }: { kind: SpaceKind; home?: boolean }) {
    const def = kindOf(kind);
    const Icon = def.icon;
    return (
        <div className="flex flex-col items-center px-6 py-14 text-center">
            <span className="grid h-11 w-11 place-items-center rounded-full bg-foreground/[0.05]">
                <Icon className="h-5 w-5 text-foreground/70" strokeWidth={1.75} />
            </span>
            <p className="mt-4 text-[15px] font-semibold text-foreground">No {def.label.toLowerCase()} here</p>
            <p className="mt-1 max-w-sm text-[13.5px] leading-relaxed text-muted-foreground">
                {kind === 'machines'
                    ? 'A sandbox starts when one of its agents needs a shell.'
                    : kind === 'secrets'
                      ? 'A secret an agent here holds shows here by name, never its value.'
                      : home
                        ? 'Make one and it shows here.'
                        : 'Make one, or add one the account already has.'}
            </p>
        </div>
    );
}

/** The way back up: Resources, then its kind. A back arrow leads it in a narrow pane. */
export function Crumbs({ onAt, kind, end }: { onAt: Pane['onAt']; kind?: SpaceKind; end?: ReactNode }) {
    // The phone shell's top bar already has the way back.
    const phone = useInPhoneShell();
    const crumb = 'rounded-full px-2 py-0.5 transition-colors hover:bg-foreground/[0.05] hover:text-foreground';
    if (phone && !end) return null;
    return (
        <nav aria-label="Breadcrumb" className="-mt-1 mb-3 flex min-h-8 items-center gap-1 text-[13px] text-muted-foreground">
            {!phone && (
                <button
                    type="button"
                    aria-label="Back"
                    onClick={() => onAt(kind ? { kind } : null)}
                    className="-ml-1.5 mr-0.5 grid h-8 w-8 place-items-center rounded-full transition-colors hover:bg-foreground/[0.06] hover:text-foreground @2xl:hidden"
                >
                    <ArrowLeft className="h-4 w-4" strokeWidth={1.75} />
                </button>
            )}
            <button type="button" onClick={() => onAt(null)} className={cn(crumb, '-ml-2 hidden @2xl:inline')}>
                Resources
            </button>
            {kind && (
                <>
                    <ChevronRight className="hidden h-3.5 w-3.5 opacity-60 @2xl:block" />
                    <button type="button" onClick={() => onAt({ kind })} className={cn(crumb, 'hidden @2xl:inline')}>
                        {kindOf(kind).label}
                    </button>
                </>
            )}
            <ChevronRight className="hidden h-3.5 w-3.5 opacity-60 @2xl:block" />
            {end && <span className="ml-auto flex items-center gap-2">{end}</span>}
        </nav>
    );
}

/** Label and value rows, the way a resource's page lists its facts. */
export function Facts({ rows }: { rows: [string, ReactNode][] }) {
    return (
        <Surface className="px-4 py-1 sm:px-5">
            <dl className="divide-y divide-border dark:divide-foreground/[0.06]">
                {rows.map(([label, value]) => (
                    <div key={label} className="flex gap-4 py-2.5 text-[14px]">
                        <dt className="w-[132px] shrink-0 text-muted-foreground">{label}</dt>
                        <dd className="min-w-0 flex-1 text-foreground">{value}</dd>
                    </div>
                ))}
            </dl>
        </Surface>
    );
}

export function PageRow({ lead, title, sub, onOpen, hint }: { lead: ReactNode; title: string; sub: string; onOpen: () => void; hint: string }) {
    return (
        <div role="button" tabIndex={0} onClick={onOpen} onKeyDown={enterOpens(onOpen)} className="group flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-foreground/[0.03]">
            {lead}
            <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-medium">{title}</span>
                <span className="block text-[12.5px] leading-snug text-muted-foreground">{sub}</span>
            </span>
            <span className="hidden text-[12.5px] text-muted-foreground @xl:block">{hint}</span>
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform duration-200 group-hover:translate-x-0.5" />
        </div>
    );
}

/** A name edited in place: Enter or leaving it keeps it, Escape puts it back. */
export function NameInput({ value, prefix, onDone, big }: { value: string; prefix?: string; onDone: (next: string | null) => void; big?: boolean }) {
    const [draft, setDraft] = useState(value);
    const done = useRef(false);
    const input = useRef<HTMLInputElement>(null);
    useEffect(() => {
        input.current?.focus();
        input.current?.select();
    }, []);
    const finish = (next: string | null) => {
        if (done.current) return;
        done.current = true;
        onDone(next?.trim() || null);
    };
    return (
        <span className={cn('flex min-w-0 flex-1 items-center', big ? PAGE_TITLE : 'text-[14px] font-medium')}>
            {prefix && <span className="text-muted-foreground">{prefix}</span>}
            <input
                ref={input}
                value={draft}
                aria-label="Name"
                onChange={(e) => setDraft(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => {
                    e.stopPropagation();
                    if (e.key === 'Enter') finish(draft);
                    if (e.key === 'Escape') finish(null);
                }}
                onBlur={() => finish(draft)}
                className={cn(
                    'min-w-0 flex-1 rounded-full bg-foreground/[0.05] outline-none ring-1 ring-inset ring-foreground/20 focus:ring-foreground/40',
                    big ? 'h-12 px-4 font-[inherit] text-[inherit]' : '-my-1 h-7 px-2.5'
                )}
            />
        </span>
    );
}

const MENU_ITEM = 'gap-2.5 rounded-lg px-2.5 py-2 text-[14px]';
const MENU_ICON = 'h-4 w-4 text-muted-foreground';
const MENU_RULE = 'mx-1 bg-border dark:bg-foreground/[0.08]';

const DELETE_LABEL: Partial<Record<SpaceKind, string>> = {
    agents: 'Delete agent…',
    machines: 'Remove computer…',
    channels: 'Delete channel…',
    connections: 'Remove connection…',
    secrets: 'Remove secret…',
    numbers: 'Release number…',
    email: 'Delete address…',
};

/** What the space's members or its guests get of a shared resource, as a menu of its kind's levels, or as words for
 *  someone who can't change it. */
export function LevelMenu({ spaceId, link, who, readOnly }: { spaceId: string; link: SpaceLink; who: 'members' | 'guests'; readOnly?: boolean }) {
    const client = useWorkClient();
    const value = who === 'members' ? link.membersLevel : link.guestsLevel;
    if (readOnly) return <span className="text-[13.5px] text-foreground/85">{levelWords(link.kind, value)}</span>;
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                aria-label={`What ${who === 'members' ? 'people here' : 'guests'} get of ${link.name}`}
                className="inline-flex h-8 max-w-full items-center gap-1 rounded-full px-3 text-[13.5px] text-foreground ring-1 ring-inset ring-border transition-colors hover:bg-foreground/[0.05] data-[state=open]:bg-foreground/[0.06] dark:ring-foreground/[0.12]"
            >
                <span className="truncate">{levelWords(link.kind, value)}</span>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 rotate-90 text-muted-foreground" strokeWidth={2} />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" sideOffset={6} className={cn('min-w-[200px] rounded-xl p-1', MENU_SURFACE)}>
                <DropdownMenuRadioGroup value={value} onValueChange={(v) => void changeLevel(client, spaceId, link, who, v)}>
                    {link.levels.map((l) => (
                        <DropdownMenuRadioItem key={l} value={l} className="rounded-lg py-2 text-[14px]">
                            {levelWords(link.kind, l)}
                        </DropdownMenuRadioItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

/** Everything you can do to one item: rename it, set what the space's people get, open it, take it out of the space
 *  (with Undo), or, under a rule and in red, delete it from the account. Home's give it to a space instead. */
export function ThingMenu({ pane, t, onRename, className, onPage, label }: { pane: Pane; t: Thing; onRename?: () => void; className?: string; onPage?: boolean; label?: string }) {
    const client = useWorkClient();
    const nav = useWorkNav();
    const renameChosen = useRef(false);
    const owner = t.knowledge?.kind === 'memory' && t.knowledge.agentId ? pane.share.agent(t.knowledge.agentId)?.name : undefined;
    const refusal = deleteRefusal(t, owner);
    const machineAgent = t.machine?.agentId ?? null;
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                aria-label={label ?? `More for ${titleFor(t)}`}
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => e.stopPropagation()}
                className={cn(
                    'grid shrink-0 place-items-center rounded-full text-muted-foreground transition-[opacity,background-color] hover:bg-foreground/[0.07] hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.07] data-[state=open]:text-foreground data-[state=open]:opacity-100',
                    label ? 'h-8 grid-flow-col gap-1 px-3 text-[13px]' : 'h-8 w-8',
                    className
                )}
            >
                {label ? (
                    <>
                        {label}
                        <ChevronRight className="h-3.5 w-3.5 rotate-90" strokeWidth={2} />
                    </>
                ) : (
                    <MoreHorizontal className="h-[18px] w-[18px]" />
                )}
            </DropdownMenuTrigger>
            <DropdownMenuContent
                align="end"
                sideOffset={6}
                onClick={(e) => e.stopPropagation()}
                onCloseAutoFocus={(e) => {
                    if (!renameChosen.current) return;
                    renameChosen.current = false;
                    e.preventDefault();
                }}
                className={cn('w-[256px] rounded-xl p-1', MENU_SURFACE)}
            >
                {onRename && renamable(t) && (
                    <DropdownMenuItem
                        onSelect={() => {
                            renameChosen.current = true;
                            onRename();
                        }}
                        className={MENU_ITEM}
                    >
                        <Pencil className={MENU_ICON} strokeWidth={1.75} />
                        Rename
                    </DropdownMenuItem>
                )}
                {!onPage && (
                    <DropdownMenuItem onSelect={() => pane.open(t)} className={MENU_ITEM}>
                        <ArrowUpRight className={MENU_ICON} strokeWidth={1.75} />
                        {t.kind === 'agents' ? 'Open its profile' : 'Open its page'}
                    </DropdownMenuItem>
                )}
                {t.kind === 'agents' && (
                    <DropdownMenuItem onSelect={() => nav.openAgent(t.ref)} className={MENU_ITEM}>
                        <Mail className={MENU_ICON} strokeWidth={1.75} />
                        Message {t.name}
                    </DropdownMenuItem>
                )}
                {t.kind === 'machines' && machineAgent && (
                    <DropdownMenuItem onSelect={() => nav.openMachine(machineAgent)} className={MENU_ITEM}>
                        <Server className={MENU_ICON} strokeWidth={1.75} />
                        Open the machine
                    </DropdownMenuItem>
                )}
                {t.kind === 'channels' && (
                    <DropdownMenuItem onSelect={() => nav.openChannel(t.ref)} className={MENU_ITEM}>
                        <Hash className={MENU_ICON} strokeWidth={1.75} />
                        Open the channel
                    </DropdownMenuItem>
                )}
                {t.link && t.link.levels.length > 0 && (
                    <>
                        <DropdownMenuSeparator className={MENU_RULE} />
                        <DropdownMenuLabel className="px-2.5 pb-1 pt-1.5 text-xs font-normal text-muted-foreground">People here get</DropdownMenuLabel>
                        <DropdownMenuRadioGroup value={t.link.membersLevel} onValueChange={(v) => void changeLevel(client, pane.spaceId, t.link!, 'members', v)}>
                            {t.link.levels.map((l) => (
                                <DropdownMenuRadioItem key={l} value={l} className="rounded-lg py-2 text-[14px]">
                                    {levelWords(t.link!.kind, l)}
                                </DropdownMenuRadioItem>
                            ))}
                        </DropdownMenuRadioGroup>
                    </>
                )}
                {pane.share.home && givable(t) && (
                    <>
                        <DropdownMenuSeparator className={MENU_RULE} />
                        <DropdownMenuItem onSelect={() => pane.ask({ kind: 'share', key: t.key })} className={MENU_ITEM}>
                            <UsersRound className={MENU_ICON} strokeWidth={1.75} />
                            {t.kind === 'agents' ? 'Add to a space…' : 'Share with a space…'}
                        </DropdownMenuItem>
                    </>
                )}
                {!pane.share.home && removable(t) && (
                    <>
                        <DropdownMenuSeparator className={MENU_RULE} />
                        <DropdownMenuItem
                            onSelect={() => {
                                void removeFromSpace(client, pane.spaceId, t, t.kind === 'agents' ? (pane.share.agent(t.ref)?.elsewhere ?? []) : []);
                                if (onPage) pane.onAt({ kind: t.kind });
                            }}
                            className={MENU_ITEM}
                        >
                            <X className={MENU_ICON} strokeWidth={1.75} />
                            Remove from this space
                        </DropdownMenuItem>
                    </>
                )}
                {(t.kind !== 'machines' || t.place?.kind === 'own') && (
                    <>
                        <DropdownMenuSeparator className={MENU_RULE} />
                        <DropdownMenuItem
                            disabled={!!refusal}
                            onSelect={() => pane.ask({ kind: 'delete', key: t.key })}
                            className={cn(MENU_ITEM, 'items-start text-red-600 focus:bg-red-500/10 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400')}
                        >
                            <Trash2 className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={1.75} />
                            <span>
                                <span className="block">{DELETE_LABEL[t.kind] ?? 'Delete…'}</span>
                                {refusal && <span className="block text-xs text-muted-foreground">{refusal}</span>}
                            </span>
                        </DropdownMenuItem>
                    </>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}

export interface RowProps {
    lead?: ReactNode;
    badge?: ReactNode;
    sub?: ReactNode;
    /** The line under it is what waits on you. */
    strong?: boolean;
    /** The line under it says what's broken. */
    attention?: boolean;
    cols?: ReactNode;
    trailing?: ReactNode;
    /** A width kept for the trailing action on every row of a list, so the columns line up. */
    slot?: string;
    connection?: Connection;
}

/** One item: what it is and a line on it, who here uses it, then its one action and its menu. The row opens its page. */
export function Row({ pane, t, lead, badge, sub, strong, attention, cols, trailing, slot, connection }: RowProps & { pane: Pane; t: Thing }) {
    const client = useWorkClient();
    const [renaming, setRenaming] = useState(false);
    const open = () => !renaming && pane.open(t);
    return (
        <div
            role="button"
            tabIndex={0}
            aria-label={titleFor(t)}
            onClick={open}
            onKeyDown={enterOpens(open)}
            className="group flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-foreground/[0.03] focus-visible:bg-foreground/[0.03] focus-visible:outline-none"
            data-testid={`row-${t.key}`}
        >
            {lead ?? <Lead mark={markOf(t, connection)} />}
            <span className="min-w-0 flex-1">
                <span className="flex min-w-0 items-center gap-2">
                    {renaming ? (
                        <NameInput
                            value={t.name}
                            prefix={t.kind === 'channels' ? '#' : undefined}
                            onDone={(next) => {
                                setRenaming(false);
                                if (next && next !== t.name) void pane.rename(client, t, next);
                            }}
                        />
                    ) : (
                        <span className="truncate text-[14px] font-medium text-foreground">{titleFor(t)}</span>
                    )}
                    {!renaming && badge}
                </span>
                <span className={cn('block truncate text-[12.5px]', attention ? 'text-red-600 dark:text-red-400' : strong ? 'font-medium text-foreground' : 'text-muted-foreground')}>{sub}</span>
            </span>
            {cols}
            {slot ? <span className={cn('flex shrink-0 justify-end', slot)}>{trailing}</span> : trailing}
            <ThingMenu pane={pane} t={t} onRename={() => setRenaming(true)} className="opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 [@media(hover:none)]:opacity-100" />
        </div>
    );
}
