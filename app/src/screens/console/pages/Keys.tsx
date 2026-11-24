// API keys: secret keys for the clients, the Console key the console itself
// bills under, the reveal-once step where a new key meets its first call, and
// publishable keys: keys a web page can carry, which call only the endpoints
// the owner made public. The list says what each key is (name, prefix, type,
// when it was used and made); a key's drawer (`?key=`) holds its spend against
// its cap, what it may call, and its actions.
import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { useNavigate } from 'react-router';
import { toast } from 'sonner';
import { Input } from '@/ui/input';
import { Textarea } from '@/ui/textarea';
import { cn } from '@/ui/utils';
import {
    EXPLICIT_SCOPES,
    TOKEN_SCOPE,
    createKey,
    fullAccessScopes,
    listKeys,
    listPublicEndpoints,
    revokeKey,
    updateKey,
    type CreateKeyInput,
    type KeyView,
    type PublicAccessInput,
    type PublicEndpoint,
} from '@/sdk/owner';
import { keyRevealTabs } from '@/screens/console/lib/snippets';
import { formatMoney } from '@/screens/console/lib/format';
import type { StatusLook } from '@/screens/console/lib/status';
import { useSlot } from '@/slots';
import { TERMS } from '../slots';
import { useAccount, useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { ConsoleButton } from '../ui/Button';
import { CapMeter } from '../ui/CapMeter';
import { CodeSnippet } from '../ui/CodeSnippet';
import { ConsoleDialog } from '../ui/ConsoleDialog';
import { CopyButton } from '../ui/CopyButton';
import { DataTable, type Column } from '../ui/DataTable';
import { Drawer } from '../ui/Drawer';
import { ErrorPanel } from '../ui/ErrorPanel';
import { PageHeader } from '../ui/PageHeader';
import { RevealOnceSecret } from '../ui/RevealOnceSecret';
import { Segmented } from '../ui/Segmented';
import { StatusPill } from '../ui/StatusPill';
import { UserField } from '../ui/UserField';
import { TimeCell } from '../ui/TimeCell';
import { FormField, INPUT, MoreMenu, formError, parseUsd, type MenuItem } from './Users';
import { ConnectedApps } from './keys/ConnectedApps';
import { Field, Section } from './resources/shared';

// ── scopes ─────────────────────────────────────────────────────────────────

export const READ_ONLY_SCOPES = ['usage', 'operations'] as const;

export const SCOPE_GROUPS: readonly { label: string; covers: string; scopes: readonly string[] }[] = [
    {
        label: 'Admin',
        covers: 'Users, usage, policy, brand, team workspaces and the operations your calls started, and linking phone numbers to the account.',
        scopes: ['users', 'usage', 'policy', 'brand', 'operations', 'organizations', 'account:phones'],
    },
    { label: 'Connect', covers: "Ask users to connect services, and use their connections.", scopes: ['credentials:request', 'credentials:use', TOKEN_SCOPE] },
    { label: 'Tools', covers: 'Run integration operations and toolkits, host them as MCP servers, call AI models and draw pictures for replies.', scopes: ['tools', 'mcp_servers', 'ai', 'render'] },
    { label: 'People', covers: 'Ask, notify and request approvals from people, and approve, decline or switch off the calls NoClick holds for your yes.', scopes: ['humans', 'approvals:answer', 'approvals:policy'] },
    {
        label: 'Agents',
        covers: 'Hosted agents and the channels, inboxes, numbers and sandboxes they use, and taking over a coding agent’s terminal.',
        scopes: ['agents', 'agents:terminal', 'channels', 'inbox', 'phone', 'sandboxes'],
    },
    { label: 'Webhooks', covers: 'Webhook endpoints and the event log, and reading an endpoint\'s signing secret.', scopes: ['webhooks', 'webhooks:reveal'] },
    // Designed, not built yet: listed only where the account's scopes include them (the lab).
    { label: 'Acting', covers: 'Browsers and their logged-in profiles, and virtual cards.', scopes: ['browsers', 'cards', 'cards:reveal'] },
    {
        label: 'Build',
        covers: 'Apps, code repos and domains, and making an app’s code public.',
        scopes: ['apps', 'repos', 'domains', 'domains:buy', 'projects:publish'],
    },
    {
        label: 'Data',
        covers: 'Databases, buckets, volumes, dicts, queues and secrets.',
        scopes: ['databases', 'storage', 'volumes', 'dicts', 'queues', 'secrets'],
    },
    { label: 'Platform', covers: 'Workflows, and reading the values of a workflow’s variables.', scopes: ['workflows', 'workflows:variables'] },
];

/** What each scope a key holds only when it's named does, offered beside Full access or Read-only. */
const NAMED_SCOPE_HINTS: Record<string, string> = {
    [TOKEN_SCOPE]: 'reads raw provider access tokens',
    'cards:reveal': 'hands out a card’s number',
    'webhooks:reveal': 'reads a webhook’s signing secret',
    'agents:terminal': 'opens a coding agent’s terminal, which shows its sandbox’s keys and tokens',
    'approvals:answer': 'approves or declines a call NoClick holds for your yes, from your code',
    'approvals:policy': 'switches what NoClick holds for your yes, for the whole account',
    'machines:vetting': 'asks for machines for your company, saying who accepted their usage policy and when',
    'keys:create': 'makes keys no wider than itself, which go when it’s revoked',
    'account:phones': 'links phone numbers to the account, each of which signs in to it',
    'workflows:variables': 'reads the values of a workflow’s variables, which hold what its steps are given as secrets',
    'projects:publish': 'makes an app’s code public, for anyone to clone, which can’t be recalled once cloned',
};

/** The account's scopes as the API lists them: what a key with every scope holds (`full`, which Full access is built
 *  from), and with them those a key holds only when it names them (`all`). */
export function accountScopes(meta: { scopes: string[]; explicit_scopes?: string[] } | undefined): { full: string[]; all: string[] } {
    const full = meta?.scopes ?? [];
    return { full, all: [...full, ...(meta?.explicit_scopes ?? []).filter((s) => !full.includes(s))] };
}

const sameSet = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((s) => b.includes(s));

/** How a key's scopes read in the table: a preset's name, else the scopes themselves. */
export function scopeSummary(scopes: readonly string[], all: readonly string[]): { label: string } | { chips: string[] } {
    if (scopes.includes('*')) return { label: 'Full access' };
    if (all.length && sameSet(scopes, fullAccessScopes(all))) return { label: 'Full access (no raw tokens)' };
    if (sameSet(scopes, READ_ONLY_SCOPES)) return { label: 'Read-only' };
    return { chips: [...scopes] };
}

function ScopeCell({ scopes, all }: { scopes: readonly string[]; all: readonly string[] }) {
    const summary = scopeSummary(scopes, all);
    if ('label' in summary) return <span className="text-foreground/80">{summary.label}</span>;
    const shown = summary.chips.slice(0, 4);
    const rest = summary.chips.length - shown.length;
    return (
        <span className="inline-flex min-w-0 items-center gap-1 overflow-hidden" title={summary.chips.join(', ')}>
            {shown.map((s) => (
                <span key={s} className="shrink-0 rounded bg-foreground/[0.05] px-1 font-mono text-[12px] text-foreground/80">
                    {s}
                </span>
            ))}
            {rest > 0 && <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">+{rest}</span>}
        </span>
    );
}

// ── publishable keys ───────────────────────────────────────────────────────

const ENDPOINT_KINDS: Record<string, string> = { workflow: 'Workflow endpoint', agent_share: 'Agent share page' };
const endpointKind = (kind: string) => ENDPOINT_KINDS[kind] ?? kind;
const endpointRef = (e: Pick<PublicEndpoint, 'kind' | 'id'>) => `${e.kind}:${e.id}`;
const DEFAULT_PER_VISITOR = 20;

/** A publishable key with its access, or null for a secret key. */
export function publishableOf(key: KeyView): (KeyView & { publishable_key: string; public_endpoints: PublicEndpoint[] }) | null {
    return key.type === 'publishable' && key.publishable_key ? { ...key, publishable_key: key.publishable_key, public_endpoints: key.public_endpoints ?? [] } : null;
}

type KeyType = 'secret' | 'publishable';

const KEY_TYPES: readonly { value: KeyType; label: string; hint: string }[] = [
    { value: 'secret', label: 'Secret', hint: 'nk_live_: acts for this account from your server. Never put it in a page.' },
    { value: 'publishable', label: 'Publishable', hint: 'nk_pub_: safe in a web page. Calls only public endpoints you pick, rate limited per visitor.' },
];

/** What a publishable key may call, as typed into its form. */
interface AccessDraft {
    endpoints: string[];
    perVisitor: string;
    origins: string;
}

function accessDraft(key?: KeyView): AccessDraft {
    return {
        endpoints: (key?.public_endpoints ?? []).map(endpointRef),
        perVisitor: String(key?.per_visitor_limit_per_minute ?? DEFAULT_PER_VISITOR),
        origins: (key?.allowed_origins ?? []).join('\n'),
    };
}

/** The draft as the API takes it, or why it can't be sent (keyed by the form's fields). */
function parseAccess(draft: AccessDraft): { value: Required<PublicAccessInput>; errors: Record<string, string> } {
    const limit = Number(draft.perVisitor.trim());
    const origins = draft.origins.split(/[\s,]+/).filter(Boolean);
    const errors: Record<string, string> = {};
    if (!draft.endpoints.length) errors.endpoints = 'Pick at least one public endpoint.';
    if (!Number.isInteger(limit) || limit < 1) errors.perVisitor = 'Enter a whole number of calls, like 20.';
    const bad = origins.find((o) => !/^https?:\/\/[^/\s]+$/.test(o));
    if (bad) errors.origins = `${bad} isn't an origin: write https://acmebooking.com, with no path.`;
    const public_endpoints = draft.endpoints.map((ref) => {
        const at = ref.indexOf(':');
        return { kind: ref.slice(0, at), id: ref.slice(at + 1) };
    });
    return { value: { public_endpoints, per_visitor_limit_per_minute: limit, allowed_origins: origins }, errors };
}

/** The API's field names, as the access form's. */
const ACCESS_FIELDS: Record<string, string> = { public_endpoints: 'endpoints', per_visitor_limit_per_minute: 'perVisitor', allowed_origins: 'origins' };

/** The public endpoints a publishable key may call: one checkbox each, and any it lists that stopped being public. */
function PublicEndpointPicker({ value, onChange, listed = [] }: { value: string[]; onChange: (next: string[]) => void; listed?: PublicEndpoint[] }) {
    const { client } = useConsole();
    const endpoints = useV1('public_endpoints', (signal) => listPublicEndpoints(client, signal));
    if (endpoints.error !== undefined) return <ErrorPanel error={endpoints.error} onRetry={() => void endpoints.refresh()} />;
    if (!endpoints.data) return <div aria-busy className="h-20 animate-pulse rounded-lg bg-foreground/[0.03]" />;
    const live = new Set(endpoints.data.map(endpointRef));
    const stale = listed.filter((e) => !live.has(endpointRef(e)) && value.includes(endpointRef(e)));
    if (!endpoints.data.length && !stale.length) {
        return (
            <p className="m-0 rounded-lg bg-foreground/[0.03] p-3 text-[13px] text-muted-foreground">
                Nothing is public yet. Share an agent, or make a workflow&apos;s endpoint public, then give it a key.
            </p>
        );
    }
    const toggle = (ref: string, on: boolean) => onChange(on ? [...value, ref] : value.filter((x) => x !== ref));
    return (
        <div className="flex flex-col gap-1 rounded-lg bg-foreground/[0.03] p-2">
            {[...endpoints.data, ...stale].map((e) => {
                const ref = endpointRef(e);
                const gone = !live.has(ref);
                return (
                    <label key={ref} className="flex cursor-pointer items-start gap-2.5 rounded-md px-1 py-1 text-[13px]">
                        <input
                            type="checkbox"
                            aria-label={e.name ?? ref}
                            checked={value.includes(ref)}
                            onChange={(ev) => toggle(ref, ev.target.checked)}
                            className="mt-[3px] accent-[hsl(var(--foreground))]"
                        />
                        <span className="flex min-w-0 flex-col">
                            <span className={gone ? 'text-muted-foreground' : 'text-foreground'}>
                                {e.name ?? <span className="font-mono text-[12px]">{e.id}</span>} <span className="text-[12px] text-muted-foreground">· {gone ? 'no longer public' : endpointKind(e.kind)}</span>
                            </span>
                            {e.url && <span className="truncate font-mono text-[12px] text-muted-foreground">{e.url}</span>}
                        </span>
                    </label>
                );
            })}
        </div>
    );
}

/** The publishable half of a key's form: endpoints, the per-visitor limit and the allowed origins. */
function PublicAccessFields({ draft, onChange, errors, listed, cap }: { draft: AccessDraft; onChange: (next: AccessDraft) => void; errors: Record<string, string>; listed?: PublicEndpoint[]; cap?: ReactNode }) {
    return (
        <>
            <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
                <legend className="mb-1.5 p-0 text-[12px] font-medium text-muted-foreground">Public endpoints it may call</legend>
                <PublicEndpointPicker value={draft.endpoints} onChange={(endpoints) => onChange({ ...draft, endpoints })} listed={listed} />
                {errors.endpoints && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{errors.endpoints}</p>}
            </fieldset>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <FormField label="Per-visitor limit (calls a minute)" htmlFor="key-per-visitor" error={errors.perVisitor} hint="Counted per visitor IP address.">
                    <Input id="key-per-visitor" inputMode="numeric" className={cn(INPUT, 'tabular-nums')} value={draft.perVisitor} onChange={(e) => onChange({ ...draft, perVisitor: e.target.value })} />
                </FormField>
                {cap}
            </div>
            <FormField label="Allowed origins" htmlFor="key-origins" error={errors.origins} hint="The sites that may use it from a browser, one per line. Blank allows any.">
                <Textarea id="key-origins" rows={2} className="font-mono text-[12px]" value={draft.origins} onChange={(e) => onChange({ ...draft, origins: e.target.value })} placeholder="https://acmebooking.com" />
            </FormField>
        </>
    );
}

// ── create ─────────────────────────────────────────────────────────────────

type Access = 'full' | 'read' | 'custom';

const ACCESS: readonly { value: Access; label: string; hint: string }[] = [
    { value: 'full', label: 'Full access (no raw tokens)', hint: 'Every scope except those a key holds only when you name them, like raw provider tokens.' },
    { value: 'read', label: 'Read-only', hint: 'Usage and operations.' },
    { value: 'custom', label: 'Custom…', hint: 'Pick the scopes yourself.' },
];

const KEY_FIELDS: Record<string, string> = { name: 'name', scopes: 'scopes', spend_cap_usd_per_month: 'cap', user_id: 'user', expires_at: 'expires' };

function isoDay(ms: number): string {
    return new Date(ms).toISOString().slice(0, 10);
}

function CreateKeyDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (open: boolean) => void; onCreated: (rawKey: string) => void }) {
    const { client, now } = useConsole();
    const Terms = useSlot(TERMS);
    const [keyType, setKeyType] = useState<KeyType>('secret');
    const [draft, setDraft] = useState<AccessDraft>(accessDraft);
    const { full: fullScopes, all: allScopes } = accountScopes(useAccount().data?.meta);
    const [name, setName] = useState('');
    const [access, setAccess] = useState<Access>('full');
    const [custom, setCustom] = useState<string[]>([]);
    // Beside Full access or Read-only: scopes a key holds only when they're named, each chosen on its own.
    const [named, setNamed] = useState<string[]>([]);
    const [user, setUser] = useState<string | null>(null);
    const [cap, setCap] = useState('');
    const [expires, setExpires] = useState('');
    const [errors, setErrors] = useState<Record<string, string>>({});
    const [failure, setFailure] = useState<unknown>(undefined);
    const [busy, setBusy] = useState(false);

    const reset = () => {
        setKeyType('secret');
        setDraft(accessDraft());
        setName('');
        setAccess('full');
        setCustom([]);
        setNamed([]);
        setUser(null);
        setCap('');
        setExpires('');
        setErrors({});
        setFailure(undefined);
    };
    const close = (next: boolean) => {
        if (!next) reset();
        onOpenChange(next);
    };

    const scopes = access === 'full' ? [...fullAccessScopes(fullScopes), ...named] : access === 'read' ? [...READ_ONLY_SCOPES, ...named] : custom;
    const nameable = allScopes.filter((s) => EXPLICIT_SCOPES.includes(s));
    const grouped = SCOPE_GROUPS.map((g) => ({ ...g, scopes: g.scopes.filter((s) => allScopes.includes(s)) })).filter((g) => g.scopes.length);
    const ungrouped = allScopes.filter((s) => !SCOPE_GROUPS.some((g) => g.scopes.includes(s)));
    if (ungrouped.length) grouped.push({ label: 'Other', covers: 'Scopes added since this form was written.', scopes: ungrouped });

    const publishable = keyType === 'publishable';

    const submitPublishable = async () => {
        const capValue = parseUsd(cap);
        const parsed = parseAccess(draft);
        const local: Record<string, string> = { ...parsed.errors };
        if (!name.trim()) local.name = 'Name the key after the site that uses it, like booking-site.';
        if (capValue.error) local.cap = capValue.error;
        setErrors(local);
        setFailure(undefined);
        if (Object.keys(local).length) return;
        const input: CreateKeyInput = { name: name.trim(), type: 'publishable', ...parsed.value };
        if (capValue.value !== null) input.spend_cap_usd_per_month = capValue.value;
        setBusy(true);
        try {
            await createKey(client, input);
            invalidateV1('keys');
            toast.success(`${input.name} created. A publishable key isn't secret: copy it from its row whenever you need it.`);
            close(false);
        } catch (error) {
            const { field, message } = formError(error);
            const mapped = field ? { ...KEY_FIELDS, ...ACCESS_FIELDS }[field] : undefined;
            if (mapped) setErrors({ [mapped]: message });
            else setFailure(error);
        } finally {
            setBusy(false);
        }
    };

    const submit = async () => {
        if (publishable) return submitPublishable();
        const capValue = parseUsd(cap);
        const local: Record<string, string> = {};
        if (!name.trim()) local.name = 'Name the key after where it runs, like backend-prod.';
        if (!scopes.length) local.scopes = 'Pick at least one scope.';
        if (capValue.error) local.cap = capValue.error;
        setErrors(local);
        setFailure(undefined);
        if (Object.keys(local).length) return;
        const input: CreateKeyInput = { name: name.trim(), scopes };
        if (capValue.value !== null) input.spend_cap_usd_per_month = capValue.value;
        if (user) input.user_id = user;
        if (expires) input.expires_at = `${expires}T00:00:00Z`;
        setBusy(true);
        try {
            const key = await createKey(client, input);
            invalidateV1('keys');
            if (!key.raw_key) throw new Error(`The key was created but its secret didn't come back; revoke ${key.key_prefix}… and create another.`);
            reset();
            onCreated(key.raw_key);
        } catch (error) {
            const { field, message } = formError(error);
            if (field && KEY_FIELDS[field]) setErrors({ [KEY_FIELDS[field]]: message });
            else setFailure(error);
        } finally {
            setBusy(false);
        }
    };

    return (
        <ConsoleDialog
            open={open}
            onOpenChange={close}
            size="lg"
            title="New key"
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={() => close(false)}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="primary" onClick={submit} disabled={busy}>
                        {busy ? 'Creating…' : 'Create'}
                    </ConsoleButton>
                </>
            }
        >
            <form
                className="flex flex-col gap-4"
                onSubmit={(e) => {
                    e.preventDefault();
                    void submit();
                }}
            >
                <FormField label="Name" htmlFor="key-name" error={errors.name}>
                    <Input id="key-name" className={INPUT} value={name} onChange={(e) => setName(e.target.value)} placeholder={publishable ? 'booking-site' : 'backend-prod'} />
                </FormField>
                <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
                    <legend className="mb-1.5 p-0 text-[12px] font-medium text-muted-foreground">Key type</legend>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                        {KEY_TYPES.map((t) => (
                            <label
                                key={t.value}
                                htmlFor={`key-type-${t.value}`}
                                className={cn(
                                    'flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2.5 text-[13px] transition-colors',
                                    keyType === t.value ? 'border-foreground/40 bg-foreground/[0.03]' : 'border-border hover:bg-foreground/[0.02] dark:border-foreground/[0.08]'
                                )}
                            >
                                <input id={`key-type-${t.value}`} type="radio" name="key-type" value={t.value} checked={keyType === t.value} onChange={() => setKeyType(t.value)} className="mt-[3px] accent-[hsl(var(--foreground))]" />
                                <span className="flex flex-col text-foreground">
                                    {t.label}
                                    <span className="text-[12px] text-muted-foreground">{t.hint}</span>
                                </span>
                            </label>
                        ))}
                    </div>
                </fieldset>
                {publishable ? (
                    <PublicAccessFields
                        draft={draft}
                        onChange={setDraft}
                        errors={errors}
                        cap={
                            <FormField label="Monthly cap (USD)" htmlFor="key-cap" error={errors.cap} hint="Blank means no cap.">
                                <Input id="key-cap" inputMode="decimal" className={cn(INPUT, 'tabular-nums')} value={cap} onChange={(e) => setCap(e.target.value)} />
                            </FormField>
                        }
                    />
                ) : (
                    <>
                        <fieldset className="m-0 flex flex-col gap-1.5 border-0 p-0">
                            <legend className="mb-1.5 p-0 text-[12px] font-medium text-muted-foreground">Access</legend>
                            {ACCESS.map((a) => (
                                <label key={a.value} htmlFor={`key-access-${a.value}`} className="flex cursor-pointer items-start gap-2.5 rounded-md px-1 py-1 text-[13px]">
                                    <input id={`key-access-${a.value}`} type="radio" name="key-access" value={a.value} checked={access === a.value} onChange={() => setAccess(a.value)} className="mt-[3px] accent-[hsl(var(--foreground))]" />
                                    <span className="flex flex-col text-foreground">
                                        {a.label}
                                        <span className="text-[12px] text-muted-foreground">{a.hint}</span>
                                    </span>
                                </label>
                            ))}
                            {access === 'custom' && (
                                <div className="mt-1 grid grid-cols-1 gap-3 rounded-lg bg-foreground/[0.03] p-3 sm:grid-cols-2">
                                    {grouped.map((g) => (
                                        <div key={g.label} className="flex flex-col gap-1">
                                            <span className="text-[12px] font-medium text-foreground">{g.label}</span>
                                            <span className="text-[12px] text-muted-foreground">{g.covers}</span>
                                            {g.scopes.map((s) => (
                                                <label key={s} className="flex cursor-pointer items-center gap-2 text-[13px]">
                                                    <input
                                                        type="checkbox"
                                                        checked={custom.includes(s)}
                                                        onChange={(e) => setCustom((c) => (e.target.checked ? [...c, s] : c.filter((x) => x !== s)))}
                                                        className="accent-[hsl(var(--foreground))]"
                                                    />
                                                    <span className="font-mono text-[12px]">{s}</span>
                                                    {s === TOKEN_SCOPE && (
                                                        <span className="inline-flex items-center gap-1 text-[12px] text-red-600 dark:text-red-400">
                                                            <AlertTriangle className="h-3 w-3" />
                                                            reads raw provider access tokens
                                                        </span>
                                                    )}
                                                </label>
                                            ))}
                                        </div>
                                    ))}
                                </div>
                            )}
                            {access !== 'custom' && nameable.length > 0 && (
                                <div className="mt-1 flex flex-col gap-1 rounded-lg bg-foreground/[0.03] p-3" data-named-scopes>
                                    <span className="text-[12px] font-medium text-foreground">Also, only if you name them</span>
                                    <span className="text-[12px] text-muted-foreground">A key never holds these unless you pick them here.</span>
                                    {nameable.map((s) => (
                                        <label key={s} className="flex cursor-pointer items-center gap-2 text-[13px]">
                                            <input
                                                type="checkbox"
                                                checked={named.includes(s)}
                                                onChange={(e) => setNamed((n) => (e.target.checked ? [...n, s] : n.filter((x) => x !== s)))}
                                                className="accent-[hsl(var(--foreground))]"
                                            />
                                            <span className="font-mono text-[12px]">{s}</span>
                                            {NAMED_SCOPE_HINTS[s] && <span className="text-[12px] text-muted-foreground">{NAMED_SCOPE_HINTS[s]}</span>}
                                        </label>
                                    ))}
                                </div>
                            )}
                            {errors.scopes && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{errors.scopes}</p>}
                        </fieldset>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                            <div className="flex flex-col gap-1.5">
                                <UserField label="Pin to user" value={user} onChange={setUser} />
                                {errors.user && <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{errors.user}</p>}
                            </div>
                            <FormField label="Monthly cap (USD)" htmlFor="key-cap" error={errors.cap} hint="Blank means no cap.">
                                <Input id="key-cap" inputMode="decimal" className={cn(INPUT, 'tabular-nums')} value={cap} onChange={(e) => setCap(e.target.value)} />
                            </FormField>
                            <FormField label="Expires" htmlFor="key-expires" error={errors.expires} hint="Blank means never.">
                                <Input id="key-expires" type="date" min={isoDay(now() + 86_400_000)} className={INPUT} value={expires} onChange={(e) => setExpires(e.target.value)} />
                            </FormField>
                        </div>
                    </>
                )}
                {failure !== undefined && <ErrorPanel error={failure} className="bg-transparent" />}
                <Terms action="creating a key" />
                <button type="submit" hidden />
            </form>
        </ConsoleDialog>
    );
}

