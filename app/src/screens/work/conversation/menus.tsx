// The menus the box opens, t3code's drawer: `/` for NoClick's own controls and then the commands the session's
// harness reports (those NoClick has a control of its own for open that control, as /mcp opens what the agent can
// use; those it never runs from a chat are said, not offered), `@` for its files, agents and people, `$` for its skills. One compact row each: the name, what it
// does on the same line, its source at the right. The order is the grouping.
import { Fragment, useEffect, useRef, type ReactNode } from 'react';
import { Bot, FileText, FolderOpen, Sparkles, UserRound } from 'lucide-react';
import type { AgentCommands } from 'noclick';
import { cn } from '@/ui/utils';
import { DRAWER, TUCK } from './styles';

/** What NoClick does itself when one of its commands is picked, the same on every harness. */
export type Control = 'model' | 'effort' | 'clear' | 'resume' | 'usage' | 'context' | 'tools' | 'help' | 'loop' | 'rename';

/** One row of a menu: a command, a file, an agent, a person, a skill. */
export interface MenuItem {
    key: string;
    group: string;
    title: string;
    hint?: string;
    detail?: string;
    tag?: string;
    icon?: ReactNode;
    pick: () => void;
}

export interface Menu {
    label: string;
    items: MenuItem[];
    /** Group names over their rows. */
    grouped: boolean;
    /** A hairline between groups, without their names. */
    separated?: boolean;
    notes?: ReactNode;
    footer?: ReactNode;
}

/** One entry of the `/` menu: NoClick's control, or the harness's own command to run. */
export type SlashCommand = { kind: 'control'; control: Control; name: string; aliases: string[]; hint: string; description: string } | { kind: 'harness'; name: string; aliases: string[]; hint: string; description: string; source: string };

/** NoClick's own commands, ahead of the harness's. */
const CONTROLS: { control: Control; name: string; aliases: string[]; hint?: string; description: string }[] = [
    { control: 'model', name: 'model', aliases: [], description: 'Change the model its next message runs on' },
    { control: 'effort', name: 'effort', aliases: ['fast'], description: 'How hard it thinks, and how fast' },
    { control: 'clear', name: 'clear', aliases: ['new', 'reset'], description: 'Start it fresh for everyone; this session is kept to resume' },
    { control: 'resume', name: 'resume', aliases: [], description: 'Switch everyone back to an earlier session' },
    { control: 'usage', name: 'usage', aliases: ['cost', 'stats'], description: 'What this session has cost, and its plan’s limits' },
    { control: 'context', name: 'context', aliases: [], description: 'How full its context is' },
    // The harnesses' own /mcp (and Codex's /apps, OpenCode's /mcps) would change what NoClick sets up: this is NoClick's.
    { control: 'tools', name: 'mcp', aliases: ['tools', 'apps', 'mcps'], description: 'Add apps and tools this agent can use' },
    { control: 'help', name: 'help', aliases: [], description: 'What you can do here' },
    // NoClick keeps a loop's time, so it runs on while the sandbox is paused (a harness's own /loop wouldn't).
    { control: 'loop', name: 'loop', aliases: [], hint: '[5m] <prompt> | stop', description: 'Run a prompt again and again: every so often, or when it decides' },
    // The agent's own name, never the session's (a harness's /rename names its session): its old name still reaches it.
    { control: 'rename', name: 'rename', aliases: [], hint: '<new name>', description: 'Give this agent a new name; its old one still reaches it' },
];

/** Every one of NoClick's own commands, for a page that offers all but some (a NoClick's conversation has no /rename). */
export const CONTROL_NAMES: readonly Control[] = CONTROLS.map((c) => c.control);

/** Where a harness's mapped command goes: the control of NoClick's that takes its place. */
const MAPPED_TO: Record<string, Control | null> = { model: 'model', effort: 'effort', new: 'clear', usage: 'usage', context: 'context', loop: 'loop', ask: null, delivery: null };

