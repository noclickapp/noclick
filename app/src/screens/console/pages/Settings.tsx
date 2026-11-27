// Settings, one page in the app's settings rows: your brand (its editor one click away at settings/brand), the
// account's defaults (where new resources run, what a paused user is told), setting up the clients and MCP, the docs,
// and your plan. Webhooks and Approval rules are sections of their own, under Access. The old README addresses
// (/settings/docs/{python|typescript}) forward to the docs site.
import { useEffect, useState, type FormEvent } from 'react';
import { ArrowUpRight } from 'lucide-react';
import { Link, Navigate } from 'react-router';
import { toast } from 'sonner';
import { FieldSelect } from '@/ui/FieldSelect';
import { FIELD, FIELD_LABEL } from '@/ui/fields';
import { HAIRLINE } from '@/ui/primitives';
import { planLabel } from '@/ui/accountParts';
import { cn } from '@/ui/utils';
import { Brand } from 'noclick';
import { SettingsGroup, SettingsGroupTitle, SettingsRow } from '@/screens/settings/parts';
import { formatCount } from '@/screens/console/lib/format';
import { MCP_URL } from '@/screens/console/lib/snippets';
import { docsLinks, pricingUrl } from '@/screens/console/lib/site';
import { API_KEY_ENV } from '@/sdk/source';
import { ANYWHERE, regionLabel, useRegions } from '@/screens/console/hooks/useRegions';
import { useOwnerOnly } from '../ownerOnly';
import { useAccount, useAccountPlan, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { updateAccount } from '@/sdk/owner';
import { resolvePage, settingsPages, type ConsolePageProps } from '../sections';
import { ConsoleDialog } from '../ui/ConsoleDialog';
import { CopyButton } from '../ui/CopyButton';
import { ErrorPanel } from '../ui/ErrorPanel';
import { PageFrame } from '../ui/PageFrame';
import { PageHeader } from '../ui/PageHeader';
import { ConsoleButton, consoleButtonClass } from '../ui/Button';
import { formError } from './Users';

/** The editors Settings opens as their own pages; the designed ones open only in the lab. */
function editorFor(id: string | undefined, lab: boolean): string | undefined {
    return id ? settingsPages(lab).find((p) => p.id === id && p.page !== 'Settings')?.page : undefined;
}

const ROW_ACTION = consoleButtonClass('soft', 'sm');
const WAITING = <span aria-busy className="inline-block h-4 w-40 animate-pulse rounded bg-foreground/[0.06] align-middle" />;

function BrandRow() {
    const { client } = useConsole();
    const href = useConsoleHref();
    const brand = useV1('brand', () => Brand.get({ client }));
    const b = brand.data;
    const description = brand.error !== undefined && !b ? (
        <ErrorPanel error={brand.error} onRetry={() => void brand.refresh()} className="mt-2" />
    ) : !b ? (
        WAITING
    ) : b.isDefault ? (
        'Pages and emails go out as NoClick.'
    ) : (
        <span className="flex min-w-0 items-center gap-2">
            {b.logoUrl ? (
                <img src={b.logoUrl} alt="" className={cn('h-5 w-5 shrink-0 rounded border object-contain', HAIRLINE)} />
            ) : (
                <span aria-hidden className="h-4 w-4 shrink-0 rounded" style={{ background: b.color ?? undefined }} />
            )}
            <span className="truncate">{[b.name ?? 'Unnamed', b.emailFromName && `emails from ${b.emailFromName}`].filter(Boolean).join(', ')}</span>
        </span>
    );
    return (
        <SettingsRow
            label="Brand"
            description={description}
            control={
                b && (
                    <Link to={href('settings/brand')} className={ROW_ACTION}>
                        {b.isDefault ? 'Use your own' : 'Edit'}
                    </Link>
                )
            }
        />
    );
}

/** The account's default region: what a sandbox or agent created without one runs in. */
function RegionRow() {
    const { client } = useConsole();
    const account = useAccount().data;
    const regions = useRegions();
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    const save = async (value: string) => {
        setSaving(true);
        setError(undefined);
        try {
            await updateAccount(client, { default_region: value || null });
            invalidateV1('account');
            invalidateV1('regions');
            toast.success(value ? `New resources run in ${regionLabel(value, regions.data)}` : 'New resources run wherever NoClick has capacity');
        } catch (e) {
            setError(e);
        } finally {
            setSaving(false);
        }
    };
    return (
        <SettingsRow
            label="Region"
            description={
                <>
                    Where sandboxes and agents run when your code doesn&apos;t say. A resource keeps its region for life, and the price is the same in every one. Key-value stores and
                    queues are kept in us-east only.
                    {error !== undefined && <ErrorPanel error={error} className="mt-2" />}
                </>
            }
            control={
                <FieldSelect
                    aria-label="Default region"
                    className="w-64"
                    value={account?.default_region ?? ''}
                    disabled={!account || !regions.data || saving}
                    onValueChange={(value) => void save(value)}
                    options={[{ value: '', label: ANYWHERE }, ...(regions.data ?? []).map((r) => ({ value: r.name, label: regionLabel(r.name, regions.data) }))]}
                />
            }
        />
    );
}

/** What a user is told when your code pauses their spending without a message: shown here, changed in a dialog. */
function PausedSpendingRow() {
    const saved = useAccount().data?.spending_paused ?? null;
    const [editing, setEditing] = useState(false);
    return (
        <SettingsRow
            label="Paused spending"
            description={
                saved?.message ? (
                    <>
                        <span className="text-foreground/85">&ldquo;{saved.message}&rdquo;</span>
                        {saved.action && <span> with a button, {saved.action.label}</span>}
                    </>
                ) : (
                    'What a user is told when your billing pauses their spending and your code doesn’t say. None set, so each pause must say what to do.'
                )
            }
            control={
                <>
                    <ConsoleButton size="sm" variant="soft" onClick={() => setEditing(true)}>
                        {saved?.message ? 'Edit' : 'Set'}
                    </ConsoleButton>
                    {editing && <PausedSpendingDialog onClose={() => setEditing(false)} />}
                </>
            }
        />
    );
}

function PausedSpendingDialog({ onClose }: { onClose: () => void }) {
    const { client } = useConsole();
    const saved = useAccount().data?.spending_paused ?? null;
    const [message, setMessage] = useState(saved?.message ?? '');
    const [label, setLabel] = useState(saved?.action?.label ?? '');
    const [url, setUrl] = useState(saved?.action?.url ?? '');
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const submit = async (e: FormEvent) => {
        e.preventDefault();
        if (!label.trim() !== !url.trim()) return setError('A button needs both a label and a link.');
        setBusy(true);
        setError(null);
        try {
            const value = message.trim() ? { message: message.trim(), action: label.trim() ? { label: label.trim(), url: url.trim() } : null } : null;
            await updateAccount(client, { spending_paused: value });
            invalidateV1('account');
            toast.success(value ? 'Default saved' : 'Default removed');
            onClose();
        } catch (err) {
            setError(formError(err).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(open) => !open && onClose()}
            title="Paused spending"
            description="What a user is told when your billing pauses their spending and your code doesn’t say: your words, and your page to pay on."
            onSubmit={(e) => void submit(e)}
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton type="submit" variant="primary" disabled={busy}>
                        {busy ? 'Saving…' : 'Save'}
                    </ConsoleButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div>
                    <label htmlFor="paused-default-message" className={FIELD_LABEL}>
                        Message
                    </label>
                    <input id="paused-default-message" maxLength={500} className={FIELD} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="You’ve used this month’s credits." />
                    <p className="m-0 mt-1.5 text-[12.5px] text-muted-foreground">Blank removes the default, so each pause must say what to do.</p>
                </div>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
                    <div>
                        <label htmlFor="paused-default-label" className={FIELD_LABEL}>
                            Button
                        </label>
                        <input id="paused-default-label" maxLength={40} className={FIELD} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Top up" />
                    </div>
                    <div>
                        <label htmlFor="paused-default-url" className={FIELD_LABEL}>
                            Link
                        </label>
                        <input id="paused-default-url" inputMode="url" className={cn(FIELD, 'font-mono text-[13px]')} value={url} onChange={(e) => setUrl(e.target.value)} />
                        <p className="m-0 mt-1.5 text-[12.5px] text-muted-foreground">{'{{user.id}}'} fills in each user&apos;s id.</p>
                    </div>
                </div>
                {error && <p className="m-0 text-[13px] text-red-600 dark:text-red-400">{error}</p>}
            </div>
        </ConsoleDialog>
    );
}

/** A value to copy, in a row's control: an install line, an address, a variable's name. */
function Copyable({ value, label }: { value: string; label: string }) {
    return (
        <span className="inline-flex max-w-[22rem] min-w-0 items-center gap-1 rounded-lg bg-foreground/[0.05] py-1 pl-2.5 pr-1">
            <code className="truncate font-mono text-[12.5px] text-foreground/85">{value}</code>
            <CopyButton value={value} label={label} />
        </span>
    );
}

function ClientsGroup() {
    const href = useConsoleHref();
    const ownerCan = useOwnerOnly();
    const tools = useAccount().data?.meta.mcp_tools ?? [];
    return (
        <section id="install" aria-label="Clients and MCP">
            <SettingsGroupTitle title="Clients and MCP" description="Install a client and give it a key. Coding agents and other tools use the platform over MCP." />
            <SettingsGroup>
                <SettingsRow label="Python" control={<Copyable value="pip install noclick" label="Copy the Python install line" />} />
                <SettingsRow label="TypeScript" control={<Copyable value="npm install noclick" label="Copy the TypeScript install line" />} />
                <SettingsRow
                    label="Your key"
                    description={`Your code reads it from ${API_KEY_ENV}, so keep it in your project's .env.`}
                    control={
                        ownerCan('keys') ? (
                            <Link to={href('keys')} className={ROW_ACTION}>
                                Create a key
                            </Link>
                        ) : (
                            <Copyable value={API_KEY_ENV} label="Copy the variable's name" />
                        )
                    }
                />
                <SettingsRow
                    label="MCP"
                    description={
                        <>
                            Clients sign in with OAuth or take a key as their bearer.
                            {tools.length > 0 && (
                                <details className="mt-1">
                                    <summary className="cursor-pointer select-none">Its {formatCount(tools.length)} tools</summary>
                                    <ul aria-label="MCP tools" className="m-0 mt-2 flex list-none flex-wrap gap-1 p-0">
                                        {tools.map((t) => (
                                            <li key={t} className="rounded bg-foreground/[0.05] px-1.5 py-[1px] font-mono text-[12px] text-foreground/80">
                                                {t}
                                            </li>
                                        ))}
                                    </ul>
                                </details>
                            )}
                        </>
                    }
                    control={<Copyable value={MCP_URL} label="Copy the MCP address" />}
                />
            </SettingsGroup>
        </section>
    );
}

function Overview({ install }: { install: boolean }) {
    const { site } = useConsole();
    const ownerCan = useOwnerOnly();
    const account = useAccount().data;
    const plan = useAccountPlan();
    useEffect(() => {
        if (install) document.getElementById('install')?.scrollIntoView({ block: 'start' });
    }, [install]);
    return (
        <>
            <PageHeader section="settings" />
            <div className="flex max-w-[880px] flex-col gap-10">
                <section aria-label="Account">
                    <SettingsGroup>
                        <BrandRow />
                        {ownerCan('accountDefaults') && (
                            <>
                                <RegionRow />
                                <PausedSpendingRow />
                            </>
                        )}
                    </SettingsGroup>
                </section>
                <ClientsGroup />
                <section aria-label="Docs and plan">
                    <SettingsGroupTitle title="Docs and plan" />
                    <SettingsGroup>
                        {docsLinks(site).map((doc) => (
                            <SettingsRow
                                key={doc.id}
                                label={doc.title}
                                control={
                                    <a href={doc.href} target="_blank" rel="noopener noreferrer" className={ROW_ACTION}>
                                        Open <ArrowUpRight className="h-3.5 w-3.5" />
                                    </a>
                                }
                            />
                        ))}
                        <SettingsRow
                            label="Plan"
                            description={
                                account && plan !== undefined ? (
                                    <p className="m-0">
                                        {plan && `${planLabel(plan)}. `}
                                        {account.email && `Signed in as ${account.email}.`}
                                    </p>
                                ) : (
                                    WAITING
                                )
                            }
                            control={
                                <a href={pricingUrl(site)} target="_blank" rel="noopener noreferrer" className={ROW_ACTION}>
                                    View plans <ArrowUpRight className="h-3.5 w-3.5" />
                                </a>
                            }
                        />
                    </SettingsGroup>
                </section>
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