// ── row actions ────────────────────────────────────────────────────────────

type KeyAction = { kind: 'rename' | 'access' | 'cap' | 'revoke'; key: KeyView } | null;

/** A publishable key's endpoints, per-visitor limit and origins, changed in place. */
function AccessDialog({ keyView, onClose }: { keyView: KeyView; onClose: () => void }) {
    const { client } = useConsole();
    const [draft, setDraft] = useState<AccessDraft>(() => accessDraft(keyView));
    const [errors, setErrors] = useState<Record<string, string>>({});
    const [failure, setFailure] = useState<unknown>(undefined);
    const [busy, setBusy] = useState(false);
    const save = async () => {
        const parsed = parseAccess(draft);
        setErrors(parsed.errors);
        setFailure(undefined);
        if (Object.keys(parsed.errors).length) return;
        setBusy(true);
        try {
            await updateKey(client, keyView.id, parsed.value);
            invalidateV1('keys');
            toast.success(`${keyView.name} updated`);
            onClose();
        } catch (error) {
            const { field, message } = formError(error);
            if (field && ACCESS_FIELDS[field]) setErrors({ [ACCESS_FIELDS[field]]: message });
            else setFailure(error);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="lg"
            title={`What ${keyView.name} may call`}
            description="Pages using the key keep working; calls to an endpoint you untick stop at once."
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="primary" onClick={save} disabled={busy}>
                        Save
                    </ConsoleButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <PublicAccessFields draft={draft} onChange={setDraft} errors={errors} listed={keyView.public_endpoints} />
                {failure !== undefined && <ErrorPanel error={failure} className="bg-transparent" />}
            </div>
        </ConsoleDialog>
    );
}

function RenameDialog({ keyView, onClose }: { keyView: KeyView; onClose: () => void }) {
    const { client } = useConsole();
    const [name, setName] = useState(keyView.name);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const save = async () => {
        if (!name.trim()) return setError('A key needs a name.');
        setBusy(true);
        try {
            await updateKey(client, keyView.id, { name: name.trim() });
            invalidateV1('keys');
            toast.success('Key renamed');
            onClose();
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="sm"
            title="Rename key"
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="primary" onClick={save} disabled={busy}>
                        Save
                    </ConsoleButton>
                </>
            }
        >
            <FormField label="Name" htmlFor="rename-key" error={error}>
                <Input id="rename-key" className={INPUT} value={name} onChange={(e) => setName(e.target.value)} />
            </FormField>
        </ConsoleDialog>
    );
}

function CapDialog({ keyView, onClose }: { keyView: KeyView; onClose: () => void }) {
    const { client } = useConsole();
    const [cap, setCap] = useState(keyView.spend_cap_usd_per_month == null ? '' : String(keyView.spend_cap_usd_per_month));
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const save = async () => {
        const parsed = parseUsd(cap);
        if (parsed.error) return setError(parsed.error);
        setBusy(true);
        try {
            await updateKey(client, keyView.id, { spend_cap_usd_per_month: parsed.value });
            invalidateV1('keys');
            toast.success(parsed.value === null ? 'Cap removed' : `Cap set to ${formatMoney(parsed.value)} a month`);
            onClose();
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="sm"
            title={`Monthly cap for ${keyView.name}`}
            description={keyView.kind === 'console' ? 'Caps what actions you take in this console can spend each month.' : 'Calls with this key stop once it has spent this much this month.'}
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="primary" onClick={save} disabled={busy}>
                        Save
                    </ConsoleButton>
                </>
            }
        >
            <FormField label="Monthly cap (USD)" htmlFor="key-cap-edit" error={error} hint="Blank removes the cap.">
                <Input id="key-cap-edit" inputMode="decimal" className={cn(INPUT, 'tabular-nums')} value={cap} onChange={(e) => setCap(e.target.value)} />
            </FormField>
        </ConsoleDialog>
    );
}

function RevokeDialog({ keyView, onClose }: { keyView: KeyView; onClose: () => void }) {
    const { client } = useConsole();
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const revoke = async () => {
        setBusy(true);
        try {
            await revokeKey(client, keyView.id);
            invalidateV1('keys');
            toast.success(`${keyView.name} revoked`);
            onClose();
        } catch (e) {
            setError(formError(e).message);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open
            onOpenChange={(o) => !o && onClose()}
            size="sm"
            title={`Revoke ${keyView.name}?`}
            footer={
                <>
                    <ConsoleButton variant="ghost" onClick={onClose}>
                        Cancel
                    </ConsoleButton>
                    <ConsoleButton variant="danger" onClick={revoke} disabled={busy}>
                        Revoke
                    </ConsoleButton>
                </>
            }
        >
            <p className="m-0 text-[13px] text-muted-foreground">
                Calls using <span className="font-mono text-foreground">{keyView.key_prefix}…</span> fail immediately. Sessions minted by this key stop working too.
            </p>
            {error && <p className="m-0 mt-2 text-[12px] text-red-600 dark:text-red-400">{error}</p>}
        </ConsoleDialog>
    );
}

// ── a key's drawer ─────────────────────────────────────────────────────────

const TYPE_LABEL = (k: KeyView) => (k.kind === 'console' ? 'Console' : k.type === 'publishable' ? 'Publishable' : 'Secret');

const ACTIVE_LOOK: StatusLook = { label: 'Active', glyph: 'filled', tone: 'ink' };
const REVOKED_LOOK: StatusLook = { label: 'Revoked', glyph: 'hollow', tone: 'muted' };

/** A key's prefix, and for a publishable key (not a secret) the whole key to copy. */
function KeyPrefix({ keyView }: { keyView: KeyView }) {
    const pub = publishableOf(keyView);
    return (
        <span className="inline-flex min-w-0 items-center gap-0.5">
            <span className="truncate font-mono text-[12px] text-foreground/80">{keyView.key_prefix}…</span>
            {pub?.publishable_key && <CopyButton value={pub.publishable_key} label="Copy publishable key" />}
        </span>
    );
}

/** One key: what it spent against its cap, what it may call, then the facts; its actions at the foot. */
function KeyDrawer({ keyView, allScopes, actions, onClose }: { keyView: KeyView | undefined; allScopes: readonly string[]; actions: MenuItem[]; onClose: () => void }) {
    const pub = keyView ? publishableOf(keyView) : null;
    return (
        <Drawer
            open={!!keyView}
            onOpenChange={(open) => !open && onClose()}
            kind="API key"
            title={keyView ? (keyView.kind === 'console' ? 'Console' : keyView.name) : undefined}
            id={keyView?.id}
            status={keyView ? <StatusPill look={keyView.revoked_at ? REVOKED_LOOK : ACTIVE_LOOK} /> : undefined}
            footer={
                keyView && (
                    <>
                        {actions.map((a) => (
                            <ConsoleButton key={a.label} size="sm" variant={a.danger ? 'danger' : 'ghost'} onClick={a.onSelect}>
                                {a.label}
                            </ConsoleButton>
                        ))}
                    </>
                )
            }
        >
            {keyView && (
                <div className="flex flex-col gap-6">
                    <Section title="This month">
                        <CapMeter spent={keyView.spent_usd_this_month ?? null} cap={keyView.spend_cap_usd_per_month} noCapLabel className="max-w-xs" />
                        {keyView.kind === 'console' && <p className="m-0 mt-1.5 text-[12px] text-muted-foreground">Spend from actions you take here.</p>}
                    </Section>
                    <Section title={pub ? 'What it may call' : 'Access'}>
                        {pub ? (
                            <div className="flex flex-col gap-1.5 text-[13px]">
                                <ul aria-label="Public endpoints" className="m-0 flex list-none flex-col gap-1 p-0">
                                    {pub.public_endpoints.map((e) => (
                                        <li key={endpointRef(e)} className={cn(e.public === false ? 'text-muted-foreground line-through' : 'text-foreground')}>
                                            {e.name ?? e.id.slice(0, 8)} <span className="text-muted-foreground">{endpointKind(e.kind)}</span>
                                        </li>
                                    ))}
                                    {!pub.public_endpoints.length && <li className="text-muted-foreground">No endpoints</li>}
                                </ul>
                                {pub.per_visitor_limit_per_minute != null && <span className="tabular-nums text-muted-foreground">{pub.per_visitor_limit_per_minute} calls a minute per visitor</span>}
                                {(pub.allowed_origins ?? []).length > 0 && <span className="text-muted-foreground">From {(pub.allowed_origins ?? []).join(', ')}</span>}
                            </div>
                        ) : (
                            <ScopeCell scopes={keyView.scopes} all={allScopes} />
                        )}
                    </Section>
                    <Section title="Details">
                        <dl className="m-0">
                            <Field label="Key">
                                <KeyPrefix keyView={keyView} />
                            </Field>
                            <Field label="Type">{TYPE_LABEL(keyView)}</Field>
                            <Field label="User">{keyView.user_id ?? <span className="text-muted-foreground">The account</span>}</Field>
                            <Field label={keyView.revoked_at ? 'Revoked' : 'Last used'}>
                                <TimeCell value={keyView.revoked_at ?? keyView.last_used_at} empty="Never used" />
                            </Field>
                            <Field label="Created">
                                <TimeCell value={keyView.created_at} tier="absolute" />
                            </Field>
                            {keyView.expires_at && (
                                <Field label="Expires">
                                    <TimeCell value={keyView.expires_at} tier="absolute" />
                                </Field>
                            )}
                        </dl>
                    </Section>
                </div>
            )}
        </Drawer>
    );
}

// ── the page ───────────────────────────────────────────────────────────────

const STATUS_VIEWS = [
    { value: 'active', label: 'Active' },
    { value: 'revoked', label: 'Revoked' },
] as const;

/** The console key first, then newest first as the API lists them. */
export function orderKeys(keys: readonly KeyView[]): KeyView[] {
    return [...keys.filter((k) => k.kind === 'console'), ...keys.filter((k) => k.kind !== 'console')];
}

export default function Keys() {
    const { client } = useConsole();
    const href = useConsoleHref();
    const navigate = useNavigate();
    const allScopes = useAccount().data?.meta.scopes ?? [];
    const [statusParam, setStatus] = useSearchParam('status');
    const [selected, setSelected] = useSearchParam('key');
    const status = statusParam === 'revoked' ? 'revoked' : 'active';
    const [creating, setCreating] = useState(false);
    const [created, setCreated] = useState<string | null>(null);
    const [action, setAction] = useState<KeyAction>(null);

    const fetchPage = useCallback((cursor: string | null) => listKeys(client, { status, cursor, limit: 50 }), [client, status]);
    const keys = usePaged(`keys:list?status=${status}`, fetchPage, (k) => k.id);
    const rows = useMemo(() => orderKeys(keys.rows), [keys.rows]);
    const hasApiKeys = rows.some((k) => k.kind !== 'console');
    const selectedKey = rows.find((k) => k.id === selected);

    const menu = (k: KeyView): MenuItem[] => {
        const viewRequests: MenuItem = {
            label: 'View requests →',
            onSelect: () => navigate(href('logs/requests', { q: `key:${k.key_prefix}` })),
        };
        if (k.revoked_at) return [viewRequests];
        if (k.kind === 'console') return [{ label: 'Edit cap', onSelect: () => setAction({ kind: 'cap', key: k }) }, viewRequests];
        return [
            { label: 'Rename', onSelect: () => setAction({ kind: 'rename', key: k }) },
            ...(k.type === 'publishable' ? [{ label: 'Edit endpoints and origins', onSelect: () => setAction({ kind: 'access', key: k }) }] : []),
            { label: 'Edit cap', onSelect: () => setAction({ kind: 'cap', key: k }) },
            viewRequests,
            { label: 'Revoke', danger: true, separated: true, onSelect: () => setAction({ kind: 'revoke', key: k }) },
        ];
    };

    const columns: Column<KeyView>[] = [
        {
            id: 'name',
            header: 'Name',
            priority: 1,
            cell: (k) =>
                k.kind === 'console' ? (
                    <span className="flex min-w-0 flex-col">
                        <span className="font-medium text-foreground">Console</span>
                        <span className="truncate text-[12px] text-muted-foreground">Spend from actions you take here.</span>
                    </span>
                ) : (
                    <span className="font-medium text-foreground">{k.name}</span>
                ),
        },
        { id: 'key', header: 'Key', priority: 1, width: '9.5rem', cell: (k) => <KeyPrefix keyView={k} /> },
        { id: 'type', header: 'Type', priority: 2, width: '7.5rem', cell: (k) => TYPE_LABEL(k) },
        {
            id: 'used',
            header: status === 'revoked' ? 'Revoked' : 'Last used',
            priority: 2,
            width: '8rem',
            cell: (k) => <TimeCell value={status === 'revoked' ? k.revoked_at : k.last_used_at} empty="Never used" />,
        },
        { id: 'created', header: 'Created', priority: 3, width: '7rem', cell: (k) => <TimeCell value={k.created_at} /> },
    ];

    return (
        <>
            <PageHeader
                section="keys"
                actions={
                    <ConsoleButton variant="primary" onClick={() => setCreating(true)}>
                        New key
                    </ConsoleButton>
                }
            />
            <div className="mb-3 flex items-center gap-2">
                <Segmented label="Key status" options={STATUS_VIEWS} value={status} onChange={(v) => setStatus(v === 'active' ? null : v)} />
            </div>
            <DataTable
                label="API keys"
                columns={columns}
                rows={rows}
                getRowId={(k) => k.id}
                selectedId={selected}
                onRowClick={(k) => setSelected(k.id, { push: true })}
                loading={keys.loading}
                error={keys.error}
                onRetry={keys.refresh}
                rowActions={(k) => <MoreMenu label={`Actions for ${k.kind === 'console' ? 'Console' : k.name}`} items={menu(k)} />}
                nextCursor={keys.nextCursor}
                onLoadMore={keys.loadMore}
                loadingMore={keys.loadingMore}
                empty={<p className="m-0 py-8 text-center text-[13px] text-muted-foreground">{status === 'revoked' ? 'No revoked keys.' : 'No keys yet.'}</p>}
            />
            {status === 'active' && !keys.loading && keys.error === undefined && !hasApiKeys && rows.length > 0 && (
                <p className="m-0 mt-3 text-[13px] text-muted-foreground">No keys yet. Create one for your code; the Console key covers only what you do here.</p>
            )}
            <ConnectedApps />
            <KeyDrawer keyView={selectedKey} allScopes={allScopes} actions={selectedKey ? menu(selectedKey) : []} onClose={() => setSelected(null)} />
            <CreateKeyDialog
                open={creating}
                onOpenChange={setCreating}
                onCreated={(rawKey) => {
                    setCreating(false);
                    setCreated(rawKey);
                }}
            />
            <RevealOnceSecret secret={created} title="Key created" onDone={() => setCreated(null)}>
                {(raw) => (
                    <div className="flex flex-col gap-2">
                        <CodeSnippet tabs={keyRevealTabs(raw)} />
                        <p className="m-0 text-[12px] text-muted-foreground">
                            Only the env tab holds the key; the other snippets read <span className="font-mono">$NOCLICK_API_KEY</span>.
                        </p>
                    </div>
                )}
            </RevealOnceSecret>
            {action?.kind === 'rename' && <RenameDialog keyView={action.key} onClose={() => setAction(null)} />}
            {action?.kind === 'access' && <AccessDialog keyView={action.key} onClose={() => setAction(null)} />}
            {action?.kind === 'cap' && <CapDialog keyView={action.key} onClose={() => setAction(null)} />}
            {action?.kind === 'revoke' && <RevokeDialog keyView={action.key} onClose={() => setAction(null)} />}
        </>
    );
}

