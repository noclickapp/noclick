// Users: the people and companies the developer's product acts for, each by the
// developer's own id for them, with this month's spend against each cap. Also
// the small form pieces Keys and a user's page share.
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Check } from 'lucide-react';
import { Link, useNavigate } from 'react-router';
import { toast } from 'sonner';
import { Input } from '@/ui/input';
import { Textarea } from '@/ui/textarea';
import { cn } from '@/ui/utils';
import { Conflict, NoClickError, User, usage as readUsage } from 'noclick';
import { USERS_EMPTY } from '@/screens/console/lib/snippets';
import type { StatusLook } from '@/screens/console/lib/status';
import { userPath } from '@/screens/console/lib/userFilter';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { useSlashFocus } from '@/screens/console/hooks/useSlashFocus';
import { ConsoleButton } from '../ui/Button';
import { CapMeter } from '../ui/CapMeter';
import { ConsoleDialog } from '../ui/ConsoleDialog';
import { DataTable, type Column } from '../ui/DataTable';
import { EmptyCode } from '../ui/EmptyCode';
import { FacetSelect } from '../ui/FacetSelect';
import { PageHeader } from '../ui/PageHeader';
import { SearchField } from '@/ui/SearchField';
import { StatusPill } from '../ui/StatusPill';
import { TimeCell } from '../ui/TimeCell';

// ── shared form pieces ────────────────────────────────────────────────────

export const INPUT = 'h-9 text-[13px] md:text-[13px]';

export function FormField({ label, htmlFor, hint, error, children, className }: { label: string; htmlFor?: string; hint?: ReactNode; error?: string | null; children: ReactNode; className?: string }) {
    return (
        <div className={cn('flex flex-col gap-1.5', className)}>
            <label htmlFor={htmlFor} className="text-[12px] font-medium text-muted-foreground">
                {label}
            </label>
            {children}
            {error ? <p className="m-0 text-[12px] text-red-600 dark:text-red-400">{error}</p> : hint ? <p className="m-0 text-[12px] text-muted-foreground">{hint}</p> : null}
        </div>
    );
}

/** A dollar amount typed into a form: blank is no value, anything else must be a non-negative number. */
export function parseUsd(text: string): { value: number | null; error: string | null } {
    const t = text.trim().replace(/^\$/, '');
    if (!t) return { value: null, error: null };
    const n = Number(t);
    if (!Number.isFinite(n) || n < 0) return { value: null, error: 'Enter an amount in dollars, like 50.' };
    return { value: n, error: null };
}

/** The API's refusal for a form: its message and next step, and which field it names. */
export function formError(error: unknown): { message: string; field: string | null } {
    if (error instanceof NoClickError) {
        const field = typeof error.details.field === 'string' ? error.details.field : null;
        return { message: error.nextStep ? `${error.message} ${error.nextStep}` : error.message, field };
    }
    return { message: error instanceof Error ? error.message : String(error), field: null };
}

export { MoreMenu, type MenuItem } from '../ui/MoreMenu';

/** This month's spend per user id (`GET /v1/usage?group_by=user`). */
export function useUserSpend() {
    const { client } = useConsole();
    return useV1('usage?group_by=user', async () => {
        const usage = await readUsage({ client, groupBy: 'user', user: null });
        return new Map(usage.groups.filter((g) => g.id).map((g) => [g.id as string, g.usd]));
    });
}

type SpendRead = { data: Map<string, number> | undefined; error: unknown; refresh: () => Promise<void> };

/** A user's spend from the grouped read: 0 when they have none, null (Unknown) when the read failed, undefined while loading. */
export function spendOf(spend: Pick<SpendRead, 'data' | 'error'>, userId: string): number | null | undefined {
    if (spend.data) return spend.data.get(userId) ?? 0;
    return spend.error !== undefined ? null : undefined;
}

/** This month against the cap; a skeleton bar while the spend read is in flight. */
export function UserSpend({ spent, cap, noCapLabel, className }: { spent: number | null | undefined; cap: number | null | undefined; noCapLabel?: boolean; className?: string }) {
    if (spent === undefined) return <span aria-busy aria-label="Loading spend" className={cn('inline-block h-3 w-24 animate-pulse rounded bg-foreground/[0.07]', className)} />;
    return <CapMeter spent={spent} cap={cap} noCapLabel={noCapLabel} className={className} />;
}

/** One line when the spend read failed, so "Unknown" never stands without a way to retry. */
export function SpendReadError({ spend, className }: { spend: SpendRead; className?: string }) {
    if (spend.error === undefined) return null;
    return (
        <p role="alert" className={cn('m-0 flex items-center gap-2 text-[13px] text-muted-foreground', className)}>
            {"Spend couldn't be read."}
            <button type="button" onClick={() => void spend.refresh()} className="font-medium text-foreground underline underline-offset-2">
                Retry
            </button>
        </p>
    );
}

export function userStatusLook(status: string): StatusLook {
    if (status === 'active') return { label: 'Active', glyph: 'check', tone: 'ink' };
    if (status === 'suspended') return { label: 'Suspended', glyph: 'muted', tone: 'muted' };
    return { label: status.charAt(0).toUpperCase() + status.slice(1), glyph: 'muted', tone: 'muted' };
}

