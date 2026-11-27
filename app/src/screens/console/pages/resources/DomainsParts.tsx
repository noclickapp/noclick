// Pieces the Domains panel, its dialogs and its drawer share: the status look, a
// DNS record list with copy buttons and per-record state, what a domain serves,
// the notice box and the empty state's code.
import type { ReactNode } from 'react';
import { Link } from 'react-router';
import { AppWindow, Inbox as InboxIcon, Lock, Palette, Trash2 } from 'lucide-react';
import { HAIRLINE, SURFACE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import type { DnsRecord, Domain, DomainService } from 'noclick';
import type { StatusLook } from '@/screens/console/lib/status';
import type { Snippet } from '@/screens/console/lib/snippets';
import { useConsoleHref } from '@/screens/console/hooks/useConsole';
import { ConsoleButton } from '../../ui/Button';
import { CopyButton } from '../../ui/CopyButton';
import { StatusPill } from '../../ui/StatusPill';
import { appPath } from './AppsFormat';

const DAY_MS = 86_400_000;

/** `Sep 1, 2027`: registration dates are days, and a year out needs its year. */
export function dayLabel(value: Date | null | undefined): string {
    if (!value) return '—';
    return value.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
}

/** `a year`, `2 years`. */
export function yearsLabel(years: number): string {
    return years === 1 ? 'a year' : `${years} years`;
}

/** How often a renewal of `years` comes round: `a year`, `every 2 years`. */
export function everyLabel(years: number): string {
    return years === 1 ? 'a year' : `every ${years} years`;
}

/** Whole days from `now` until `value` (negative once past). */
export function daysUntil(value: Date | null | undefined, now: number): number | null {
    return value ? Math.ceil((value.getTime() - now) / DAY_MS) : null;
}

export function domainLook(domain: Pick<Domain, 'status' | 'source' | 'expiresAt'>, now: number): StatusLook {
    switch (domain.status) {
        case 'awaiting_human':
            return { label: 'Waiting', reason: 'approval', glyph: 'waiting', tone: 'ink' };
        case 'registering':
            return { label: 'Registering', glyph: 'filled', tone: 'ink' };
        case 'transferring_in':
            return { label: 'Transferring in', glyph: 'filled', tone: 'ink' };
        case 'pending_dns':
            // Bought: NoClick is setting its DNS up. Connected: waiting on the person's records.
            return domain.source === 'bought' ? { label: 'Configuring DNS', glyph: 'filled', tone: 'ink' } : { label: 'Pending DNS', glyph: 'waiting', tone: 'ink' };
        case 'active':
            return { label: 'Active', glyph: 'check', tone: 'ink' };
        case 'registrant_unverified':
            return { label: 'Registrant unverified', glyph: 'waiting', tone: 'ink' };
        case 'expiring': {
            const days = daysUntil(domain.expiresAt, now);
            return { label: 'Expiring', reason: days !== null && days >= 0 ? `in ${days}d` : null, glyph: 'waiting', tone: 'ink' };
        }
        case 'expired':
            return { label: 'Expired', glyph: 'muted', tone: 'muted' };
        case 'transferring_out':
            return { label: 'Transferring out', glyph: 'filled', tone: 'ink' };
        case 'failed':
            return { label: 'Failed', glyph: 'cross', tone: 'failure' };
        default:
            return { label: domain.status ?? 'Unknown', glyph: 'filled', tone: 'ink' };
    }
}

export function sourceLabel(domain: Pick<Domain, 'source'>): string {
    return domain.source === 'bought' ? 'Bought' : domain.source === 'transferred' ? 'Transferred' : 'Connected';
}

/** Registered through NoClick (bought or transferred in), so it renews and transfers out here. */
export function registeredHere(domain: Pick<Domain, 'source'>): boolean {
    return domain.source !== 'connected';
}

function recordLook(status: string | null): StatusLook {
    if (status === 'verified') return { label: 'Verified', glyph: 'check', tone: 'ink' };
    if (status === 'conflict') return { label: 'Conflict', glyph: 'cross', tone: 'failure' };
    return { label: 'Pending', glyph: 'waiting', tone: 'ink' };
}

export const BADGE = 'shrink-0 rounded-md bg-foreground/[0.06] px-1.5 py-[1px] text-[12px] font-medium text-muted-foreground';

/** A value you paste into a DNS host, with its copy button. */
function Copyable({ value, label }: { value: string; label: string }) {
    return (
        <span className="group/copy inline-flex min-w-0 max-w-full items-center gap-1">
            <span className="truncate font-mono text-[12px]" title={value}>
                {value}
            </span>
            <CopyButton value={value} label={label} className="opacity-100 md:opacity-0 md:group-hover/copy:opacity-100 md:group-focus-within/copy:opacity-100" />
        </span>
    );
}

/**
 * DNS records as a list: type, name and value (each copyable), the record's state
 * and what it's for. `onDelete` adds a remove button to records you own; NoClick's
 * (`managed`) carry a lock instead.
 */
export function DnsRecordList({ records, label, onDelete, busy }: { records: readonly DnsRecord[]; label: string; onDelete?: (record: DnsRecord) => void; busy?: boolean }) {
    return (
        <ul aria-label={label} className={'m-0 -mx-3 list-none p-0'}>
            {records.map((r) => (
                <li key={`${r.type} ${r.name} ${r.value}`} className={cn('flex flex-col gap-1 px-3 py-2.5')}>
                    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 sm:flex-nowrap">
                        <span className="w-14 shrink-0 font-mono text-[12px] font-medium">{r.type}</span>
                        <span className="min-w-0 flex-1 sm:w-40 sm:flex-none">
                            <Copyable value={r.name} label={`Copy name ${r.name}`} />
                        </span>
                        <span className="order-last min-w-0 basis-full sm:order-none sm:basis-auto sm:flex-1">
                            <Copyable value={r.value} label={`Copy value for ${r.name}`} />
                        </span>
                        <span className="ml-auto flex shrink-0 items-center gap-2 sm:ml-0">
                            {!r.required && <span className={BADGE}>Optional</span>}
                            <StatusPill look={recordLook(r.status)} />
                            {r.managed ? (
                                <span title="Kept by NoClick for what the domain serves" className="inline-flex h-6 w-6 items-center justify-center text-muted-foreground">
                                    <Lock aria-label="Managed by NoClick" className="h-3.5 w-3.5" />
                                </span>
                            ) : onDelete ? (
                                <ConsoleButton variant="ghost" size="icon" aria-label={`Delete ${r.type} ${r.name}`} disabled={busy} onClick={() => onDelete(r)} icon={<Trash2 className="h-3.5 w-3.5" />} />
                            ) : null}
                        </span>
                    </div>
                    {r.purpose && <p className="m-0 text-[12px] text-muted-foreground sm:pl-[4.25rem]">{r.purpose}</p>}
                </li>
            ))}
        </ul>
    );
}

/** What a domain points at, each once (an app may be served at several of its names), a link to its page. */
export function ServesLinks({ serves, empty = 'Nothing yet' }: { serves: readonly DomainService[]; empty?: ReactNode }) {
    const href = useConsoleHref();
    if (!serves.length) return <span className="text-muted-foreground">{empty}</span>;
    const each = [...new Map(serves.map((s) => [`${s.kind}:${s.id}`, s])).values()];
    return (
        <span className="inline-flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            {each.map((s) => {
                // `brand`: the account's approval, question and hand-off pages.
                const Icon = s.kind === 'inbox' ? InboxIcon : s.kind === 'brand' ? Palette : AppWindow;
                const to = s.kind === 'inbox' ? href('resources/inboxes', { inbox: s.id }) : s.kind === 'brand' ? href('settings/brand') : href(appPath(s.id));
                return (
                    <Link key={`${s.kind}:${s.id}`} to={to} onClick={(e) => e.stopPropagation()} className="inline-flex min-w-0 items-center gap-1 text-foreground underline-offset-2 hover:underline">
                        <Icon aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <span className={cn('truncate', s.kind === 'inbox' && 'font-mono text-[12px]')}>{s.name}</span>
                    </Link>
                );
            })}
        </span>
    );
}

