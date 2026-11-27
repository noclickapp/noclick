// A template's page: its name, what it does, what it adds, costs and where it comes from
// in a line, the one button that adds it, then the space as it'll look (its channels and an example conversation in
// each, switched between; a template with no channels leads with its pictures), then what it adds (each agent's
// instructions a tap away), what it asks for and what it costs (an estimate of what's priced before it runs, and
// where each agent stops). The same page in Work and on the site; each hands it its button and its way back.
import { useState, type ReactNode } from 'react';
import { AppWindow, BookOpen, Brain, ChevronRight, Clock, Database, Hash, KeyRound, Workflow } from 'lucide-react';
import { MemberAvatar } from '@/screens/channels/avatars';
import { CredentialMark } from '@/ui/connectionMark';
import { DISPLAY } from '@/ui/titles';
import { cn } from '@/ui/utils';
import { contentsLine, dollars, jobLabel, priceLine, type Listing } from './model';
import { agentMember, LaptopFrame, PAGE_GROUND, PhoneFrame, TemplatePicture } from './Pictures';

const SECTION = 'border-t border-border/70 pt-6 dark:border-foreground/[0.08]';
const HEADING = cn(DISPLAY, 'm-0 mb-4 text-[28px] leading-tight text-foreground');
const ROW = 'flex items-start gap-3 py-2.5';
const ICON = 'mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-foreground/[0.06] text-foreground/75';

const and = (names: readonly string[]) => (names.length <= 1 ? (names[0] ?? '') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`);

/** Someone in an example conversation: one of its agents, by its face, else a person, by their initial. */
function Who({ t, name }: { t: Listing; name: string }) {
    const agent = t.agents.find((a) => a.name === name);
    return agent ? <MemberAvatar member={agentMember(t, agent)} size={32} /> : <MemberAvatar member={{ id: `person:${name}`, kind: 'human', name }} size={32} />;
}

/** The space as it'll look: its channels and agents, and the example conversation of the channel picked. */
export function SpacePreview({ t }: { t: Listing }) {
    const talked = t.conversations.map((c) => c.channel);
    const [open, setOpen] = useState(talked[0] ?? t.channels[0]?.name ?? null);
    const channel = t.channels.find((c) => c.name === open) ?? null;
    const messages = t.conversations.find((c) => c.channel === open)?.messages ?? [];
    return (
        <div data-testid="space-preview" className="overflow-hidden rounded-2xl bg-background ring-1 ring-inset ring-foreground/[0.08] md:grid md:grid-cols-[220px_1fr]">
            <nav className="hidden border-r border-foreground/[0.08] p-3 md:block" aria-label={`${t.name}'s channels`}>
                <p className="mb-3 truncate px-2 text-[15px] font-semibold text-foreground">{t.name}</p>
                <p className="px-2 pb-1 text-[12px] text-muted-foreground">Channels</p>
                {t.channels.map((c) => (
                    <button
                        key={c.name}
                        type="button"
                        onClick={() => setOpen(c.name)}
                        aria-current={c.name === open ? 'page' : undefined}
                        className={cn('flex h-8 w-full items-center gap-2 rounded-lg px-2 text-left text-[14px]', c.name === open ? 'bg-foreground/[0.08] font-medium text-foreground' : 'text-foreground/75 hover:bg-foreground/[0.04]')}
                    >
                        <Hash className="h-4 w-4 shrink-0 text-foreground/55" strokeWidth={1.75} />
                        <span className="truncate">{c.name}</span>
                    </button>
                ))}
                {t.agents.length > 0 && <p className="px-2 pb-1 pt-4 text-[12px] text-muted-foreground">Agents</p>}
                {t.agents.map((a) => (
                    <p key={a.name} className="flex h-8 items-center gap-2 px-2 text-[14px] text-foreground/75">
                        <MemberAvatar member={agentMember(t, a)} size={20} />
                        <span className="truncate">{a.name}</span>
                    </p>
                ))}
            </nav>
            <div className="flex min-h-[340px] min-w-0 flex-col">
                <div className="flex gap-2 overflow-x-auto border-b border-foreground/[0.08] px-3 py-2.5 [scrollbar-width:none] md:hidden" role="group" aria-label={`${t.name}'s channels`}>
                    {t.channels.map((c) => (
                        <button
                            key={c.name}
                            type="button"
                            onClick={() => setOpen(c.name)}
                            aria-pressed={c.name === open}
                            className={cn('inline-flex h-8 shrink-0 items-center rounded-full px-3 text-[13px]', c.name === open ? 'bg-foreground text-background' : 'bg-foreground/[0.06] text-foreground/80')}
                        >
                            # {c.name}
                        </button>
                    ))}
                </div>
                {channel && (
                    <header className="hidden h-12 shrink-0 items-center gap-2 border-b border-foreground/[0.08] px-5 md:flex">
                        <Hash className="h-4 w-4 text-foreground/55" strokeWidth={1.75} />
                        <span className="text-[15px] font-semibold">{channel.name}</span>
                        {channel.topic && <span className="ml-2 truncate text-[13px] text-muted-foreground">{channel.topic}</span>}
                    </header>
                )}
                <ol className="flex-1 space-y-4 px-4 py-5 md:px-5">
                    {messages.length ? (
                        messages.map((m, i) => (
                            <li key={i} className="flex gap-3">
                                <Who t={t} name={m.from} />
                                <div className="min-w-0">
                                    <p className="text-[14px] font-semibold text-foreground">{m.from}</p>
                                    <p className="mt-0.5 whitespace-pre-line text-[14px] leading-relaxed text-foreground/90">{m.text}</p>
                                </div>
                            </li>
                        ))
                    ) : (
                        <li className="text-[14px] text-muted-foreground">{channel?.topic ?? 'Nothing here yet.'}</li>
                    )}
                </ol>
            </div>
        </div>
    );
}

