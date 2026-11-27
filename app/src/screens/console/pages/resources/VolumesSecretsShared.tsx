// Who uses a volume or a secret: the agents and apps
// by name with running sandboxes counted, for a table cell, and each one linked in a
// drawer with its mount path or binding and whose it is (a user's or your account's).
import { AppWindow, Bot, Box, type LucideIcon } from 'lucide-react';
import { Link } from 'react-router';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { truncateId } from '@/screens/console/lib/format';
import { userLabel } from '@/screens/console/lib/userFilter';
import { useConsoleHref } from '@/screens/console/hooks/useConsole';
import { useAgentNames } from '../lookups';
import { appPath } from './AppsFormat';

/** A mount (`detail` = its path) or a use (`detail` = an app's binding name). */
export interface ResourceUse {
    kind: string;
    id: string;
    name: string | null;
    detail: string | null;
}

const KINDS: Record<string, { label: string; icon: LucideIcon }> = {
    agent: { label: 'agent', icon: Bot },
    sandbox: { label: 'sandbox', icon: Box },
    project: { label: 'app', icon: AppWindow },
};

/** `assistant, booking · SHIPPING, 1 sandbox`: named uses first, running sandboxes counted. */
export function usesSummary(uses: readonly ResourceUse[]): string {
    const named = uses.filter((u) => u.kind !== 'sandbox').map((u) => (u.kind === 'project' && u.detail ? `${u.name ?? u.id} · ${u.detail}` : (u.name ?? truncateId(u.id))));
    const sandboxes = uses.filter((u) => u.kind === 'sandbox').length;
    if (sandboxes) named.push(`${sandboxes} ${sandboxes === 1 ? 'sandbox' : 'sandboxes'}`);
    return named.join(', ');
}

export function UsesSummary({ uses }: { uses: readonly ResourceUse[] }) {
    const text = usesSummary(uses);
    return text ? <span className="truncate">{text}</span> : <span className="text-muted-foreground">Nothing yet</span>;
}

/** Each use on its own row: what it is, linked to where it lives, with its path or binding. */
export function UsesList({ uses, label, empty }: { uses: readonly ResourceUse[]; label: string; empty: string }) {
    const href = useConsoleHref();
    const agents = useAgentNames();
    if (!uses.length) return <p className="m-0 text-[13px] text-muted-foreground">{empty}</p>;
    return (
        <ul aria-label={label} className={'m-0 list-none p-0'}>
            {uses.map((u) => {
                const meta = KINDS[u.kind] ?? KINDS.agent;
                const Icon = meta.icon;
                const target =
                    u.kind === 'agent' ? href(`agents/${u.id}`) : u.kind === 'sandbox' ? href('resources/sandboxes', { sandbox: u.id }) : href(appPath(u.id));
                const userId = u.kind === 'agent' ? agents.get(u.id)?.userId : undefined;
                return (
                    <li key={`${u.kind}:${u.id}:${u.detail}`} className="flex min-w-0 items-center gap-3 py-2.5">
                        <span className={cn('inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border text-foreground/70', HAIRLINE)} title={meta.label}>
                            <Icon aria-hidden className="h-3.5 w-3.5" />
                        </span>
                        <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2">
                            <Link to={target} className={cn('min-w-0 truncate text-[13px] text-foreground hover:underline', !u.name && 'font-mono text-[12px]')}>
                                {u.name ?? truncateId(u.id)}
                            </Link>
                            <span className="text-[12px] text-muted-foreground">
                                {meta.label}
                                {userId !== undefined && ` · ${userLabel(userId)}`}
                            </span>
                        </span>
                        {u.detail && <span className="shrink-0 font-mono text-[12px] text-muted-foreground">{u.detail}</span>}
                    </li>
                );
            })}
        </ul>
    );
}