/** A quiet box for what needs the reader: a title, what to do, and its actions. */
export function Notice({ title, children, actions, icon }: { title: string; children: ReactNode; actions?: ReactNode; icon?: ReactNode }) {
    return (
        <div role="note" aria-label={title} className={cn(SURFACE, 'flex gap-3 px-4 py-3 text-[13px]')}>
            {icon && <span className="mt-0.5 shrink-0 text-muted-foreground">{icon}</span>}
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <p className="m-0 font-medium text-foreground">{title}</p>
                <div className="text-muted-foreground">{children}</div>
                {actions && <div className="mt-1.5 flex flex-wrap items-center gap-2">{actions}</div>}
            </div>
        </div>
    );
}

/** A value shown whole with a copy button (a transfer's auth code). */
export function LinkBox({ url, label }: { url: string; label: string }) {
    return (
        <span className={cn('flex min-w-0 items-center gap-1 rounded-md border bg-foreground/[0.03] py-1 pl-2.5 pr-1', HAIRLINE)}>
            <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-foreground" title={url}>
                {url}
            </span>
            <CopyButton value={url} label={`Copy ${label}`} />
        </span>
    );
}

/** The first call: find a name and buy it, or connect one the person owns. */
export const DOMAINS_EMPTY: Snippet = {
    python: [
        'import noclick',
        '[offer] = noclick.Domain.search("acmebooking", tlds=["com"], limit=1)',
        'domain = noclick.Domain.buy(offer, max_price_usd=15).wait()',
        'print(domain.name, domain.expires_at)',
    ].join('\n'),
    typescript: [
        'import { Domain } from "noclick";',
        'const [offer] = await Domain.search("acmebooking", { tlds: ["com"], limit: 1 });',
        'const purchase = await Domain.buy(offer, { maxPriceUsd: 15 });',
        'const domain = await purchase.wait();',
        'console.log(domain.name, domain.expiresAt);',
    ].join('\n'),
};