// ── create ─────────────────────────────────────────────────────────────────

interface UserDraft {
    id: string;
    name: string;
    email: string;
    phone: string;
    cap: string;
    metadata: string;
}

const EMPTY_DRAFT: UserDraft = { id: '', name: '', email: '', phone: '', cap: '', metadata: '' };

/** A metadata textarea's JSON: blank is none; anything else must be an object. */
export function parseMetadata(text: string): { value: Record<string, unknown> | null; error: string | null } {
    if (!text.trim()) return { value: null, error: null };
    try {
        const parsed: unknown = JSON.parse(text);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return { value: parsed as Record<string, unknown>, error: null };
        return { value: null, error: 'Metadata must be a JSON object, like {"plan": "team"}.' };
    } catch {
        return { value: null, error: "That isn't valid JSON." };
    }
}

function CreateUserDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
    const { client } = useConsole();
    const href = useConsoleHref();
    const navigate = useNavigate();
    const [draft, setDraft] = useState<UserDraft>(EMPTY_DRAFT);
    const [errors, setErrors] = useState<Partial<Record<keyof UserDraft | 'form', string>>>({});
    const [existingId, setExistingId] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const set = (field: keyof UserDraft) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [field]: e.target.value }));

    const close = (next: boolean) => {
        if (!next) {
            setDraft(EMPTY_DRAFT);
            setErrors({});
            setExistingId(null);
        }
        onOpenChange(next);
    };

    const submit = async () => {
        const cap = parseUsd(draft.cap);
        const metadata = parseMetadata(draft.metadata);
        const local = {
            id: draft.id.trim() ? undefined : 'Every user needs your id for them.',
            cap: cap.error ?? undefined,
            metadata: metadata.error ?? undefined,
        };
        setExistingId(null);
        if (local.id || local.cap || local.metadata) {
            setErrors(local);
            return;
        }
        setErrors({});
        setBusy(true);
        try {
            const user = await User.create(draft.id.trim(), {
                client,
                name: draft.name.trim() || undefined,
                email: draft.email.trim() || undefined,
                phone: draft.phone.trim() || undefined,
                spendCapUsdPerMonth: cap.value ?? undefined,
                metadata: metadata.value ?? undefined,
            });
            invalidateV1('users');
            toast.success(`User ${user.id} created`);
            close(false);
            navigate(href(userPath(user.id)));
        } catch (error) {
            if (error instanceof Conflict && error.existingId) {
                setExistingId(error.existingId);
                setErrors({ id: 'A user with this id exists.' });
            } else {
                const { message, field } = formError(error);
                const byField: Record<string, keyof UserDraft> = { id: 'id', name: 'name', email: 'email', phone: 'phone', spend_cap_usd_per_month: 'cap', metadata: 'metadata' };
                setErrors(field && byField[field] ? { [byField[field]]: message } : { form: message });
            }
        } finally {
            setBusy(false);
        }
    };

    return (
        <ConsoleDialog
            open={open}
            onOpenChange={close}
            title="New user"
            description="Your code usually does this with User.from_id(…, create_if_missing=True)."
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
                className="grid grid-cols-1 gap-3 sm:grid-cols-2"
                onSubmit={(e) => {
                    e.preventDefault();
                    void submit();
                }}
            >
                <FormField
                    label="ID"
                    htmlFor="user-id"
                    className="sm:col-span-2"
                    hint="Your id for this user, e.g. user_42 or the id your sign-in provider gives them."
                    error={errors.id}
                >
                    <Input id="user-id" className={cn(INPUT, 'font-mono')} value={draft.id} onChange={set('id')} />
                </FormField>
                {existingId && (
                    <p className="m-0 -mt-1 text-[12px] text-muted-foreground sm:col-span-2">
                        <Link to={href(userPath(existingId))} className="text-foreground underline underline-offset-2" onClick={() => close(false)}>
                            Open {existingId}
                        </Link>
                    </p>
                )}
                <FormField label="Name" htmlFor="user-name" error={errors.name}>
                    <Input id="user-name" className={INPUT} value={draft.name} onChange={set('name')} />
                </FormField>
                <FormField label="Email" htmlFor="user-email" error={errors.email}>
                    <Input id="user-email" type="email" className={INPUT} value={draft.email} onChange={set('email')} />
                </FormField>
                <FormField label="Phone" htmlFor="user-phone" hint="E.164, e.g. +14155550101." error={errors.phone}>
                    <Input id="user-phone" className={INPUT} value={draft.phone} onChange={set('phone')} />
                </FormField>
                <FormField label="Monthly cap (USD)" htmlFor="user-cap" hint="Blank means no cap." error={errors.cap}>
                    <Input id="user-cap" inputMode="decimal" className={cn(INPUT, 'tabular-nums')} value={draft.cap} onChange={set('cap')} />
                </FormField>
                <FormField label="Metadata (JSON)" htmlFor="user-metadata" className="sm:col-span-2" error={errors.metadata}>
                    <Textarea id="user-metadata" rows={3} className="font-mono text-[12px] md:text-[12px]" placeholder='{"plan": "team"}' value={draft.metadata} onChange={set('metadata')} />
                </FormField>
                {errors.form && <p className="m-0 text-[13px] text-red-600 dark:text-red-400 sm:col-span-2">{errors.form}</p>}
                <button type="submit" hidden />
            </form>
        </ConsoleDialog>
    );
}

