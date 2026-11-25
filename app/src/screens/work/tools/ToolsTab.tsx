// An agent's profile's Tools tab: everything on the account, or Restricted to what's allowed, app by app. Each
// connection of its scope, NoClick and the web is a row with its account, how often it ran this week and a switch;
// opening one lists its actions, each Allowed, Ask first or Off (a search, what it used and its groups for an app with
// many). Under Everything they say what holds; Restricted makes them changeable. Each change writes the agent's rules
// whole (a list of tools becomes everything with rules the first time), and a turn answering someone else still waits
// for the owner's yes on their other accounts.
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { ChevronRight, Globe, ShieldCheck } from 'lucide-react';
import { Agent, type AgentToolAction, type AgentToolApp, type ToolRule, type ToolRules } from 'noclick';
import { errorText } from '@/screens/console/pages/resources/shared';
import { HAIRLINE } from '@/ui/primitives';
import { Switch } from '@/ui/switch';
import { SearchField } from '@/ui/SearchField';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { HarnessMark } from '../agents/harness';
import { AppMark, catalogApp } from '../newAgent/wakes';
import { rereadAgent, useToolAccess } from '../profile/reads';
import { actionView, exceptionsOf, isOn, KIND_WORDS, modeOf, rulesForMode, usageLine, verdictOf, withAction, withApp, type ToolsMode } from './access';
import { toEverything, toolRows, type ToolEntry } from '@/lib/agentTools';

const VERDICTS: [ToolRule, string][] = [
    ['allow', 'Allowed'],
    ['ask', 'Ask first'],
    ['off', 'Off'],
];
const VERDICT_WORD = Object.fromEntries(VERDICTS) as Record<ToolRule, string>;
const SECTION = 'mb-0.5 mt-2.5 text-[11.5px] font-medium text-muted-foreground first:mt-0';
export const STRANGERS_NOTE = 'When someone other than you is talking to it, anything on your other accounts still waits for your yes.';

export function ToolsTab({ agent, name }: { agent: Agent; name: string }) {
    const client = useWorkClient();
    const access = useToolAccess(agent.id);
    // What was just written, shown until the read after the last write says it.
    const [pending, setPending] = useState<ToolRules | null>(null);
    const writing = useRef(0);
    useEffect(() => {
        if (!writing.current) setPending(null);
    }, [access.data]);
    const [open, setOpen] = useState<string | null>(null);
    const data = access.data;
    const rules = pending ?? data?.rules ?? {};
    const latest = useRef(rules);
    latest.current = rules;

    const save = async (change: (now: ToolRules) => ToolRules, done?: string) => {
        if (!data) return;
        const before = latest.current;
        const next = change(before);
        latest.current = next;
        setPending(next);
        writing.current += 1;
        try {
            // A list of tools becomes everything, its rules saying what's on (``toEverything``).
            await Agent.fromId(agent.id, { client }).update(data.listed ? { tools: toEverything(agent.tools as ToolEntry[]), toolRules: next } : { toolRules: next });
            if (done) toast(done, { description: `${name} follows it from its next call.` });
        } catch (error) {
            latest.current = before;
            setPending(before);
            toast(`Couldn’t change what ${name} can use`, { description: errorText(error) });
        } finally {
            writing.current -= 1;
            rereadAgent(agent.id);
        }
    };

    if (!data)
        return (
            <div className="px-5 pb-10 pt-5" data-testid="agent-tools">
                {access.error !== undefined ? (
                    <p className="text-[13px] text-muted-foreground">Couldn’t load what {name} can use.</p>
                ) : (
                    <div className="flex flex-col gap-2" aria-label="Loading what it can use">
                        <span className="h-[68px] animate-pulse rounded-[18px] bg-foreground/[0.04]" />
                        {[0, 1, 2, 3].map((i) => (
                            <span key={i} className="h-12 animate-pulse rounded-[14px] bg-foreground/[0.04]" />
                        ))}
                    </div>
                )}
            </div>
        );

    const mode = modeOf(rules);
    const restricted = mode === 'restricted';
    const setMode = (to: ToolsMode) => {
        if (to === mode) return;
        void save(
            (now) => rulesForMode(now, data.apps, to),
            to === 'restricted' ? `${name} is restricted to what’s allowed` : `${name} can use everything on your account`
        );
    };
    return (
        <div className="px-5 pb-10 pt-5" data-testid="agent-tools" data-mode={mode}>
            <Banner mode={mode} onMode={setMode} />
            <div className="mt-2" role="list" aria-label="Its apps">
                {data.apps.map((app) => (
                    <AppRow
                        key={app.app}
                        app={app}
                        rules={rules}
                        restricted={restricted}
                        open={open === app.app}
                        onOpen={() => setOpen(open === app.app ? null : app.app)}
                        onSwitch={(on) => void save((now) => withApp(now, app, on))}
                        onAction={(action, verdict) => void save((now) => withAction(now, app, action, verdict))}
                    />
                ))}
            </div>
            <AlsoLine tools={agent.tools as ToolEntry[]} />
            <p className="mt-4 flex items-start gap-2 text-[12.5px] leading-snug text-muted-foreground" data-testid="strangers-note">
                <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                {STRANGERS_NOTE}
            </p>
        </div>
    );
}