const SOURCE_TAG: Record<string, string> = { custom: 'Yours', mcp: 'MCP', skill: 'Skill' };

/** The `/` menu's entries: NoClick's controls (with the harness's names for them as aliases), then what the harness
 *  reports and NoClick runs. `controls`: which of NoClick's own the box offers (every one where absent). */
export function slashCommands(commands: AgentCommands | null, controls?: readonly Control[]): SlashCommand[] {
    const aliases = new Map<Control, string[]>();
    for (const m of commands?.mapped ?? []) {
        const to = MAPPED_TO[m.to];
        if (to) aliases.set(to, [...(aliases.get(to) ?? []), m.name]);
    }
    const mapped = new Set((commands?.mapped ?? []).map((m) => m.name));
    const own: SlashCommand[] = CONTROLS.filter((c) => !controls || controls.includes(c.control)).map((c) => ({ kind: 'control', control: c.control, name: c.name, aliases: [...new Set([...c.aliases, ...(aliases.get(c.control) ?? [])])].filter((a) => a !== c.name), hint: c.hint ?? '', description: c.description }));
    const taken = new Set(own.flatMap((c) => [c.name, ...c.aliases]));
    const withheld = new Set(commands?.withheld ?? []);
    const harness: SlashCommand[] = (commands?.commands ?? [])
        .filter((c) => !mapped.has(c.name) && !taken.has(c.name) && !withheld.has(c.name))
        .map((c) => ({ kind: 'harness', name: c.name, aliases: c.aliases, hint: c.argumentHint, description: c.description, source: c.source }));
    return [...own, ...harness];
}

/** A typed `/name args` the menu knows, by name or alias. Anything else starting with / is a message. */
export function commandIn(list: SlashCommand[], text: string): { command: SlashCommand; args: string } | null {
    const m = /^\/(\S+)(?:\s+([\s\S]*))?$/.exec(text.trim());
    const command = m && list.find((c) => c.name === m[1] || c.aliases.includes(m[1]));
    return command ? { command, args: (m[2] ?? '').trim() } : null;
}

function scoreName(name: string, detail: string, query: string): number {
    const n = name.toLowerCase();
    if (n.startsWith(query)) return 4;
    if (n.includes(query)) return 3;
    let at = 0;
    for (const ch of n) if (ch === query[at]) at++;
    if (at === query.length) return 2;
    return detail.toLowerCase().includes(query) ? 1 : 0;
}

/** Ranked by name (or any alias) before description, as t3code ranks its menu; in order while nothing's typed. */
export function rank<T>(list: T[], query: string, names: (t: T) => string[], detail: (t: T) => string): T[] {
    const q = query.toLowerCase();
    if (!q) return list;
    return list
        .map((t, i) => ({ t, i, score: Math.max(...names(t).map((n) => scoreName(n, detail(t), q))) }))
        .filter((x) => x.score > 0)
        .sort((a, b) => b.score - a.score || a.i - b.i)
        .map((x) => x.t);
}