// ── the list ───────────────────────────────────────────────────────────────

const STATUS_OPTIONS = [
    { value: 'active', label: 'Active' },
    { value: 'suspended', label: 'Suspended' },
] as const;

/** A search box bound to `?name=`: typing writes it after `ms`; navigation (a sidebar click, back/forward) replaces the text. */
function useDebouncedParam(name: string, ms = 250): [string, (value: string) => void] {
    const [param, setParam] = useSearchParam(name);
    const [text, setText] = useState(param ?? '');
    const written = useRef(param ?? '');
    useEffect(() => {
        const next = param ?? '';
        if (next === written.current) return;
        written.current = next;
        setText(next);
    }, [param]);
    useEffect(() => {
        if (text === written.current) return;
        const t = window.setTimeout(() => {
            written.current = text;
            setParam(text || null);
        }, ms);
        return () => window.clearTimeout(t);
    }, [text, setParam, ms]);
    return [text, setText];
}

export default function Users() {
    const { client } = useConsole();
    const href = useConsoleHref();
    const navigate = useNavigate();
    const [q] = useSearchParam('q');
    const [status, setStatus] = useSearchParam('status');
    const [text, setText] = useDebouncedParam('q');
    const [creating, setCreating] = useState(false);
    const search = useRef<HTMLInputElement>(null);
    useSlashFocus(search);

    const statusFilter = status === 'active' || status === 'suspended' ? status : undefined;
    const fetchPage = useCallback(
        (cursor: string | null) => User.listPage({ client, q: q || undefined, status: statusFilter, cursor, limit: 50 }),
        [client, q, statusFilter]
    );
    const users = usePaged(`users:list?q=${q ?? ''}&status=${statusFilter ?? ''}`, fetchPage, (u) => u.id);
    const spend = useUserSpend();
    const filtered = Boolean(q || statusFilter);

    const columns: Column<User>[] = [
        {
            id: 'user',
            header: 'User',
            priority: 1,
            cell: (u) => (
                <span className="flex min-w-0 flex-col py-1">
                    <span className="truncate text-[14px] font-medium text-foreground">{u.id}</span>
                    {(u.name || u.email) && <span className="truncate text-[12px] text-muted-foreground">{u.name ?? u.email}</span>}
                </span>
            ),
        },
        { id: 'status', header: 'Status', priority: 1, width: '7.5rem', cell: (u) => <StatusPill look={userStatusLook(u.status)} /> },
        {
            id: 'phone',
            header: 'Phone',
            priority: 3,
            width: '11rem',
            cell: (u) =>
                u.phone ? (
                    <span className="inline-flex items-center gap-1 font-mono text-[12px]">
                        {u.phone}
                        {u.phoneVerifiedAt && <Check className="h-3.5 w-3.5 text-muted-foreground" aria-label="Verified" />}
                    </span>
                ) : (
                    <span className="text-muted-foreground">—</span>
                ),
        },
        {
            id: 'month',
            header: 'This month',
            priority: 1,
            align: 'right',
            className: 'w-[9rem] sm:w-[11.5rem]',
            cell: (u) => <UserSpend spent={spendOf(spend, u.id)} cap={u.spendCapUsdPerMonth} />,
        },
        { id: 'created', header: 'Created', priority: 3, width: '7rem', cell: (u) => <TimeCell value={u.createdAt} /> },
    ];

    return (
        <>
            <PageHeader
                section="users"
                actions={
                    <ConsoleButton variant="primary" onClick={() => setCreating(true)}>
                        New user
                    </ConsoleButton>
                }
            />
            <div className="mb-3 flex flex-wrap items-center gap-2">
                <SearchField ref={search} size="sm" value={text} onChange={setText} placeholder="Search by id, name or email" aria-label="Search users" className="flex-1 sm:max-w-xs" />
                <FacetSelect label="Status" value={statusFilter ?? null} options={STATUS_OPTIONS} onChange={setStatus} />
            </div>
            <SpendReadError spend={spend} className="mb-2" />
            <DataTable
                label="Users"
                columns={columns}
                rows={users.rows}
                getRowId={(u) => u.id}
                loading={users.loading}
                error={users.error}
                onRetry={users.refresh}
                onRowClick={(u) => navigate(href(userPath(u.id)))}
                nextCursor={users.nextCursor}
                onLoadMore={users.loadMore}
                loadingMore={users.loadingMore}
                empty={
                    filtered ? (
                        <p className="m-0 py-8 text-center text-[13px] text-muted-foreground">No users match.</p>
                    ) : (
                        <EmptyCode title="No users yet." hint="Users appear when your code creates them, by your own id for each." snippet={USERS_EMPTY} />
                    )
                }
            />
            <CreateUserDialog open={creating} onOpenChange={setCreating} />
        </>
    );
}