/** A template with no channels leads with its pictures: each of its own, in its frame, side by side. */
function PictureStrip({ t }: { t: Listing }) {
    if (!t.pictures.length) return <TemplatePicture t={t} className="min-h-[280px] py-8" large />;
    return (
        <div className={cn('flex items-end justify-center gap-6 overflow-hidden rounded-[18px] px-6 py-8', PAGE_GROUND)}>
            {t.pictures.map((p) =>
                p.frame === 'phone' ? (
                    <figure key={p.url} className="m-0 w-[22%] min-w-[110px] shrink-0">
                        <PhoneFrame>
                            <img src={p.url} alt={p.caption ?? t.name} className="block aspect-[9/19] w-full object-cover object-top" />
                        </PhoneFrame>
                        {p.caption && <figcaption className="mt-2 text-center text-[12px] text-muted-foreground">{p.caption}</figcaption>}
                    </figure>
                ) : (
                    <figure key={p.url} className="m-0 min-w-0 flex-1">
                        <LaptopFrame>
                            <img src={p.url} alt={p.caption ?? t.name} className="block aspect-[16/10] w-full object-cover object-top" />
                        </LaptopFrame>
                        {p.caption && <figcaption className="mt-2 text-center text-[12px] text-muted-foreground">{p.caption}</figcaption>}
                    </figure>
                )
            )}
        </div>
    );
}

function Row({ icon, title, line, children }: { icon: ReactNode; title: ReactNode; line?: ReactNode; children?: ReactNode }) {
    return (
        <li className={ROW}>
            {icon}
            <div className="min-w-0 flex-1">
                <p className="text-[15px] font-medium text-foreground">{title}</p>
                {line && <p className="mt-0.5 text-[13.5px] leading-snug text-muted-foreground">{line}</p>}
                {children}
            </div>
        </li>
    );
}