function Banner({ mode, onMode }: { mode: ToolsMode; onMode: (mode: ToolsMode) => void }) {
    const restricted = mode === 'restricted';
    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2.5 rounded-[18px] bg-foreground/[0.03] px-3.5 py-3 ring-1 ring-inset ring-foreground/[0.06]" data-testid="tools-banner">
            <div className="min-w-[15rem] flex-1">
                <p className="text-[14px] font-semibold leading-5">{restricted ? 'Restricted' : 'Everything on your account'}</p>
                <p className="mt-0.5 text-[12.5px] leading-snug text-muted-foreground">
                    {restricted ? 'Only what’s allowed below. Apps you connect later start off.' : 'Every app you’ve connected, and ones you connect later, plus NoClick and the web.'}
                </p>
            </div>
            <div role="radiogroup" aria-label="What it can use" className="inline-flex shrink-0 rounded-full bg-foreground/[0.06] p-[3px]">
                {(['everything', 'restricted'] as const).map((m) => (
                    <button
                        key={m}
                        type="button"
                        role="radio"
                        aria-checked={mode === m}
                        onClick={() => onMode(m)}
                        className={cn(
                            'h-7 rounded-full px-3 text-[12.5px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                            mode === m ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground'
                        )}
                    >
                        {m === 'everything' ? 'Everything' : 'Restricted'}
                    </button>
                ))}
            </div>
        </div>
    );
}

function AppIcon({ app }: { app: AgentToolApp }) {
    const mark =
        app.kind === 'noclick' ? (
            <HarnessMark harness="sdk" className="h-4 w-4" />
        ) : app.kind === 'web' ? (
            <Globe className="h-4 w-4 text-foreground/75" strokeWidth={2} />
        ) : (
            <AppMark nodeType={catalogApp(app.integration ?? app.app, app.credentialType ? [app.credentialType] : []).nodeType} className="h-[18px] w-[18px]" />
        );
    return <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground/[0.06]">{mark}</span>;
}

/** Who the app acts as, and how often it ran: "rowan@acme.test · 12 uses this week". */
function appLine(app: AgentToolApp): { text: string; down: boolean } {
    const down = app.status === 'disconnected';
    const who = down ? 'Needs reconnecting' : app.status === 'pending' ? 'Waiting for its account' : app.kind === 'integration' ? 'Needs no account' : app.account;
    return { text: [who, usageLine(app.calls)].filter(Boolean).join(' · '), down };
}

