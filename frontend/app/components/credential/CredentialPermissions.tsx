// The credential permissions editor is shared by the signed-in review page and UI tests.
// Lock controls and quick selections are scoped to one connection; machine tools can only add restrictions.
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { ArrowLeft, Check, Search, ShieldCheck } from 'lucide-react';
import { CredentialRuleLock } from './CredentialRuleLock';
import { Button } from '~/components/ui/button';
import { isReadOperation } from '~/utils/readOperations';

interface Operation {
    key: string;
    operation?: string;
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
    review_pending?: boolean;
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
    const operations = useMemo(
        () => state.operations ?? [],
        [state.operations]
    );
    const readOnlyKeys = useMemo(
        () =>
            new Set(
                operations
                    .filter((op) =>
                        isReadOperation(
                            op.operation ?? op.key.split('.').at(-1) ?? ''
                        )
                    )
                    .map((op) => op.key)
            ),
        [operations]
    );
    const lockedCount = all
        ? operations.length
        : operations.filter((op) => selected.has(op.key)).length;
    const readOnly =
        !all &&
        readOnlyKeys.size > 0 &&
        operations.every(
            (op) => selected.has(op.key) !== readOnlyKeys.has(op.key)
        );
    const selectReadOnly = () =>
        setSelected((previous) => {
            const known = new Set(operations.map((op) => op.key));
            // Keep historical restrictions that this catalog no longer describes.
            const next = new Set(
                [...previous].filter((key) => key !== '*' && !known.has(key))
            );
            operations.forEach((op) => {
                if (!readOnlyKeys.has(op.key)) next.add(op.key);
            });
            return next;
        });
    const visible = useMemo(
        () =>
            operations.filter((op) =>
                `${op.display_name} ${op.node_type} ${op.category || ''}`
                    .toLowerCase()
                    .includes(query.toLowerCase())
            ),
        [operations, query]
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
                    Locked actions wait for your approval. Everything else can
                    run freely across your coordinator, agents, and MCP clients
                    using this connection.
                </p>
                {state.detail ? (
                    <p role="alert" className="mt-8 text-sm text-destructive">
                        {state.detail}
                    </p>
                ) : (
                    <>
                        <div className="my-8 rounded-2xl bg-foreground/[0.03] p-5">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                                <p className="text-sm font-medium">
                                    Use without approval
                                </p>
                                <div
                                    className="flex items-center gap-1.5"
                                    role="group"
                                    aria-label="Use without approval"
                                >
                                    <PresetButton
                                        label="Read-only"
                                        selected={readOnly}
                                        disabled={
                                            !readOnlyKeys.size ||
                                            !state.can_edit ||
                                            saving
                                        }
                                        onClick={selectReadOnly}
                                    />
                                    <PresetButton
                                        label="All"
                                        selected={selected.size === 0}
                                        disabled={!state.can_edit || saving}
                                        onClick={() => setSelected(new Set())}
                                    />
                                    <PresetButton
                                        label="None"
                                        selected={all}
                                        disabled={!state.can_edit || saving}
                                        onClick={() =>
                                            setSelected(
                                                (previous) =>
                                                    new Set([...previous, '*'])
                                            )
                                        }
                                    />
                                </div>
                            </div>
                            <p
                                className="mt-3 text-xs leading-5 text-muted-foreground"
                                aria-live="polite"
                            >
                                {all
                                    ? 'Every action needs approval, including new ones. Choose Read-only or All to unlock individual actions.'
                                    : readOnly
                                      ? 'Read-style actions can run without asking. Other current actions need approval.'
                                      : selected.size === 0
                                        ? 'All actions can run without asking. Lock any action below to require approval.'
                                        : 'Click a lock to change approval, or start with a shortcut.'}
                            </p>
                            {!all && (
                                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                                    Read-only selects from current actions. None
                                    also locks newly added actions.
                                </p>
                            )}
                        </div>
                        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-xl bg-foreground/[0.04] px-4 py-3">
                            <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
                            <input
                                aria-label="Search tools"
                                placeholder="Search actions"
                                value={query}
                                onChange={(event) => {
                                    setQuery(event.target.value);
                                    setLimit(50);
                                }}
                                className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                            />
                            <span className="shrink-0 text-xs text-muted-foreground">
                                {lockedCount} locked ·{' '}
                                {operations.length - lockedCount} unlocked
                            </span>
                        </div>
                        <div
                            className="space-y-1"
                            aria-label="Operation permissions"
                        >
                            {visible.slice(0, limit).map((op) => (
                                <div
                                    key={op.key}
                                    className="flex items-center gap-3 rounded-xl px-4 py-3.5 transition-colors hover:bg-foreground/[0.03]"
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
                                    <CredentialRuleLock
                                        name={op.display_name}
                                        locked={all || selected.has(op.key)}
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
                                    disabled={(!changed && !state.review_pending) || saving}
                                    onClick={() => onSave([...selected])}
                                >
                                    {saving ? (
                                        'Saving…'
                                    ) : state.review_pending ? (
                                        changed ? 'Save and continue' : 'Confirm rules'
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

function PresetButton({
    label,
    selected,
    disabled,
    onClick,
}: {
    label: string;
    selected: boolean;
    disabled?: boolean;
    onClick: () => void;
}) {
    return (
        <button
            type="button"
            aria-pressed={selected}
            disabled={disabled}
            onClick={onClick}
            className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring disabled:opacity-40 ${selected ? 'border-foreground/20 bg-foreground/[0.08] text-foreground' : 'border-foreground/[0.08] text-muted-foreground hover:bg-foreground/[0.04] hover:text-foreground'}`}
        >
            {selected && <Check className="h-3 w-3" />}
            {label}
        </button>
    );
}
