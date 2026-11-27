// A space template's one page of asks, in Work's main pane (`template` in the URL: its address, or one of your repos
// by name): where it goes (one button aimed at the space you came from, a new space otherwise, Somewhere else to
// change it), what comes (a tick on each part when it goes into a space you have: untick every channel to bring just
// the agents), what it costs a month (its app and data stores, from the deploy's own estimate; its agents said as the
// cap they stop at, which is editable), each account it uses (connect now or later: one you have is used, never asked
// again) and each key it takes. Nothing is made until the last tap; then the add is followed over the account's
// frames (never a poll) to the space's #noclick, where its welcome post waits.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AppWindow, BookOpen, Brain, Check, ChevronDown, Database, Hash, LayoutTemplate, Loader2, Plus, Workflow } from 'lucide-react';
import { Project, Workspace, type TemplateAdd, type TemplateAdded, type TemplatePlan } from 'noclick';
import { useSlot } from '@/slots';
import { useWorkFrames } from '@/sdk/live';
import { CONNECT_APP } from '@/ui/slots';
import { CredentialMark } from '@/ui/connectionMark';
import { BUTTON_OUTLINE_SM, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { Checkbox } from '@/ui/checkbox';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { FIELD, FIELD_LABEL } from '@/ui/fields';
import { MENU_SURFACE } from '@/ui/menus';
import { DISPLAY } from '@/ui/titles';
import { cn } from '@/ui/utils';
import { MemberAvatar } from '@/screens/channels/avatars';
import { errorText } from '@/screens/console/pages/resources/shared';
import { useWorkClient } from '../client';
import { APPS } from '../slots';
import type { WorkSpace } from '../spaces';
import { and, containsLine, costLines, dollars, estimated, fromWhere, partKey, partLine, sortedParts } from './model';

export interface AddTemplatePageProps {
    /** The template's address, or one of your repos holding a space.json, by name. */
    source: string;
    /** The space it goes into (a workspace id of yours); null for a new space. */
    target: string | null;
    /** Your own spaces it can go into instead. */
    spaces: readonly WorkSpace[];
    onTarget: (workspaceId: string | null) => void;
    /** It arrived: open its space's #noclick. */
    onAdded: (added: TemplateAdded) => void;
}

type Phase = { kind: 'ready' } | { kind: 'adding'; op: TemplateAdd; line: string | null } | { kind: 'added'; added: TemplateAdded } | { kind: 'failed'; message: string };

const SECTION = 'border-t border-border/70 pt-5 dark:border-foreground/[0.08]';
const HEADING = 'mb-3 text-[13px] text-muted-foreground';
const ROW = 'flex items-center gap-3 py-2.5';

/** The add's latest stage line, from its progress. */
function lineOf(op: TemplateAdd): string | null {
    const lines = op.progress?.lines ?? [];
    return lines.length ? String(lines[lines.length - 1]) : null;
}

export function AddTemplatePage({ source, target, spaces, onTarget, onAdded }: AddTemplatePageProps) {
    const client = useWorkClient();
    const apps = useSlot(APPS).useToolApps();
    const { Connect, subscribe } = useSlot(CONNECT_APP);
    const [plan, setPlan] = useState<TemplatePlan | null>(null);
    const [problem, setProblem] = useState<string | null>(null);
    const [left, setLeft] = useState<Set<string>>(new Set());
    const [cap, setCap] = useState<string | null>(null);
    const [secrets, setSecrets] = useState<Record<string, Record<string, string>>>({});
    const [appSecrets, setAppSecrets] = useState<Record<string, string>>({});
    const [connecting, setConnecting] = useState<string | null>(null);
    const [phase, setPhase] = useState<Phase>({ kind: 'ready' });
    const [revealed, setRevealed] = useState<Record<string, string>>({});
    const [reads, setReads] = useState(0);
    const reread = () => setReads((n) => n + 1);
    useEffect(() => subscribe?.(reread), [subscribe]);

    const options = useMemo(() => {
        const capUsd = cap === null || cap.trim() === '' ? undefined : Number(cap);
        return {
            client,
            leaveOut: [...left].map((key) => {
                const [kind, ...name] = key.split(':');
                return { kind: kind as never, name: kind === 'app' ? undefined : name.join(':') };
            }),
            capUsdPerMonth: capUsd !== undefined && Number.isFinite(capUsd) ? capUsd : undefined,
        };
    }, [client, left, cap]);

    // The dry run, read again as what it depends on changes (a tick, the cap, where it goes, an account landing).
    useEffect(() => {
        let live = true;
        const timer = setTimeout(() => {
            const read = target
                ? Workspace.fromId(target, { client, user: null }).addTemplate(source, { ...options, dryRun: true })
                : Workspace.fromTemplate(source, { ...options, dryRun: true });
            read.then(
                (found) => {
                    if (!live) return;
                    setPlan(found);
                    setProblem(null);
                    if (cap === null && found.cap.usdPerMonth !== null) setCap(String(found.cap.usdPerMonth));
                },
                (e: unknown) => live && setProblem(errorText(e))
            );
        }, 250);
        return () => {
            live = false;
            clearTimeout(timer);
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps -- cap seeds once from the template's own
    }, [client, source, target, options, reads]);

    // The add moving on: each stage and its end arrive as an `operation` frame, which reads it again.
    const follow = useRef<TemplateAdd | null>(null);
    const readAdd = async () => {
        const op = follow.current;
        if (!op) return;
        await op.refresh();
        if (op.status === 'succeeded') {
            const added = await op.wait();
            follow.current = null;
            if ((added.app?.to_reveal as string[] | undefined)?.length) setPhase({ kind: 'added', added });
            else onAdded(added);
        } else if (op.done) {
            follow.current = null;
            setPhase({ kind: 'failed', message: errorText(op.error ?? new Error('It wasn’t added.')) });
        } else setPhase({ kind: 'adding', op, line: lineOf(op) });
    };
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'operation' && frame.id === follow.current?.id) void readAdd();
    });
    useWorkFrames('reset', () => void readAdd());

    const add = async () => {
        if (!plan) return;
        const given = Object.fromEntries(Object.entries(secrets).filter(([, values]) => Object.values(values).some((v) => v.trim())));
        try {
            const body = { ...options, secrets: Object.keys(given).length ? given : undefined, appSecrets: Object.keys(appSecrets).length ? appSecrets : undefined };
            const op = target ? await Workspace.fromId(target, { client, user: null }).addTemplate(source, body) : await Workspace.fromTemplate(source, body);
            follow.current = op;
            setPhase({ kind: 'adding', op, line: lineOf(op) });
            void readAdd();
        } catch (e) {
            setPhase({ kind: 'failed', message: errorText(e) });
        }
    };

    if (!plan) {
        return (
            <Frame>
                {problem ? (
                    <p role="alert" className="m-0 text-[14px] text-red-600 dark:text-red-400" data-testid="template-problem">
                        {problem}
                    </p>
                ) : (
                    <div aria-busy className="flex flex-col gap-3">
                        <span className="h-4 w-48 animate-pulse rounded bg-foreground/[0.06]" />
                        <span className="h-10 w-80 animate-pulse rounded bg-foreground/[0.06]" />
                        <span className="h-4 w-96 animate-pulse rounded bg-foreground/[0.06]" />
                    </div>
                )}
            </Frame>
        );
    }

    const labels = Object.fromEntries(plan.connections.map((c) => [c.integration, c.label]));
    const where = plan.target.new ? `Make ${plan.target.name}` : `Add to ${plan.target.name}`;
    const into = !plan.target.new;
    const parts = sortedParts(plan.parts);
    const agents = parts.filter((p) => p.kind === 'agent');
    const { lines, hostingUsd, agentsUpTo } = costLines(plan);
    const app = plan.app as Record<string, unknown> | null;
    const appSecretsAsk = ((app?.secrets as Record<string, unknown> | undefined)?.asked ?? []) as { name: string; description: string | null; required: boolean }[];
    const passwords = (((app?.secrets as Record<string, unknown> | undefined)?.generated ?? []) as { name: string; kind: string }[]).filter((s) => s.kind === 'password');
    const funds = plan.funds as { ok?: boolean; refusal?: { message?: string } };
    const missing = appSecretsAsk.filter((s) => s.required && !appSecrets[s.name]?.trim());
    const blocked = !!plan.refused || funds.ok === false || missing.length > 0;
    const others = spaces.filter((s) => s.own && s.workspaceId && !s.archived && !s.personal && s.workspaceId !== target);
    const opening = connecting ? apps.find((a) => a.value === connecting) : undefined;

    if (phase.kind === 'adding') {
        return (
            <Frame>
                <Head plan={plan} source={source} agents={agents.filter((a) => a.included).map((a) => a.named)} />
                <div className="flex items-center gap-2.5 text-[14px] text-foreground" role="status" data-testid="template-adding">
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                    {phase.line ?? `Adding ${plan.template.name}…`}
                </div>
                <p className="m-0 text-[13px] text-muted-foreground">All of it arrives, or none of it does. You can leave this page: it carries on.</p>
            </Frame>
        );
    }
    if (phase.kind === 'added') {
        const projectId = String(phase.added.app?.project_id ?? '');
        return (
            <Frame>
                <Head plan={plan} source={source} agents={agents.filter((a) => a.included).map((a) => a.named)} />
                <p className="m-0 text-[14px] text-foreground">{plan.template.name} is in. NoClick made a password for its app, shown to you this once:</p>
                {((phase.added.app?.to_reveal as string[]) ?? []).map((name) => (
                    <div key={name} className="flex items-center gap-3 rounded-2xl bg-foreground/[0.05] py-1.5 pl-3.5 pr-1.5">
                        <code className="min-w-0 flex-1 truncate font-mono text-[12.5px]">{revealed[name] ?? name}</code>
                        {!revealed[name] && (
                            <button type="button" className={BUTTON_SECONDARY} onClick={() => void Project.fromId(projectId, { client }).secrets.reveal(name).then((value) => setRevealed((r) => ({ ...r, [name]: value })))}>
                                Show it
                            </button>
                        )}
                    </div>
                ))}
                <button type="button" className={cn(BUTTON_PRIMARY, 'self-start')} onClick={() => onAdded(phase.added)}>
                    Open #noclick
                </button>
            </Frame>
        );
    }

    return (
        <Frame foot={
            <div className="flex flex-wrap items-center gap-3">
                <button type="button" className={BUTTON_PRIMARY} disabled={blocked} onClick={() => void add()} data-testid="template-add">
                    {where}
                </button>
                {phase.kind === 'failed' && (
                    <p role="alert" className="m-0 text-[13px] text-red-600 dark:text-red-400">
                        {phase.message}
                    </p>
                )}
            </div>
        }>
            <Head plan={plan} source={source} agents={agents.filter((a) => a.included).map((a) => a.named)} />
            <div className="flex flex-wrap items-center gap-2 text-[13.5px]">
                <span className="text-muted-foreground">Goes to</span>
                <DropdownMenu>
                    <DropdownMenuTrigger className={cn(BUTTON_OUTLINE_SM, 'gap-1')} data-testid="template-where">
                        {plan.target.new ? `A new space, ${plan.target.name}` : plan.target.name}
                        <ChevronDown className="h-3.5 w-3.5" />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className={cn(MENU_SURFACE, 'min-w-[220px]')}>
                        {target && (
                            <DropdownMenuItem onSelect={() => onTarget(target)}>
                                <span className="flex-1">{plan.target.name}</span>
                                <Check className="h-4 w-4" />
                            </DropdownMenuItem>
                        )}
                        {others.map((s) => (
                            <DropdownMenuItem key={s.id} onSelect={() => onTarget(s.workspaceId)}>
                                {s.name}
                            </DropdownMenuItem>
                        ))}
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onSelect={() => onTarget(null)}>
                            <Plus className="h-4 w-4" />
                            <span className="flex-1">A new space</span>
                            {!target && <Check className="h-4 w-4" />}
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>

            <section aria-label="What comes" className={SECTION}>
                <p className={HEADING}>{into ? `What comes to ${plan.target.name}` : 'What it makes'}</p>
                <ul className="m-0 list-none p-0" data-testid="template-parts">
                    {parts.map((part) => {
                        const key = partKey(part);
                        const line = partLine(part, labels);
                        return (
                            <li key={key} className={cn(ROW, 'border-b border-border/50 last:border-0 dark:border-foreground/[0.06]', !part.included && 'opacity-50')}>
                                {into && <Checkbox checked={part.included} aria-label={`Bring ${part.named}`} onCheckedChange={(on) => setLeft((was) => toggled(was, key, on !== true))} />}
                                <PartMark kind={part.kind} name={part.named} role={part.line} />
                                <div className="min-w-0 flex-1">
                                    <p className="m-0 truncate text-[14px] text-foreground">{part.kind === 'channel' ? `#${part.named}` : part.named}</p>
                                    {line && <p className="m-0 truncate text-[12.5px] text-muted-foreground">{line}</p>}
                                </div>
                            </li>
                        );
                    })}
                </ul>
                {into && <p className="m-0 mt-2 text-[12.5px] text-muted-foreground">Untick every channel to bring just the agents: they join {plan.target.name} and show under Agents.</p>}
                {plan.short.map((s) => (
                    <p key={s} className="m-0 mt-1 text-[12.5px] text-muted-foreground">
                        {s}
                    </p>
                ))}
            </section>

            <section aria-label="What it costs" className={SECTION} data-testid="template-cost">
                <p className={HEADING}>What it costs</p>
                <p className="m-0 flex items-baseline gap-2">
                    <span className={cn(DISPLAY, 'text-[40px] leading-none text-foreground')}>{estimated(hostingUsd)}</span>
                    <span className="text-[14px] text-muted-foreground">a month, by what it uses{agentsUpTo !== null ? `, and its agents up to ${dollars(agentsUpTo)}` : ''}</span>
                </p>
                <ul className="m-0 mt-3 list-none p-0">
                    {lines.map((line) => (
                        <li key={line.key} className="flex items-baseline justify-between gap-4 border-b border-border/50 py-2 last:border-0 dark:border-foreground/[0.06]">
                            <span className="min-w-0">
                                <span className="block text-[14px] text-foreground">{line.name}</span>
                                <span className="block text-[12.5px] text-muted-foreground">{line.by}</span>
                            </span>
                            <span className="shrink-0 text-[14px] tabular-nums text-foreground">{line.upTo ? `up to ${dollars(line.usd)}` : estimated(line.usd)}</span>
                        </li>
                    ))}
                </ul>
                {agents.some((a) => a.included) && (
                    <label className="mt-4 flex flex-wrap items-center gap-2 text-[13.5px]">
                        <span className="w-full text-muted-foreground">Its agents stop at</span>
                        <span className="relative">
                            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground">$</span>
                            <input inputMode="decimal" value={cap ?? ''} onChange={(e) => setCap(e.target.value.replace(/[^0-9.]/g, ''))} aria-label="Its agents' cap a month" className={cn(FIELD, 'w-28 rounded-full pl-6')} data-testid="template-cap" />
                        </span>
                        <span className="text-muted-foreground">a month{into ? ` in ${plan.target.name}` : ''}, shared out as their budgets</span>
                    </label>
                )}
            </section>

            {plan.connections.length > 0 && (
                <section aria-label="Accounts it uses" className={SECTION} data-testid="template-accounts">
                    <p className={HEADING}>Accounts it uses</p>
                    {plan.connections.map((account) => (
                        <div key={account.integration} className={cn(ROW, 'border-b border-border/50 last:border-0 dark:border-foreground/[0.06]')}>
                            <CredentialMark credentialType="" nodeType={account.nodeType} size="md" />
                            <div className="min-w-0 flex-1">
                                <p className="m-0 text-[14px] text-foreground">{account.label}</p>
                                <p className="m-0 truncate text-[12.5px] text-muted-foreground">{account.connected?.name ?? and(account.usedBy)}</p>
                            </div>
                            {account.connected ? (
                                <span className="flex items-center gap-1 text-[13px] text-muted-foreground">
                                    <Check className="h-3.5 w-3.5" /> Connected
                                </span>
                            ) : (
                                <button type="button" className={BUTTON_OUTLINE_SM} disabled={!account.nodeType || !apps.some((a) => a.value === account.nodeType)} onClick={() => setConnecting(account.nodeType)}>
                                    Connect
                                </button>
                            )}
                        </div>
                    ))}
                    {plan.connections.some((c) => !c.connected) && <Note>Connect now or later: what’s left waits in the space’s #noclick.</Note>}
                </section>
            )}

            {(plan.secrets.some((s) => !s.held) || appSecretsAsk.length > 0) && (
                <section aria-label="Keys it takes" className={SECTION}>
                    {plan.secrets
                        .filter((s) => !s.held)
                        .map((secret) => (
                            <div key={secret.name} className="mb-3">
                                <p className={HEADING}>A key it takes, if you want</p>
                                {(secret.keys.length ? secret.keys : [secret.name]).map((key) => (
                                    <label key={key} className="block">
                                        <span className={FIELD_LABEL}>
                                            {key}
                                            {secret.description ? <span className="font-normal text-muted-foreground"> · {secret.description}</span> : null}
                                        </span>
                                        <input type="password" autoComplete="off" placeholder="Paste it here" className={FIELD} value={secrets[secret.name]?.[key] ?? ''} onChange={(e) => setSecrets((was) => ({ ...was, [secret.name]: { ...was[secret.name], [key]: e.target.value } }))} />
                                    </label>
                                ))}
                            </div>
                        ))}
                    {appSecretsAsk.map((secret) => (
                        <label key={secret.name} className="mb-3 block">
                            <span className={FIELD_LABEL}>
                                {secret.name}
                                {secret.description ? <span className="font-normal text-muted-foreground"> · {secret.description}</span> : null}
                            </span>
                            <input type="password" autoComplete="off" placeholder={secret.required ? 'Its app needs it' : 'Paste it here'} className={FIELD} value={appSecrets[secret.name] ?? ''} onChange={(e) => setAppSecrets((was) => ({ ...was, [secret.name]: e.target.value }))} />
                        </label>
                    ))}
                </section>
            )}
            {passwords.map((p) => (
                <Note key={p.name}>NoClick makes a password for {String(app?.name ?? 'its app')} ({p.name}) and shows it to you once, when it’s live.</Note>
            ))}
            {plan.refused && <Note alert>{plan.refused.message}</Note>}
            {funds.ok === false && <Note alert>{funds.refusal?.message ?? 'Your account can’t pay to run it now.'}</Note>}
            {problem && <Note alert>{problem}</Note>}
            {opening && (
                <Connect
                    app={opening}
                    name={opening.label}
                    client={client}
                    onConnected={() => {
                        setConnecting(null);
                        reread();
                    }}
                    onClose={() => setConnecting(null)}
                />
            )}
        </Frame>
    );
}