function Adds({ t }: { t: Listing }) {
    const icon = (Icon: typeof Hash) => (
        <span className={ICON}>
            <Icon className="h-4 w-4" strokeWidth={1.75} />
        </span>
    );
    return (
        <ul className="m-0 list-none p-0">
            {t.agents.map((a) => (
                <Row key={`agent:${a.name}`} icon={<MemberAvatar member={agentMember(t, a)} size={32} className="mt-0.5" />} title={a.name} line={[a.role, a.channels.length ? `works in ${and(a.channels.map((c) => `#${c}`))}` : null].filter(Boolean).join(' · ')}>
                    {a.instructions && (
                        <details className="group mt-1.5">
                            <summary className="flex cursor-pointer list-none items-center gap-1 text-[13px] text-foreground/75 hover:text-foreground [&::-webkit-details-marker]:hidden">
                                <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" strokeWidth={2} />
                                Its instructions
                            </summary>
                            <p className="mt-2 whitespace-pre-line rounded-xl bg-foreground/[0.04] p-3.5 text-[13.5px] leading-relaxed text-foreground/85">{a.instructions}</p>
                        </details>
                    )}
                </Row>
            ))}
            {t.channels.map((c) => (
                <Row key={`channel:${c.name}`} icon={icon(Hash)} title={`#${c.name}`} line={[c.topic, c.members.length ? and(c.members) : null].filter(Boolean).join(' · ')}>
                    {c.schedules.map((s) => (
                        <p key={s} className="mt-1 flex items-center gap-1.5 text-[13px] text-muted-foreground">
                            <Clock className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
                            On a schedule: “{s}”
                        </p>
                    ))}
                </Row>
            ))}
            {t.skills.map((s) => (
                <Row key={`skill:${s.name}`} icon={icon(BookOpen)} title={`The ${s.name} skill`} line={s.description} />
            ))}
            {t.memories.map((m) => (
                <Row key={`memory:${m.name}`} icon={icon(Brain)} title={`The ${m.name} memory`} line={m.description ?? `${m.entries.length} notes to start from`} />
            ))}
            {t.automations.map((a) => (
                <Row key={`automation:${a.name}`} icon={icon(Workflow)} title={a.name} line={a.description ?? 'An automation'} />
            ))}
            {t.stores.map((s) => (
                <Row key={`store:${s.name}`} icon={icon(Database)} title={s.name} line={s.kind === 'database' ? 'A database, made empty' : 'A bucket for files, made empty'} />
            ))}
            {t.app && <Row icon={icon(AppWindow)} title="Its app" line={`Its code copied into a repository of yours and deployed${t.app.framework ? ` (${t.app.framework})` : ''}`} />}
        </ul>
    );
}

function Asks({ t }: { t: Listing }) {
    if (!t.connections.length && !t.secrets.length) return <p className="text-[14px] text-muted-foreground">Nothing: it works as it is.</p>;
    return (
        <ul className="m-0 list-none p-0">
            {t.connections.map((c) => (
                <Row key={c.integration} icon={<span className="mt-1.5 grid h-6 w-8 shrink-0 place-items-center"><CredentialMark credentialType="" nodeType={c.nodeType} size="md" /></span>} title={c.label} line={c.usedBy.length ? `For ${and(c.usedBy)}. Connect it now or later; one you have is used.` : 'Connect it now or later; one you have is used.'} />
            ))}
            {t.secrets.map((s) => (
                <Row key={s.name} icon={<span className={ICON}><KeyRound className="h-4 w-4" strokeWidth={1.75} /></span>} title={s.name} line={[s.description, s.usedBy.length ? `for ${and(s.usedBy)}` : null].filter(Boolean).join(', ')} />
            ))}
        </ul>
    );
}

function Costs({ t }: { t: Listing }) {
    const lines = t.estimate.lines.filter((l) => l.usd > 0);
    const budgets = t.budget.agents.filter((a) => a.usdPerMonth !== null);
    return (
        <div className="space-y-4">
            <p className={cn(DISPLAY, 'm-0 text-[34px] leading-none text-foreground')}>{t.estimate.monthlyUsd > 0 ? `~${dollars(t.estimate.monthlyUsd)} a month` : t.agents.length ? 'By what its agents do' : 'Nothing a month'}</p>
            {lines.length > 0 && (
                <ul className="m-0 list-none space-y-1.5 p-0 text-[14px]">
                    {lines.map((l) => (
                        <li key={`${l.kind}:${l.name}`} className="flex justify-between gap-4">
                            <span className="text-foreground/85">{l.label ?? l.kind}</span>
                            <span className="tabular-nums text-muted-foreground">~{dollars(l.usd)}</span>
                        </li>
                    ))}
                </ul>
            )}
            {budgets.length > 0 && (
                <div className="space-y-1.5 border-t border-foreground/[0.08] pt-3 text-[14px]">
                    {budgets.map((a) => (
                        <p key={a.name} className="m-0 flex justify-between gap-4">
                            <span className="text-foreground/85">{a.name} stops at</span>
                            <span className="tabular-nums text-muted-foreground">{dollars(a.usdPerMonth ?? 0)} a month</span>
                        </p>
                    ))}
                    {t.budget.usdPerMonth !== null && (
                        <p className="m-0 flex justify-between gap-4 pt-1 font-medium">
                            <span>Its agents stop at</span>
                            <span className="tabular-nums">{dollars(t.budget.usdPerMonth)} a month</span>
                        </p>
                    )}
                </div>
            )}
            <p className="text-[13px] leading-relaxed text-muted-foreground">
                {t.agents.length ? 'What its agents spend is by what they do: each turn’s model and the tools it calls, priced as it runs, and you can change where they stop before you add it. ' : ''}
                Everything is charged at cost as it’s used.{t.connections.length ? ' Accounts you connect bill you themselves.' : ''}
            </p>
        </div>
    );
}

export function TemplatePageView({ t, action, crumb, from }: { t: Listing; action: ReactNode; crumb?: ReactNode; from?: string }) {
    const job = jobLabel(t.job);
    const leadsWithSpace = t.channels.length > 0;
    return (
        <article data-testid="template-page" data-template={t.slug} className="space-y-10">
            <header>
                {crumb ?? (job && <p className="text-[13px] text-muted-foreground">{job}</p>)}
                <h1 className={cn(DISPLAY, 'm-0 mt-3 text-[44px] leading-[1.02] text-foreground sm:text-[60px]')}>{t.name}</h1>
                {t.description && <p className="mt-4 max-w-[640px] text-[17px] leading-relaxed text-foreground/70">{t.description}</p>}
                <p className="mt-3 text-[13px] text-muted-foreground">
                    {[contentsLine(t), priceLine(t)].join(' · ')}
                    {from && <span className="ml-3 text-muted-foreground/80">From {from}</span>}
                </p>
                <div className="mt-6">{action}</div>
            </header>
            {leadsWithSpace ? <SpacePreview t={t} /> : <PictureStrip t={t} />}
            <section className={SECTION}>
                <h2 className={HEADING}>What it adds</h2>
                <Adds t={t} />
            </section>
            <section className={SECTION}>
                <h2 className={HEADING}>What it asks for</h2>
                <Asks t={t} />
            </section>
            <section className={SECTION}>
                <h2 className={HEADING}>What it costs</h2>
                <Costs t={t} />
            </section>
        </article>
    );
}
