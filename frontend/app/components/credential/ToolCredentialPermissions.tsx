// Bind workflow tool rows to their connection's existing, owner-managed policy.
// The signed-in route supplies CSRF and revision checks; these edits never change
// the node's operation allowlist or create a separate workflow permission policy.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useFetcher } from 'react-router';
import { CredentialRuleLock } from './CredentialRuleLock';
import type { CredentialPolicyState } from './CredentialPermissions';
import { TooltipProvider } from '~/components/ui/tooltip';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '~/components/ui/select';

export interface ToolPermissionControls {
    header: ReactNode;
    lock: (operation: string, name: string) => ReactNode;
}

export function ToolCredentialPermissions({
    credentialIds,
    nodeType,
    hideSummary = false,
    children,
}: {
    credentialIds: Record<string, string>;
    nodeType: string;
    hideSummary?: boolean;
    children: (controls: ToolPermissionControls) => ReactNode;
}) {
    const [active, setActive] = useState('');
    const ids = [
        ...new Set(
            Object.entries(credentialIds)
                .filter(
                    ([key, value]) =>
                        key !== 'credential_type' &&
                        typeof value === 'string' &&
                        !!value
                )
                .map(([, value]) => value)
        ),
    ];
    const credentialId = ids.includes(active) ? active : ids[0];
    if (!credentialId) return children({ header: null, lock: () => null });
    return (
        <BoundCredentialPolicy
            key={credentialId}
            credentialId={credentialId}
            ids={ids}
            onSelect={setActive}
            nodeType={nodeType}
            hideSummary={hideSummary}
        >
            {children}
        </BoundCredentialPolicy>
    );
}

function BoundCredentialPolicy({
    credentialId,
    ids,
    onSelect,
    nodeType,
    hideSummary,
    children,
}: {
    credentialId: string;
    ids: string[];
    onSelect: (id: string) => void;
    nodeType: string;
    hideSummary: boolean;
    children: (controls: ToolPermissionControls) => ReactNode;
}) {
    const policy = useFetcher<{
        state: CredentialPolicyState;
        csrfToken: string;
    }>();
    const update = useFetcher<{ saved?: boolean; error?: string }>();
    const [error, setError] = useState<string>();
    const [pendingKey, setPendingKey] = useState<string>();
    const [optimistic, setOptimistic] = useState<{
        key: string;
        locked: boolean;
    }>();
    const handled = useRef<unknown>(undefined);
    const path = `/credential/permissions/${encodeURIComponent(credentialId)}`;
    const { load } = policy;
    useEffect(() => {
        void load(path);
    }, [load, path]);
    useEffect(() => {
        if (
            update.state !== 'idle' ||
            !update.data ||
            handled.current === update.data
        )
            return;
        handled.current = update.data;
        setError(update.data.error);
        setOptimistic(undefined);
        // Successful actions already revalidate the policy through the router.
        // Only errors need an explicit refresh; never retry a stale removal.
        if (update.data.error) void load(path);
    }, [update.state, update.data, load, path]);
    const state = policy.data?.state;
    const ready = state?.id === credentialId;
    const busy = update.state !== 'idle' || policy.state !== 'idle';
    const all = state?.approval_operations?.includes('*') ?? false;
    const toggle = (key: string) => {
        if (!ready || !state.can_edit || all || busy || !policy.data?.csrfToken)
            return;
        const operations = new Set(state.approval_operations);
        operations.has(key) ? operations.delete(key) : operations.add(key);
        setError(undefined);
        setPendingKey(key);
        setOptimistic({ key, locked: operations.has(key) });
        void update.submit(
            {
                csrf_token: policy.data.csrfToken,
                payload: JSON.stringify({
                    operations: [...operations],
                    expected_revision: state.revision,
                }),
            },
            { method: 'post', action: path }
        );
    };
    const header =
        hideSummary && ids.length <= 1 && !error && !state?.detail ? null : (
            <div className="space-y-1.5 px-2 text-xs text-muted-foreground">
                {(!hideSummary || ids.length > 1) && (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                        {!hideSummary && (
                            <span className="font-medium text-foreground">
                                Approval rules
                            </span>
                        )}
                        {ids.length > 1 ? (
                            <Select
                                value={credentialId}
                                onValueChange={onSelect}
                                disabled={busy}
                            >
                                <SelectTrigger
                                    aria-label="Connection for approval rules"
                                    className="h-8 w-auto min-w-40 gap-3 border-0 bg-foreground/[0.04] text-xs"
                                >
                                    <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                    {ids.map((id, index) => (
                                        <SelectItem key={id} value={id}>
                                            {id === credentialId && ready
                                                ? state.name
                                                : `Connection ${index + 1}`}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        ) : (
                            <span>
                                {ready ? state.name : 'Loading connection…'}
                            </span>
                        )}
                        {!hideSummary && (
                            <>
                                <span
                                    role="status"
                                    className="ml-auto h-4 w-16 shrink-0 text-right"
                                >
                                    {busy
                                        ? pendingKey
                                            ? 'Saving…'
                                            : 'Loading…'
                                        : ''}
                                </span>
                                <Link
                                    to={path}
                                    className="rounded px-1.5 py-1 hover:bg-foreground/[0.05] hover:text-foreground"
                                >
                                    Manage rules
                                </Link>
                            </>
                        )}
                    </div>
                )}
                {!hideSummary && (
                    <>
                        <p>
                            Locks require approval. Changes apply everywhere
                            this connection is used.
                        </p>
                        {ready && !state.can_edit && (
                            <p>The connection owner manages these rules.</p>
                        )}
                        {ready && all && (
                            <p>
                                All tools are locked, including future tools.
                                Use Manage rules to change this policy.
                            </p>
                        )}
                    </>
                )}
                {(error || state?.detail) && (
                    <p role="alert" className="text-destructive">
                        {error || state?.detail}
                    </p>
                )}
            </div>
        );
    return (
        <TooltipProvider delayDuration={350}>
            {children({
                header,
                lock: (operation, name) => {
                    if (!ready) return null;
                    const entry = state.operations.find(
                        (item) =>
                            item.node_type === nodeType &&
                            (item.operation ?? item.key.split('.').at(-1)) ===
                                operation
                    );
                    if (!entry) return null;
                    return (
                        <CredentialRuleLock
                            iconOnly
                            name={name}
                            locked={
                                optimistic?.key === entry.key
                                    ? optimistic.locked
                                    : all ||
                                      state.approval_operations.includes(
                                          entry.key
                                      )
                            }
                            disabled={!state.can_edit || all}
                            busy={busy}
                            saving={busy && pendingKey === entry.key}
                            onChange={() => toggle(entry.key)}
                        />
                    );
                },
            })}
        </TooltipProvider>
    );
}