function AppRow({
    app,
    rules,
    restricted,
    open,
    onOpen,
    onSwitch,
    onAction,
}: {
    app: AgentToolApp;
    rules: ToolRules;
    restricted: boolean;
    open: boolean;
    onOpen: () => void;
    onSwitch: (on: boolean) => void;
    onAction: (action: AgentToolAction, verdict: ToolRule) => void;
}) {
    const on = isOn(rules, app);
    const line = appLine(app);
    const exceptions = on ? exceptionsOf(rules, app) : 0;
    return (
        <div className={cn('border-t first:border-t-0', HAIRLINE)} role="listitem" data-app={app.app} data-on={on}>
            <div className="flex items-center gap-3 py-2.5">
                <button type="button" onClick={onOpen} aria-expanded={open} className="flex min-w-0 flex-1 items-center gap-3 rounded-[14px] text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    <AppIcon app={app} />
                    <span className={cn('min-w-0 flex-1', !on && 'opacity-60')}>
                        <span className="flex min-w-0 items-center gap-2">
                            <span className="truncate text-[14px] font-medium leading-5">{app.label}</span>
                            {exceptions > 0 && (
                                <span className="shrink-0 whitespace-nowrap rounded-full bg-foreground/[0.06] px-2 text-[11.5px] leading-[18px] text-foreground/75" data-testid="app-exceptions">
                                    {exceptions} {exceptions === 1 ? 'exception' : 'exceptions'}
                                </span>
                            )}
                        </span>
                        <span className={cn('block truncate text-[12.5px] leading-4', line.down ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>{line.text}</span>
                    </span>
                </button>
                <Switch checked={on} disabled={!restricted} onCheckedChange={onSwitch} aria-label={`${app.label}: ${on ? 'on' : 'off'}`} className="relative disabled:cursor-default max-md:after:absolute max-md:after:-inset-x-1 max-md:after:-inset-y-2.5 max-md:after:content-['']" />
                <button type="button" onClick={onOpen} aria-label={open ? `Hide ${app.label}’s actions` : `Show ${app.label}’s actions`} className="grid h-7 w-5 shrink-0 place-items-center text-muted-foreground transition-colors hover:text-foreground max-md:-mx-2.5 max-md:h-10 max-md:w-10">
                    <ChevronRight className={cn('h-4 w-4 transition-transform duration-200 motion-reduce:transition-none', open && 'rotate-90')} strokeWidth={2} />
                </button>
            </div>
            {open && <Actions app={app} rules={rules} restricted={restricted} onAction={onAction} />}
        </div>
    );
}

function Actions({ app, rules, restricted, onAction }: { app: AgentToolApp; rules: ToolRules; restricted: boolean; onAction: (action: AgentToolAction, verdict: ToolRule) => void }) {
    const [search, setSearch] = useState('');
    const [group, setGroup] = useState<string | null>(null);
    const view = useMemo(() => actionView(rules, app, search), [rules, app, search]);
    const row = (a: AgentToolAction) => <ActionRow key={a.key} action={a} verdict={verdictOf(rules, app, a)} restricted={restricted} onChange={(v) => onAction(a, v)} />;
    return (
        <div className="pb-3 pl-11 animate-in fade-in-0 slide-in-from-top-1 duration-200 max-sm:pl-1 motion-reduce:animate-none" data-testid="app-actions">
            {view.kind !== 'all' && (
                <SearchField type="search" size="sm" value={search} onChange={setSearch} placeholder={`Search its ${app.actions.length} actions`} aria-label={`Search ${app.label}’s actions`} className="mb-1.5" />
            )}
            {view.kind === 'all' &&
                view.groups.map(([name, list]) => (
                    <section key={name ?? ''} aria-label={name ?? app.label}>
                        {name && view.groups.length > 1 && <p className={SECTION}>{name}</p>}
                        {list.map(row)}
                    </section>
                ))}
            {view.kind === 'found' && (
                <>
                    {view.actions.length ? view.actions.map(row) : <p className="py-1.5 text-[12.5px] text-muted-foreground">No action matches “{search.trim()}”.</p>}
                    {view.more > 0 && <p className="pt-1 text-[12px] text-muted-foreground">And {view.more} more: say more of what it does.</p>}
                </>
            )}
            {view.kind === 'groups' && (
                <>
                    {view.used.length > 0 && (
                        <section aria-label="Used this week">
                            <p className={SECTION}>Used this week</p>
                            {view.used.map(row)}
                        </section>
                    )}
                    {view.changed.length > 0 && (
                        <section aria-label="Set one by one">
                            <p className={SECTION}>Set one by one</p>
                            {view.changed.map(row)}
                        </section>
                    )}
                    <section aria-label="Every action">
                        <p className={SECTION}>Every action, by what it works on</p>
                        {view.groups.map(([name, list]) => (
                            <div key={name}>
                                <button
                                    type="button"
                                    aria-expanded={group === name}
                                    onClick={() => setGroup(group === name ? null : name)}
                                    className="flex min-h-8 w-full items-center gap-2 rounded-lg py-1 text-left text-[13px] transition-colors hover:text-foreground"
                                >
                                    <ChevronRight className={cn('h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none', group === name && 'rotate-90')} strokeWidth={2} />
                                    <span className="min-w-0 flex-1 truncate">{name}</span>
                                    <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">{list.length}</span>
                                </button>
                                {group === name && <div className="pl-5">{list.map(row)}</div>}
                            </div>
                        ))}
                    </section>
                </>
            )}
        </div>
    );
}

function ActionRow({ action, verdict, restricted, onChange }: { action: AgentToolAction; verdict: ToolRule; restricted: boolean; onChange: (verdict: ToolRule) => void }) {
    return (
        <div className="flex min-h-8 items-center gap-2.5 py-1" data-action={action.key} data-verdict={verdict}>
            <span className="min-w-0 flex-1 text-[13.5px] leading-snug">
                {action.title}
                <span className="ml-1.5 whitespace-nowrap text-[12px] text-muted-foreground">{KIND_WORDS[action.kind]}</span>
            </span>
            {restricted ? (
                <Verdicts value={verdict} title={action.title} canAsk={action.canAsk} onChange={onChange} />
            ) : (
                <span className={cn('shrink-0 text-[12px]', verdict === 'off' ? 'text-red-600 dark:text-red-400' : verdict === 'ask' ? 'font-medium text-foreground/85' : 'text-muted-foreground')}>{VERDICT_WORD[verdict]}</span>
            )}
        </div>
    );
}

function Verdicts({ value, title, canAsk, onChange }: { value: ToolRule; title: string; canAsk: boolean; onChange: (verdict: ToolRule) => void }) {
    return (
        <div role="radiogroup" aria-label={title} className="inline-flex shrink-0 rounded-full bg-foreground/[0.06] p-0.5">
            {VERDICTS.map(([v, label]) => {
                const blocked = v === 'ask' && !canAsk;
                return (
                    <button
                        key={v}
                        type="button"
                        role="radio"
                        aria-checked={value === v}
                        disabled={blocked}
                        title={blocked ? 'Reading never waits for a person' : undefined}
                        onClick={() => value !== v && onChange(v)}
                        className={cn(
                            'h-6 whitespace-nowrap rounded-full px-2.5 text-[12px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-40 max-sm:px-2',
                            value === v
                                ? cn('bg-popover font-medium shadow-sm ring-1 ring-inset ring-border dark:ring-foreground/[0.12]', v === 'off' ? 'text-red-600 dark:text-red-400' : 'text-foreground')
                                : 'text-muted-foreground hover:text-foreground'
                        )}
                    >
                        {label}
                    </button>
                );
            })}
        </div>
    );
}

/** What it holds besides apps (a browser, its other agents, its card, a database or bucket), in a line. */
function AlsoLine({ tools }: { tools: ToolEntry[] }) {
    const also = toolRows(tools, [])
        .filter((r) => (r.kind === 'noclick' && ['browser', 'agents', 'card'].includes(r.ref)) || r.kind === 'resource')
        .map((r) => ('title' in r ? r.title : ''));
    if (!also.length) return null;
    return (
        <p className={cn('mt-1 border-t pt-3 text-[12.5px] leading-snug text-muted-foreground', HAIRLINE)} data-testid="tools-also">
            Also: <span className="text-foreground/85">{also.join(' · ')}</span>
        </p>
    );
}
