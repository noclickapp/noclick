// The credential permissions editor is shared by the signed-in review page and UI tests.
// Each switch is scoped to one connection; machine tools can only add restrictions.
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { ArrowLeft, Check, Search, ShieldCheck } from 'lucide-react';
import { Button } from '~/components/ui/button';

interface Operation {
    key: string;
    node_type: string;
    display_name: string;
    description: string;
    category?: string;
}
export interface CredentialPolicyState {
    id: string;
    name: string;
    operations: Operation[];
    approval_operations: string[];
    revision: number;
    can_edit: boolean;
    detail?: string;
}

export function CredentialPermissions({
    state,
    saving,
    error,
    onSave,
}: {
    state: CredentialPolicyState;
    saving?: boolean;
    error?: string;
    onSave: (operations: string[]) => void;
}) {
    const [query, setQuery] = useState('');
    const [limit, setLimit] = useState(50);
    const [selected, setSelected] = useState(
        new Set(state.approval_operations || [])
    );
    useEffect(
        () => setSelected(new Set(state.approval_operations || [])),
        [state.revision, state.id, state.approval_operations]
    );
    const all = selected.has('*');
    const visible = useMemo(
        () =>
            (state.operations || []).filter((op) =>
                `${op.display_name} ${op.node_type} ${op.category || ''}`
                    .toLowerCase()
                    .includes(query.toLowerCase())
            ),
        [state.operations, query]
    );
    const changed =
        JSON.stringify([...selected].sort()) !==
        JSON.stringify([...(state.approval_operations || [])].sort());
    const toggle = (key: string) =>
        setSelected((previous) => {
            const next = new Set(previous);
            next.has(key) ? next.delete(key) : next.add(key);
            return next;
        });
    return (
        <main className="min-h-screen bg-background px-5 py-10 text-foreground sm:py-16">
            <div className="mx-auto max-w-3xl">
                <Link
                    to="/dashboard?tab=settings&section=credentials"
                    className="mb-9 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
                >
                    <ArrowLeft className="h-4 w-4" />
                    Connections
                </Link>
                <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-2xl bg-foreground/[0.05]">
                    <ShieldCheck className="h-5 w-5" />
                </div>
                <p className="text-sm text-muted-foreground">
                    {state.name || 'Connection'}
                </p>
                <h1 className="mt-2 text-3xl font-semibold tracking-tight">
                    Tool permissions
                </h1>
                <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
                    Choose which actions need your approval. These rules follow
                    this connection across your coordinator, agents, and MCP
                    clients.
                </p>
                {state.detail ? (
                    <p role="alert" className="mt-8 text-sm text-destructive">
                        {state.detail}
                    </p>
                ) : (
                    <>
                        <div className="my-8 flex items-center justify-between gap-5 rounded-2xl bg-foreground/[0.04] p-5">
                            <div>
                                <p className="text-sm font-medium">
                                    Ask before every action
                                </p>
                                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                                    New tools will need approval too. Each
                                    approval allows one call.
                                </p>
                            </div>
                            <RuleToggle
                                label="Require approval for all actions"
                                checked={all}
                                disabled={!state.can_edit || saving}
                                onChange={() => toggle('*')}
                            />
                        </div>
                        <div className="mb-5 flex items-center gap-3 rounded-xl bg-foreground/[0.04] px-4 py-3">
                            <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
                            <input
                                aria-label="Search tools"
                                placeholder="Search actions"
                                value={query}
                                onChange={(event) => {
                                    setQuery(event.target.value);
                                    setLimit(50);
                                }}
                                className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                            />
                            <span className="shrink-0 text-xs text-muted-foreground">
                                {all ? 'All' : selected.size} require approval
                            </span>
                        </div>
                        <div
                            className="space-y-1"
                            aria-label="Operation permissions"
                        >
                            {visible.slice(0, limit).map((op) => (
                                <div
                                    key={op.key}
                                    className="flex items-center gap-5 rounded-xl px-4 py-3.5 transition-colors hover:bg-foreground/[0.03]"
                                >
                                    <div className="min-w-0 flex-1">
                                        <p className="text-sm font-medium">
                                            {op.display_name}
                                        </p>
                                        <p className="mt-1 text-xs text-muted-foreground">
                                            {op.node_type
                                                .replace(/^automation-/, '')
                                                .replaceAll('-', ' ')}
                                            {op.category
                                                ? ` · ${op.category}`
                                                : ''}
                                        </p>
                                    </div>
                                    <span className="hidden text-xs text-muted-foreground sm:block">
                                        {all || selected.has(op.key)
                                            ? 'Ask first'
                                            : 'Can run'}
                                    </span>
                                    <RuleToggle
                                        label={`Require approval for ${op.display_name}`}
                                        checked={all || selected.has(op.key)}
                                        disabled={
                                            all || !state.can_edit || saving
                                        }
                                        onChange={() => toggle(op.key)}
                                    />
                                </div>
                            ))}
                            {!visible.length && (
                                <p className="py-10 text-center text-sm text-muted-foreground">
                                    {query
                                        ? 'No matching actions.'
                                        : 'This connection has no discoverable integration actions yet.'}
                                </p>
                            )}
                            {visible.length > limit && (
                                <Button
                                    variant="ghost"
                                    onClick={() =>
                                        setLimit((value) => value + 50)
                                    }
                                >
                                    Show more actions ({visible.length - limit}{' '}
                                    remaining)
                                </Button>
                            )}
                        </div>
                        <div className="sticky bottom-0 mt-8 flex flex-wrap items-center justify-between gap-4 bg-background/95 py-5 backdrop-blur">
                            <p className="max-w-md text-xs leading-5 text-muted-foreground">
                                Agents can add restrictions. Only you can remove
                                them here. Option lookups also ask for approval
                                on restricted connections.
                            </p>
                            {state.can_edit && (
                                <Button
                                    disabled={!changed || saving}
                                    onClick={() => onSave([...selected])}
                                >
                                    {saving ? (
                                        'Saving…'
                                    ) : changed ? (
                                        'Save rules'
                                    ) : (
                                        <>
                                            <Check className="mr-2 h-3.5 w-3.5" />
                                            Saved
                                        </>
                                    )}
                                </Button>
                            )}
                        </div>
                        {!state.can_edit && (
                            <p className="text-sm text-muted-foreground">
                                The connection owner manages these rules.
                            </p>
                        )}
                        {error && (
                            <p
                                role="alert"
                                className="text-sm text-destructive"
                            >
                                {error}
                            </p>
                        )}
                    </>
                )}
            </div>
        </main>
    );
}

function RuleToggle({
    label,
    checked,
    disabled,
    onChange,
}: {
    label: string;
    checked: boolean;
    disabled?: boolean;
    onChange: () => void;
}) {
    return (
        <button
            type="button"
            role="switch"
            aria-label={label}
            aria-checked={checked}
            disabled={disabled}
            onClick={onChange}
            className={`relative h-6 w-10 shrink-0 rounded-full transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring disabled:opacity-40 ${checked ? 'bg-primary' : 'bg-foreground/15'}`}
        >
            <span
                className={`absolute top-1 h-4 w-4 rounded-full transition-all ${checked ? 'left-5 bg-primary-foreground' : 'left-1 bg-muted-foreground'}`}
            />
        </button>
    );
}