export function slashMenu(list: SlashCommand[], commands: AgentCommands | null, harnessLabel: string, query: string, pick: (c: SlashCommand) => void): Menu {
    const ranked = rank(list, query, (c) => [c.name, ...c.aliases], (c) => c.description);
    const q = query.toLowerCase();
    const own = new Set(list.flatMap((c) => (c.kind === 'control' ? [c.name, ...c.aliases] : [])));
    const withheld = q ? (commands?.withheld ?? []).filter((n) => n.startsWith(q) && !own.has(n)) : [];
    const unsupported = q ? Object.entries(commands?.notSupported ?? {}).filter(([n]) => n.startsWith(q)) : [];
    return {
        label: 'Commands',
        grouped: false,
        separated: !query,
        items: ranked.map((c) => {
            const alias = q && !c.name.startsWith(q) ? c.aliases.find((a) => a.startsWith(q)) : undefined;
            return {
                key: `${c.kind}-${c.name}`,
                group: c.kind === 'control' ? 'NoClick' : c.source === 'harness' ? harnessLabel : (SOURCE_TAG[c.source] ?? c.source),
                title: `/${c.name}`,
                hint: c.hint || undefined,
                detail: c.description,
                tag: alias ? `as /${alias}` : c.kind === 'harness' && c.source !== 'harness' ? SOURCE_TAG[c.source] : undefined,
                pick: () => pick(c),
            };
        }),
        notes: (
            <>
                {withheld.map((n) => (
                    <p key={n} className="flex items-baseline gap-2 px-2.5 py-1.5 text-xs text-muted-foreground">
                        <span className="shrink-0 font-medium text-foreground/80">/{n}</span>
                        <span className="min-w-0">Changes the setup NoClick keeps for this agent, so it doesn’t run from here. Say what you need in a message.</span>
                    </p>
                ))}
                {unsupported.map(([n, why]) => (
                    <p key={n} className="flex items-baseline gap-2 px-2.5 py-1.5 text-xs text-muted-foreground">
                        <span className="shrink-0 font-medium text-foreground/80">/{n}</span>
                        <span className="min-w-0">{why}</span>
                    </p>
                ))}
                {query && !ranked.length && !withheld.length && !unsupported.length && <p className="px-2.5 pb-3 pt-2 text-xs text-muted-foreground">No matching command. Sent as it is, /{query} is an ordinary message.</p>}
                {/* A harness that runs commands lists them from its sandbox; NoClick's own runtime has none to list. */}
                {!query && commands?.capabilities.commands && !commands.asOf && <p className="px-2.5 pb-1.5 pt-2 text-xs text-muted-foreground">Its harness lists its own commands once its sandbox has started: send it a message first.</p>}
            </>
        ),
    };
}

/** Someone or something `@` can name: a file of its workspace, another agent, a person. */
export interface Mentionable {
    kind: 'file' | 'folder' | 'agent' | 'person';
    name: string;
    detail?: string;
    /** What goes in the message. */
    text: string;
    /** Other names it's found by: an agent's from before it was renamed. */
    aliases?: string[];
}

/** The alias of `m` that `query` finds, when its own name doesn't: the old name someone typed. */
function aliasFound(m: Mentionable, query: string): string | undefined {
    const q = query.toLowerCase();
    if (!q || m.name.toLowerCase().includes(q)) return undefined;
    return m.aliases?.find((a) => a.toLowerCase().includes(q));
}

const MENTION_ICON = { file: FileText, folder: FolderOpen, agent: Bot, person: UserRound } as const;
const MENTION_GROUP = { file: 'Files', folder: 'Folders', agent: 'Agents', person: 'People' } as const;

export function mentionMenu(all: Mentionable[] | null, query: string, pick: (m: Mentionable) => void): Menu {
    const q = query.toLowerCase();
    // Each kind keeps a few rows, so one kind never crowds out the rest.
    const few = q ? 6 : 4;
    const order: Mentionable['kind'][] = ['file', 'folder', 'agent', 'person'];
    const items = order.flatMap((kind) =>
        rank((all ?? []).filter((m) => m.kind === kind), query, (m) => [m.name, ...(m.aliases ?? [])], (m) => m.detail ?? '')
            .slice(0, few)
            .map((m) => {
                const Icon = MENTION_ICON[kind];
                const old = aliasFound(m, query);
                return { key: `${kind}:${m.text}`, group: MENTION_GROUP[kind], title: m.name, detail: old ? `Formerly ${old}` : m.detail, icon: <Icon className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />, pick: () => pick(m) };
            })
    );
    return {
        label: 'Mention',
        grouped: true,
        items,
        notes: !items.length && <p className="px-2.5 pb-3 pt-2 text-xs text-muted-foreground">{all === null ? 'Looking through its files…' : 'No matching files, agents or people.'}</p>,
    };
}

