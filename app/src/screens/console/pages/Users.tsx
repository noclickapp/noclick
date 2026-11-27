// Users: the people and companies the developer's product acts for, each by the
// developer's own id for them, with this month's spend against each cap. Also
// the small form pieces Keys and a user's page share.
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Check } from 'lucide-react';
import { useNavigate } from 'react-router';
import { cn } from '@/ui/utils';
import { NoClickError, User, usage as readUsage } from 'noclick';
import { NEW_SNIPPETS } from '@/screens/console/lib/snippets';
import type { StatusLook } from '@/screens/console/lib/status';
import { userPath } from '@/screens/console/lib/userFilter';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useV1 } from '@/sdk/useV1';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { useSlashFocus } from '@/screens/console/hooks/useSlashFocus';
import { NewInCode } from '../NewInCode';
import { CapMeter } from '../ui/CapMeter';
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
            <PageHeader section="users" actions={<NewInCode kind="user" />} />
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
                        <EmptyCode title="No users yet." hint="Users appear when your code creates them, by your own id for each." snippet={NEW_SNIPPETS.user()} />
                    )
                }
            />
        </>
    );
}
