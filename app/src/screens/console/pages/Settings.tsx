// Settings, one page: approval rules and your brand (each summarised, with its
// editor one click away at settings/policy and settings/brand), the default
// region, what a paused user is told, webhooks (managed at
// settings/webhooks), setting up the clients and MCP, the docs, and your plan. The old README addresses
// (/settings/docs/{python|typescript}) forward to the docs site.
import { useEffect, useState, type ReactNode } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { Link, Navigate } from 'react-router';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { planLabel } from '@/ui/accountParts';
import { Input } from '@/ui/input';
import { Textarea } from '@/ui/textarea';
import { cn } from '@/ui/utils';
import { ALL_USERS, Brand, DEFAULT_BASE_URL, Policy, Webhook, type Rule } from 'noclick';
import { API_URL_ENV } from '@/sdk/source';
import { formatCount } from '@/screens/console/lib/format';
import { INSTALL_TABS, MCP_URL, envExport } from '@/screens/console/lib/snippets';
import { docsLinks, pricingUrl } from '@/screens/console/lib/site';
import { useOwnerOnly } from '../ownerOnly';
import { useAccount, useAccountPlan, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { updateAccount } from '@/sdk/owner';
import { resolvePage, settingsPages, type ConsolePageProps } from '../sections';
import { CodeSnippet } from '../ui/CodeSnippet';
import { ErrorPanel } from '../ui/ErrorPanel';
import { RegionField } from '../ui/RegionField';
import { PageFrame } from '../ui/PageFrame';
import { PageHeader } from '../ui/PageHeader';
import { ConsoleButton, consoleButtonClass } from '../ui/Button';
import { FormField, INPUT, formError } from './Users';

export const ENV_LINES = `${envExport('nk_live_…')}\n# Optional; defaults to ${DEFAULT_BASE_URL}\nexport ${API_URL_ENV}=${DEFAULT_BASE_URL}`;

/** The editors Settings opens as their own pages; the designed ones open only in the lab. */
function editorFor(id: string | undefined, lab: boolean): string | undefined {
    return id ? settingsPages(lab).find((p) => p.id === id && p.page !== 'Settings')?.page : undefined;
}

/** One setting: what it is on the left, its value and action on the right; stacked on phones. */
function Row({ id, title, sub, children }: { id?: string; title: string; sub: ReactNode; children: ReactNode }) {
    return (
        <section id={id} aria-label={title} className={cn('grid grid-cols-1 gap-4 border-t py-7 first:border-t-0 first:pt-0 md:grid-cols-[minmax(0,260px)_minmax(0,1fr)] md:gap-10', HAIRLINE)}>
            <div>
                <h2 className="m-0 text-[16px] font-semibold tracking-tight text-foreground">{title}</h2>
                <p className="m-0 mt-1 text-[13px] leading-relaxed text-muted-foreground">{sub}</p>
            </div>
            <div className="flex min-w-0 flex-col gap-3 text-[13px] text-foreground/85">{children}</div>
        </section>
    );
}

const plural = (n: number, one: string, many = `${one}s`) => `${formatCount(n)} ${n === 1 ? one : many}`;

/** A pattern, or a rule set from code (designed) with its condition. */
const ruleChip = (p: string | Rule) => (typeof p === 'string' ? p : `${p.tool}${p.when ? ` when ${p.when}` : ''}`);

function RuleSummary() {
    const { client } = useConsole();
    const href = useConsoleHref();
    const layers = useV1('policy/layers', () => Policy.list({ client }));
    if (layers.error !== undefined && !layers.data) return <ErrorPanel error={layers.error} onRetry={() => void layers.refresh()} />;
    if (!layers.data) return <div aria-busy className="h-10 animate-pulse rounded-lg bg-foreground/[0.03]" />;
    const account = layers.data.find((p) => !p.userId);
    const users = layers.data.filter((p) => p.userId && p.allow.length + p.deny.length + p.requireApproval.length > 0);
    const lines: [string, (string | Rule)[]][] = [
        ['Need approval', account?.requireApproval ?? []],
        ['Never run', account?.deny ?? []],
        ['Only these run', account?.allow ?? []],
    ];
    const set = lines.filter(([, patterns]) => patterns.length);
    return (
        <>
            {set.length ? (
                <dl className="m-0 flex flex-col gap-2">
                    {set.map(([label, patterns]) => (
                        <div key={label} className="flex flex-col gap-1 sm:flex-row sm:gap-3">
                            <dt className="w-32 shrink-0 text-muted-foreground">{label}</dt>
                            <dd className="m-0 flex min-w-0 flex-wrap gap-1">
                                {patterns.map(ruleChip).map((p) => (
                                    <span key={p} className="rounded bg-foreground/[0.05] px-1.5 py-[1px] font-mono text-[12px] text-foreground/85">
                                        {p}
                                    </span>
                                ))}
                            </dd>
                        </div>
                    ))}
                </dl>
            ) : (
                <p className="m-0">Every tool runs without asking. Add a rule to hold a call for a person, or to refuse it.</p>
            )}
            {users.length > 0 && <p className="m-0 text-muted-foreground">{plural(users.length, 'user')} {users.length === 1 ? 'has rules of their own' : 'have rules of their own'} on top.</p>}
            <div>
                <Link to={href('settings/policy')} className={consoleButtonClass('soft', 'sm')}>
                    Edit rules
                </Link>
            </div>
        </>
    );
}

function BrandSummary() {
    const { client } = useConsole();
    const href = useConsoleHref();
    const brand = useV1('brand', () => Brand.get({ client }));
    if (brand.error !== undefined && !brand.data) return <ErrorPanel error={brand.error} onRetry={() => void brand.refresh()} />;
    if (!brand.data) return <div aria-busy className="h-10 animate-pulse rounded-lg bg-foreground/[0.03]" />;
    const b = brand.data;
    return (
        <>
            {b.isDefault ? (
                <p className="m-0">Pages and emails go out as NoClick.</p>
            ) : (
                <div className="flex items-center gap-3">
                    {b.logoUrl ? (
                        <img src={b.logoUrl} alt="" className={cn('h-9 w-9 shrink-0 rounded-md border object-contain', HAIRLINE)} />
                    ) : (
                        <span aria-hidden className="h-9 w-9 shrink-0 rounded-md border" style={{ background: b.color ?? undefined }} />
                    )}
                    <div className="min-w-0">
                        <p className="m-0 truncate font-medium text-foreground">{b.name ?? 'Unnamed'}</p>
                        <p className="m-0 truncate text-muted-foreground">
                            {[b.emailFromName && `Emails from ${b.emailFromName}`, b.color].filter(Boolean).join(' · ') || 'No sender name or colour'}
                        </p>
                    </div>
                </div>
            )}
            <div>
                <Link to={href('settings/brand')} className={consoleButtonClass('soft', 'sm')}>
                    {b.isDefault ? 'Use your own brand' : 'Edit brand'}
                </Link>
            </div>
        </>
    );
}

/** The account's webhook endpoints at a glance, its users' included. */
function WebhooksSummary() {
    const { client } = useConsole();
    const href = useConsoleHref();
    const hooks = useV1('webhooks?summary', () => Webhook.list({ client, userFilter: ALL_USERS, limit: 100 }));
    if (hooks.error !== undefined && !hooks.data) return <ErrorPanel error={hooks.error} onRetry={() => void hooks.refresh()} />;
    if (!hooks.data) return <div aria-busy className="h-10 animate-pulse rounded-lg bg-foreground/[0.03]" />;
    const failing = hooks.data.filter((w) => w.status === 'failing');
    return (
        <>
            {hooks.data.length ? (
                <p className="m-0">
                    {plural(hooks.data.length, 'endpoint')}
                    {failing.length > 0 ? (
                        <span className="text-red-600 dark:text-red-400">
                            {' '}
                            · {failing.length} failing: <span className="font-mono text-[12px]">{failing.map((w) => w.url).join(', ')}</span>
                        </span>
                    ) : (
                        <span className="text-muted-foreground"> · all healthy</span>
                    )}
                </p>
            ) : (
                <p className="m-0">No endpoints. Events stay in the log for 30 days either way.</p>
            )}
            <div>
                <Link to={href('settings/webhooks')} className={consoleButtonClass('soft', 'sm')}>
                    {hooks.data.length ? 'Manage webhooks' : 'Add an endpoint'}
                </Link>
            </div>
        </>
    );
}

/** The account's default region: what a sandbox or agent created without one runs in. */
function DefaultRegion() {
    const { client } = useConsole();
    const account = useAccount().data;
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    if (!account) return <div aria-busy className="h-10 animate-pulse rounded-lg bg-foreground/[0.03]" />;
    const save = async (value: string) => {
        setSaving(true);
        setError(undefined);
        try {
            await updateAccount(client, { default_region: value || null });
            invalidateV1('account');
            invalidateV1('regions');
            toast.success(value ? `New resources run in ${value}` : 'New resources run wherever NoClick has capacity');
        } catch (e) {
            setError(e);
        } finally {
            setSaving(false);
        }
    };
    return (
        <>
            <RegionField
                id="default-region"
                label="Default region"
                value={account.default_region ?? ''}
                onChange={(value) => void save(value)}
                emptyLabel="None: wherever NoClick has capacity"
                hint={saving ? 'Saving…' : 'Sandboxes and agents created without a region from now on. Existing ones stay where they are. Key-value stores and queues are kept in us-east only, so with another default they pass region="us-east".'}
                className="sm:w-96"
            />
            {error !== undefined && <ErrorPanel error={error} />}
        </>
    );
}

/** What a user is told when your code pauses their spending without a message. */
function PausedSpendingDefault() {
    const { client } = useConsole();
    const saved = useAccount().data?.spending_paused ?? null;
    const [message, setMessage] = useState<string | null>(null);
    const [label, setLabel] = useState<string | null>(null);
    const [url, setUrl] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const draft = {
        message: message ?? saved?.message ?? '',
        label: label ?? saved?.action?.label ?? '',
        url: url ?? saved?.action?.url ?? '',
    };
    const save = async () => {
        if (!draft.label.trim() !== !draft.url.trim()) return setError('A button needs both a label and a link.');
        setBusy(true);
        setError(null);
        try {
            const value = draft.message.trim()
                ? { message: draft.message.trim(), action: draft.label.trim() ? { label: draft.label.trim(), url: draft.url.trim() } : null }
                : null;
            await updateAccount(client, { spending_paused: value });
            invalidateV1('account');
            toast.success(value ? 'Default saved' : 'Default removed');
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <form
            className="flex flex-col gap-3 sm:max-w-[34rem]"
            onSubmit={(e) => {
                e.preventDefault();
                void save();
            }}
        >
            <FormField label="Message" htmlFor="paused-default-message" error={error} hint="Blank removes the default, so each pause must say what to do.">
                <Textarea id="paused-default-message" rows={2} maxLength={500} className="text-[13px] md:text-[13px]" value={draft.message} onChange={(e) => setMessage(e.target.value)} />
            </FormField>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
                <FormField label="Button" htmlFor="paused-default-label">
                    <Input id="paused-default-label" maxLength={40} className={INPUT} value={draft.label} onChange={(e) => setLabel(e.target.value)} />
                </FormField>
                <FormField label="Link" htmlFor="paused-default-url" hint="{{user.id}} fills in each user's id.">
                    <Input id="paused-default-url" inputMode="url" className={cn(INPUT, 'font-mono')} value={draft.url} onChange={(e) => setUrl(e.target.value)} />
                </FormField>
            </div>
            <div>
                <ConsoleButton size="sm" variant="soft" type="submit" disabled={busy}>
                    Save
                </ConsoleButton>
            </div>
        </form>
    );
}

function Overview({ install }: { install: boolean }) {
    const href = useConsoleHref();
    const { site } = useConsole();
    const ownerCan = useOwnerOnly();
    const account = useAccount().data;
    const plan = useAccountPlan();
    const tools = account?.meta.mcp_tools ?? [];
    useEffect(() => {
        if (install) document.getElementById('install')?.scrollIntoView({ block: 'start' });
    }, [install]);
    return (
        <>
            <PageHeader section="settings" />
            <div>
                <Row title="Approval rules" sub="Which tools need a person to approve each call, and which never run. They apply to your code, your LLM's toolkit and your hosted agents alike.">
                    <RuleSummary />
                </Row>
                <Row title="Brand" sub="What your users see on the pages and emails that ask them to connect an account or answer a request.">
                    <BrandSummary />
                </Row>
                {ownerCan('accountDefaults') && (
                    <>
                        <Row id="region" title="Region" sub="Where sandboxes and agents run when your code doesn't say. A resource keeps its region for life, and the price is the same in every one.">
                            <DefaultRegion />
                        </Row>
                        <Row id="paused-spending" title="Paused spending" sub="What a user is told when your billing pauses their spending and your code doesn't say. Your words, and your page to pay on.">
                            <PausedSpendingDefault />
                        </Row>
                    </>
                )}
                <Row id="webhooks" title="Webhooks" sub="Endpoints on your server that hear about finished runs, answers and failures the moment they happen.">
                    <WebhooksSummary />
                </Row>
                <Row id="install" title="Clients and MCP" sub="Install a client and give it a key. Coding agents and other tools can use the platform over MCP.">
                    <CodeSnippet tabs={INSTALL_TABS} />
                    <CodeSnippet code={ENV_LINES} language="bash" />
                    <CodeSnippet code={`POST ${MCP_URL}`} />
                    <p className="m-0 text-muted-foreground">
                        Clients sign in with OAuth or take a platform key as their bearer.
                        {ownerCan('keys') && (
                            <>
                                {' '}
                                <Link to={href('keys')} className="text-foreground underline underline-offset-2">
                                    Create a key
                                </Link>{' '}
                                to get a ready-made config for Claude Code or Cursor.
                            </>
                        )}
                    </p>
                    {tools.length > 0 && (
                        <details className="text-muted-foreground">
                            <summary className="cursor-pointer select-none">{plural(tools.length, 'MCP tool')}</summary>
                            <ul aria-label="MCP tools" className="m-0 mt-2 flex list-none flex-wrap gap-1 p-0">
                                {tools.map((t) => (
                                    <li key={t} className="rounded bg-foreground/[0.05] px-1.5 py-[1px] font-mono text-[12px] text-foreground/80">
                                        {t}
                                    </li>
                                ))}
                            </ul>
                        </details>
                    )}
                </Row>
                <Row title="Docs" sub="The guide walks through each part of the platform; the references list every class, method and error.">
                    <ul className="m-0 flex list-none flex-col gap-2 p-0">
                        {docsLinks(site).map((doc) => (
                            <li key={doc.id}>
                                <a href={doc.href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-foreground hover:underline">
                                    {doc.title} <ArrowUpRight className="h-3.5 w-3.5 text-muted-foreground" />
                                </a>
                            </li>
                        ))}
                    </ul>
                </Row>
                <Row title="Plan" sub="Every plan includes the platform API. Usage is charged to your account's balance, in dollars: what your plan includes each month, plus funds you add.">
                    {account && plan !== undefined ? (
                        <>
                            <p className="m-0">
                                {plan && (
                                    <>
                                        <span className="font-medium text-foreground">{planLabel(plan)}</span>.{' '}
                                    </>
                                )}
                                {account.email && <span className="text-muted-foreground">Signed in as {account.email}.</span>}
                            </p>
                            <div>
                                <a href={pricingUrl(site)} target="_blank" rel="noopener noreferrer" className={consoleButtonClass('soft', 'sm')}>
                                    View plans <ArrowUpRight className="h-3.5 w-3.5" />
                                </a>
                            </div>
                        </>
                    ) : (
                        <div aria-busy className="h-10 animate-pulse rounded-lg bg-foreground/[0.03]" />
                    )}
                </Row>
            </div>
        </>
    );
}

export default function Settings({ rest }: ConsolePageProps) {
    const { lab, site } = useConsole();
    if (rest[0] === 'docs') {
        const doc = docsLinks(site).find((d) => d.id === (rest[1] ?? 'guide'));
        if (doc) return <Navigate to={doc.href} replace />;
        return <PageHeader title="Not found" purpose="There's no doc at this address." />;
    }
    const editor = editorFor(rest[0], lab);
    if (editor) {
        const Page = resolvePage(editor)!;
        return (
            <PageFrame resetKey={editor}>
                <Page rest={rest.slice(1)} />
            </PageFrame>
        );
    }
    if (rest[0] && rest[0] !== 'install') return <PageHeader title="Not found" purpose={`There's no setting called "${rest[0]}".`} />;
    return <Overview install={rest[0] === 'install'} />;
}
