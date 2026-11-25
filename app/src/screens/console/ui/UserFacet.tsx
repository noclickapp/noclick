// The page's user filter ("User: All ▾") and the picker it shares with write
// forms' User field: a search over GET /v1/users?q=, the five most recent by
// default, each by your id for them with its name and status.
import { useEffect, useState } from 'react';
import { Check, ChevronDown } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/ui/popover';
import { SearchField } from '@/ui/SearchField';
import { cn } from '@/ui/utils';
import { ALL_USERS, NO_USER, User } from 'noclick';
import { userFilterLabel, type UserFilterValue } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { useV1 } from '@/sdk/useV1';

export interface UserChoice {
    id: string;
    name: string | null;
    status: string;
}

function useDebounced<T>(value: T, ms: number): T {
    const [out, setOut] = useState(value);
    useEffect(() => {
        const t = window.setTimeout(() => setOut(value), ms);
        return () => window.clearTimeout(t);
    }, [value, ms]);
    return out;
}

export function useUserSearch(query: string, enabled = true) {
    const { client } = useConsole();
    const q = useDebounced(query.trim(), 200);
    return useV1<UserChoice[]>(
        enabled ? `users?picker&q=${q}` : null,
        async () => (await User.listPage({ client, q: q || undefined, limit: 5 })).data.map((u) => ({ id: u.id, name: u.name, status: u.status }))
    );
}

const ROW = 'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] transition-colors hover:bg-foreground/[0.05] disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-transparent';

/** The searchable list both the facet and the User field open. */
export function UserPickerList({
    selected,
    onPick,
    fixed,
    disableSuspended = false,
}: {
    selected: string | null;
    onPick: (value: string | null) => void;
    /** Choices above the search results (All users, Your account). */
    fixed: readonly { value: string | null; label: string }[];
    disableSuspended?: boolean;
}) {
    const [query, setQuery] = useState('');
    const users = useUserSearch(query);
    return (
        <div className="flex flex-col gap-1">
            <SearchField size="sm" value={query} onChange={setQuery} placeholder="Search users" />
            {!query &&
                fixed.map((f) => (
                    <button key={f.label} type="button" className={ROW} onClick={() => onPick(f.value)}>
                        <span className="flex-1">{f.label}</span>
                        {selected === f.value && <Check className="h-3.5 w-3.5" />}
                    </button>
                ))}
            {users.error !== undefined && <p className="m-0 px-2 py-1 text-[12px] text-red-600 dark:text-red-400">Couldn&apos;t load users.</p>}
            {users.data?.map((u) => {
                const suspended = u.status === 'suspended';
                return (
                    <button
                        key={u.id}
                        type="button"
                        className={ROW}
                        disabled={disableSuspended && suspended}
                        title={disableSuspended && suspended ? 'Suspended users are read-only' : undefined}
                        onClick={() => onPick(u.id)}
                    >
                        <span className="min-w-0 flex-1 truncate">{u.id}</span>
                        {u.name && <span className="max-w-[40%] truncate text-muted-foreground">{u.name}</span>}
                        {suspended && <span className="rounded bg-foreground/[0.06] px-1 text-[12px] text-muted-foreground">Suspended</span>}
                        {selected === u.id && <Check className="h-3.5 w-3.5" />}
                    </button>
                );
            })}
            {users.data && !users.data.length && <p className="m-0 px-2 py-1 text-[12px] text-muted-foreground">No users match.</p>}
        </div>
    );
}

/** The read filter: All users · your account's own rows · one user. */
export function UserFacet({ value, onChange, className }: { value: UserFilterValue; onChange: (value: UserFilterValue) => void; className?: string }) {
    const [open, setOpen] = useState(false);
    const label = value === ALL_USERS ? 'All' : userFilterLabel(value);
    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                className={cn(
                    'inline-flex h-8 max-w-[16rem] items-center gap-1 rounded-full bg-secondary hover:bg-accent dark:bg-foreground/[0.05] dark:hover:bg-foreground/[0.09] px-3.5 text-xs text-foreground/70 transition-colors dark:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    className
                )}
            >
                User: <span className={cn('truncate font-medium text-foreground')}>{label}</span>
                <ChevronDown className="h-3.5 w-3.5 shrink-0" />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-72 p-1.5">
                {open && (
                    <UserPickerList
                        selected={value}
                        fixed={[
                            { value: ALL_USERS, label: 'All users' },
                            { value: NO_USER, label: 'Your account (no user)' },
                        ]}
                        onPick={(v) => {
                            onChange(v ?? ALL_USERS);
                            setOpen(false);
                        }}
                    />
                )}
            </PopoverContent>
        </Popover>
    );
}