function toggled(set: Set<string>, key: string, out: boolean): Set<string> {
    const next = new Set(set);
    if (out) next.add(key);
    else next.delete(key);
    return next;
}

function Frame({ children, foot }: { children: ReactNode; foot?: ReactNode }) {
    return (
        <div className="flex h-full min-h-0 w-full flex-col" data-testid="add-template">
            <div className="min-h-0 flex-1 overflow-y-auto">
                <div className="mx-auto flex w-full max-w-[640px] flex-col gap-5 px-4 py-8 md:px-6">{children}</div>
            </div>
            {foot && <div className="mx-auto w-full max-w-[640px] px-4 pb-6 pt-3 md:px-6">{foot}</div>}
        </div>
    );
}

function Head({ plan, source, agents }: { plan: TemplatePlan; source: string; agents: string[] }) {
    return (
        <header className="flex flex-col gap-2">
            <p className="m-0 flex items-center gap-1.5 text-[13px] text-muted-foreground">
                <LayoutTemplate className="h-3.5 w-3.5" strokeWidth={1.75} />A template from <span className="text-foreground">{fromWhere(source)}</span>
            </p>
            <h1 className={cn(DISPLAY, 'm-0 text-[38px] leading-[1.1] text-foreground max-md:text-[32px]')}>{plan.template.name}</h1>
            {plan.template.description && <p className="m-0 text-[15px] text-muted-foreground">{plan.template.description}</p>}
            <p className="m-0 flex items-center gap-2 text-[13px] text-muted-foreground">
                {agents.length > 0 && (
                    <span className="flex -space-x-1">
                        {agents.slice(0, 4).map((name) => (
                            <MemberAvatar key={name} member={{ id: `template:${name}`, kind: 'agent', name }} size={20} className="ring-2 ring-background" />
                        ))}
                    </span>
                )}
                {containsLine(plan.parts.filter((p) => p.included))}
            </p>
        </header>
    );
}

function PartMark({ kind, name, role }: { kind: string; name: string; role: string | null }) {
    if (kind === 'agent') return <MemberAvatar member={{ id: `template:${name}`, kind: 'agent', name, role: role ?? undefined }} size={32} />;
    const Icon = { channel: Hash, skill: BookOpen, memory: Brain, automation: Workflow, store: Database, app: AppWindow }[kind] ?? Hash;
    return (
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-muted-foreground">
            <Icon className="h-4 w-4" strokeWidth={1.75} />
        </span>
    );
}

function Note({ children, alert }: { children: ReactNode; alert?: boolean }) {
    return (
        <p role={alert ? 'alert' : undefined} className={cn('m-0 flex gap-2 text-[12.5px]', alert ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')}>
            <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-current opacity-60" />
            {children}
        </p>
    );
}