export function skillsMenu(commands: AgentCommands | null, agentName: string, query: string, pick: (name: string) => void): Menu {
    const skills = rank(commands?.skills ?? [], query, (s) => [s.name], (s) => s.description);
    return {
        label: 'Skills',
        grouped: false,
        items: skills.map((s) => ({ key: s.name, group: 'Skills', title: `$${s.name}`, detail: s.description, icon: <Sparkles className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={2} />, pick: () => pick(s.name) })),
        notes: !skills.length && <p className="px-2.5 pb-3 pt-2 text-xs text-muted-foreground">{query ? 'No skills found. Try / to browse its commands.' : `${agentName} has no skills yet.`}</p>,
    };
}

/** A drawer pulled out from behind the box's top edge: a menu, /usage, /context, /help. */
export function ComposerDrawer({ children, role = 'dialog', label, className }: { children: ReactNode; role?: string; label: string; className?: string }) {
    return (
        <div
            role={role}
            aria-label={label}
            className={cn('wc-drawer absolute inset-x-[1.375rem] z-[5] overflow-hidden shadow-[0_-16px_40px_-24px_rgb(0_0_0/0.45)] dark:shadow-[0_-16px_40px_-20px_rgb(0_0_0/0.9)]', DRAWER, className)}
            style={{ bottom: `calc(100% - ${TUCK}px)`, paddingBottom: TUCK }}
        >
            {children}
        </div>
    );
}

/** The menu the box opens, t3code's: compact one-line rows, the name then what it does, its source at the right. */
export function MenuOverlay({ menu, active, onActive }: { menu: Menu; active: number; onActive: (i: number) => void }) {
    const rows = useRef<(HTMLButtonElement | null)[]>([]);
    useEffect(() => {
        rows.current[active]?.scrollIntoView?.({ block: 'nearest' });
    }, [active]);
    return (
        <ComposerDrawer role="listbox" label={menu.label}>
            <div className="max-h-72 scroll-pb-6 overflow-y-auto p-2 scrollbar-subtle">
                {menu.items.map((item, i) => (
                    <Fragment key={item.key}>
                        {menu.separated && i > 0 && menu.items[i - 1].group !== item.group && <div aria-hidden className="mx-2 my-1 h-px bg-border dark:bg-foreground/[0.07]" />}
                        {menu.grouped && (i === 0 || menu.items[i - 1].group !== item.group) && <p className={cn('px-2.5 pb-1 text-[11px] font-medium leading-4 text-muted-foreground', i ? 'pt-2.5' : 'pt-1')}>{item.group}</p>}
                        <button
                            ref={(el) => {
                                rows.current[i] = el;
                            }}
                            type="button"
                            role="option"
                            aria-selected={i === active}
                            onMouseDown={(e) => e.preventDefault()}
                            onMouseMove={() => i !== active && onActive(i)}
                            onClick={item.pick}
                            className={cn('flex min-h-7 w-full items-center gap-2 rounded-[18px] px-2.5 py-1.5 text-left', i === active && 'bg-foreground/[0.06]')}
                        >
                            {item.icon && <span className="grid h-4 w-4 shrink-0 place-items-center">{item.icon}</span>}
                            <span className="max-w-[45%] shrink-0 truncate text-xs font-medium text-foreground">{item.title}</span>
                            {item.hint && <span className="shrink-0 text-xs text-muted-foreground/70">{item.hint}</span>}
                            {item.detail && <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{item.detail}</span>}
                            {item.tag && <span className="ml-auto shrink-0 rounded-full bg-foreground/[0.06] px-2 py-px text-[10px] font-medium leading-4 text-muted-foreground">{item.tag}</span>}
                        </button>
                    </Fragment>
                ))}
                {menu.notes}
            </div>
            {menu.footer}
        </ComposerDrawer>
    );
}

