/**
 * Credentials management component for the Settings page.
 * Shows Personal and Shared With Me tabs with colored service icons,
 * expandable rows with inline share management (add/remove recipients),
 * and sharer info for received credentials.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import {
    Share2,
    Trash2,
    Loader2,
    Search,
    Building2,
    Clock,
    Check,
    ChevronDown,
    User,
    Users,
    KeyRound,
    Plus,
} from 'lucide-react';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu';
import { sendEventAsync, sendEventWithCallback } from '~/lib/socket-sender';
import type {
    CredentialInfo,
    ShareInfo,
} from '~/types/socket-events.generated';
import {
    ShareDeleteRequest,
    ShareLeaveRequest,
    ShareUpdateRequest,
} from '~/types/socket-events.generated';
import { formatCredentialTypeLabel } from '~/utils/credentialTypes';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { DeleteConfirmPopup } from '~/components/shared/popups/DeleteConfirmPopup';
import {
    openCreateCredential,
    CREDENTIALS_CHANGED_EVENT,
} from '~/components/shared/popups/CreateCredentialDialog';
import { cn } from '~/lib/utils';
import { useOrgContext } from '~/hooks/useOrgContext';
import { toast } from 'sonner';

interface CredentialsSettingsProps {
    onNavigateBack?: () => void;
    embedded?: boolean;
}

type CredentialTab = 'organization' | 'personal' | 'shared';

function formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
    });
}

function getInitials(name: string): string {
    return name.slice(0, 2).toUpperCase();
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function CredentialsSettings({
    embedded,
    onNavigateBack,
}: CredentialsSettingsProps) {
    const [orgContext] = useOrgContext();
    const hasOrg = !!orgContext.id;

    const [credentials, setCredentials] = useState<CredentialInfo[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [credentialShares, setCredentialShares] = useState<
        Record<string, ShareInfo[]>
    >({});
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
    const [activeTab, setActiveTab] = useState<CredentialTab>(
        hasOrg ? 'organization' : 'personal'
    );

    const [shareCredential, setShareCredential] = useState<{
        id: string;
        name: string;
    } | null>(null);
    const [credentialToDelete, setCredentialToDelete] = useState<{
        id: string;
        name: string;
    } | null>(null);
    // Workflows referencing the credential pending deletion (dry-run result),
    // surfaced in the confirm dialog so the user knows what breaks.
    const [affectedWorkflows, setAffectedWorkflows] = useState<
        { workflow_id: string; workflow_name: string }[]
    >([]);

    const loadCredentials = useCallback(async () => {
        setLoading(true);
        try {
            const response = await sendEventAsync({
                event_name: 'credential:list',
                request_id: `cred-settings-list-${Date.now()}`,
            });

            const creds: CredentialInfo[] = response?.credentials ?? [];
            setCredentials(creds);

            // Load shares for owned credentials in parallel (only owners can list shares)
            const ownedCreds = creds.filter((c) => c.access_type === 'owner');
            const shareResults = await Promise.all(
                ownedCreds.map(async (cred) => {
                    try {
                        const shareResponse = await sendEventAsync({
                            event_name: 'share:list',
                            request_id: `share-list-${cred.id}-${Date.now()}`,
                            resource_type: 'credential',
                            resource_id: cred.id,
                        });
                        return {
                            id: cred.id,
                            shares: (shareResponse?.shares ??
                                []) as ShareInfo[],
                        };
                    } catch {
                        return { id: cred.id, shares: [] as ShareInfo[] };
                    }
                })
            );

            const sharesMap: Record<string, ShareInfo[]> = {};
            for (const r of shareResults) sharesMap[r.id] = r.shares;
            setCredentialShares(sharesMap);
        } catch (err) {
            console.error(
                '[CredentialsSettings] Error loading credentials:',
                err
            );
            toast.error('Failed to load credentials');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadCredentials();
    }, [loadCredentials]);

    // Refresh when a credential is created from the global create-credential dialog
    // (opened via this page's "New credential" button or the command palette).
    useEffect(() => {
        const onChanged = () => loadCredentials();
        window.addEventListener(CREDENTIALS_CHANGED_EVENT, onChanged);
        return () =>
            window.removeEventListener(CREDENTIALS_CHANGED_EVENT, onChanged);
    }, [loadCredentials]);

    // Dry-run the delete when the confirm dialog opens: the backend returns
    // the workflows still referencing this credential without deleting.
    useEffect(() => {
        if (!credentialToDelete) {
            setAffectedWorkflows([]);
            return;
        }
        let cancelled = false;
        sendEventAsync({
            event_name: 'credential:delete',
            request_id: `delete-cred-dryrun-${Date.now()}`,
            credential_id: credentialToDelete.id,
            confirm: false,
        })
            .then((response) => {
                if (!cancelled && response?.success) {
                    setAffectedWorkflows(response.affected_workflows ?? []);
                }
            })
            .catch(() => {
                // Non-fatal: the dialog just shows the generic warning.
            });
        return () => {
            cancelled = true;
        };
    }, [credentialToDelete]);

    const handleDelete = useCallback(async () => {
        if (!credentialToDelete) return;
        try {
            const response = await sendEventAsync({
                event_name: 'credential:delete',
                request_id: `delete-cred-${Date.now()}`,
                credential_id: credentialToDelete.id,
                confirm: true,
            });
            if (response?.success) {
                invalidateCredentialsCache();
                toast.success('Credential deleted');
                loadCredentials();
            } else {
                // The reason rides `error`; `message` is only set on success.
                toast.error(response?.error || 'Failed to delete credential');
            }
        } catch (err) {
            console.error(
                '[CredentialsSettings] Error deleting credential:',
                err
            );
            toast.error('Failed to delete credential');
        } finally {
            setCredentialToDelete(null);
        }
    }, [credentialToDelete, loadCredentials]);

    const handleRemoveShare = useCallback(
        (credentialId: string, shareId: string) => {
            sendEventWithCallback(
                ShareDeleteRequest.create({ share_id: shareId }),
                (response) => {
                    if (response.error) {
                        toast.error('Failed to remove share');
                    } else {
                        setCredentialShares((prev) => ({
                            ...prev,
                            [credentialId]: (prev[credentialId] ?? []).filter(
                                (s) => s.id !== shareId
                            ),
                        }));
                        toast.success('Share removed');
                    }
                }
            );
        },
        []
    );

    const handleUpdatePermission = useCallback(
        (
            credentialId: string,
            shareId: string,
            newPermission: 'view' | 'edit'
        ) => {
            sendEventWithCallback(
                ShareUpdateRequest.create({
                    share_id: shareId,
                    permission: newPermission,
                }),
                (response) => {
                    if (response.error) {
                        toast.error('Failed to update permission');
                    } else {
                        setCredentialShares((prev) => ({
                            ...prev,
                            [credentialId]: (prev[credentialId] ?? []).map(
                                (s) =>
                                    s.id === shareId
                                        ? { ...s, permission: newPermission }
                                        : s
                            ),
                        }));
                    }
                }
            );
        },
        []
    );

    // share:leave, not share:delete — dropping your OWN access needs no
    // manage-shares permission, which a share recipient never has.
    const handleUnshare = useCallback((credentialId: string) => {
        sendEventWithCallback(
            ShareLeaveRequest.create({
                resource_type: 'credential',
                resource_id: credentialId,
            }),
            (response) => {
                if (response.error) {
                    toast.error(response.error);
                    return;
                }
                if (!response.removed) {
                    toast.error(
                        'Access comes from an organization share — ask the owner to remove it.'
                    );
                    return;
                }
                setCredentials((prev) =>
                    prev.filter((c) => c.id !== credentialId)
                );
                invalidateCredentialsCache();
                toast.success('Credential removed');
            }
        );
    }, []);

    const personalCredentials = useMemo(
        () => credentials.filter((c) => c.access_type === 'owner'),
        [credentials]
    );
    const orgCredentials = useMemo(
        () =>
            credentials.filter(
                (c) =>
                    c.access_type === 'shared_org' ||
                    c.shared_with_org ||
                    (orgContext.id && c.organization_id === orgContext.id)
            ),
        [credentials, orgContext.id]
    );
    const sharedCredentials = useMemo(
        () => credentials.filter((c) => c.access_type === 'shared'),
        [credentials]
    );

    const currentList =
        activeTab === 'organization'
            ? orgCredentials
            : activeTab === 'personal'
              ? personalCredentials
              : sharedCredentials;

    const filteredCredentials = useMemo(
        () =>
            fuzzyFilter(currentList, searchQuery, (cred) => [
                { text: cred.name.toLowerCase(), weight: 1, fuzzy: true },
                {
                    text: formatCredentialTypeLabel(
                        cred.credential_type
                    ).toLowerCase(),
                    weight: 0.6,
                    fuzzy: true,
                },
            ]),
        [currentList, searchQuery]
    );

    useEffect(() => {
        setExpandedIds(new Set());
    }, [activeTab]);

    return (
        <div>
            {/* Header */}
            <div className="flex items-center justify-between gap-3 mb-6">
                <div className="flex items-center gap-3">
                    <h2 className="text-lg font-semibold text-foreground tracking-tight">
                        Credentials
                    </h2>
                    {!loading && credentials.length > 0 && (
                        <span className="text-xs text-muted-foreground dark:text-white/40 bg-foreground/[0.06] px-2 py-0.5 rounded-full">
                            {credentials.length}
                        </span>
                    )}
                </div>
                <button
                    onClick={() => openCreateCredential()}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-foreground bg-card dark:bg-foreground/[0.08] hover:bg-muted dark:hover:bg-foreground/[0.12] border border-border dark:border-white/[0.08] rounded-lg transition-colors"
                >
                    <Plus className="w-4 h-4" />
                    New credential
                </button>
            </div>

            {/* Tabs */}
            {!loading && credentials.length > 0 && (
                <div className="flex gap-1 mb-4">
                    {hasOrg && (
                        <button
                            onClick={() => setActiveTab('organization')}
                            className={cn(
                                'flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors',
                                activeTab === 'organization'
                                    ? 'bg-foreground/[0.08] text-accent-foreground dark:text-white/90'
                                    : 'text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:bg-foreground/[0.04]'
                            )}
                        >
                            <Building2 className="w-3.5 h-3.5" />
                            Organization
                            {orgCredentials.length > 0 && (
                                <span className="text-xs text-muted-foreground/70 dark:text-white/30">
                                    {orgCredentials.length}
                                </span>
                            )}
                        </button>
                    )}
                    <button
                        onClick={() => setActiveTab('personal')}
                        className={cn(
                            'flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors',
                            activeTab === 'personal'
                                ? 'bg-foreground/[0.08] text-accent-foreground dark:text-white/90'
                                : 'text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:bg-foreground/[0.04]'
                        )}
                    >
                        <User className="w-3.5 h-3.5" />
                        Personal
                        {personalCredentials.length > 0 && (
                            <span className="text-xs text-muted-foreground/70 dark:text-white/30">
                                {personalCredentials.length}
                            </span>
                        )}
                    </button>
                    <button
                        onClick={() => setActiveTab('shared')}
                        className={cn(
                            'flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors',
                            activeTab === 'shared'
                                ? 'bg-foreground/[0.08] text-accent-foreground dark:text-white/90'
                                : 'text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:bg-foreground/[0.04]'
                        )}
                    >
                        <Users className="w-3.5 h-3.5" />
                        Shared With Me
                        {sharedCredentials.length > 0 && (
                            <span className="text-xs text-muted-foreground/70 dark:text-white/30">
                                {sharedCredentials.length}
                            </span>
                        )}
                    </button>
                </div>
            )}

            {/* Search */}
            {!loading && currentList.length > 0 && (
                <div className="relative mb-4">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/70 dark:text-white/30" />
                    <input
                        type="text"
                        placeholder="Search credentials..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full pl-9 pr-3 py-2 text-sm bg-foreground/[0.04] border border-input dark:border-white/[0.08] rounded-lg text-foreground placeholder:text-[hsl(var(--placeholder))] outline-none focus:border-muted-foreground/40 dark:focus:border-white/[0.15] transition-colors"
                    />
                </div>
            )}

            {/* Loading */}
            {loading && (
                <div className="flex items-center justify-center py-16">
                    <Loader2 className="w-5 h-5 text-muted-foreground dark:text-white/40 animate-spin" />
                </div>
            )}

            {/* Empty state — no credentials at all */}
            {!loading && credentials.length === 0 && (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                    <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-foreground/[0.04] mb-3">
                        <KeyRound className="w-6 h-6 text-muted-foreground/70 dark:text-white/30" />
                    </div>
                    <p className="text-sm text-muted-foreground dark:text-white/50">
                        No credentials yet
                    </p>
                    <p className="text-xs text-muted-foreground/70 dark:text-white/30 mt-1">
                        Connect a service to use across your workflows.
                    </p>
                    <button
                        onClick={() => openCreateCredential()}
                        className="mt-4 flex items-center gap-1.5 px-3 py-1.5 text-sm text-foreground bg-foreground/[0.08] hover:bg-foreground/[0.12] border border-border dark:border-white/[0.08] rounded-lg transition-colors"
                    >
                        <Plus className="w-4 h-4" />
                        New credential
                    </button>
                </div>
            )}

            {/* Empty state — current tab empty */}
            {!loading && credentials.length > 0 && currentList.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                    <p className="text-sm text-muted-foreground dark:text-white/40">
                        {activeTab === 'organization'
                            ? 'No credentials shared with this organization'
                            : activeTab === 'personal'
                              ? 'No personal credentials'
                              : 'No credentials have been shared with you'}
                    </p>
                </div>
            )}

            {/* Credential list */}
            {!loading && filteredCredentials.length > 0 && (
                <div className="space-y-1">
                    {filteredCredentials.map((cred) => {
                        const shares = credentialShares[cred.id] ?? [];
                        const isExpanded = expandedIds.has(cred.id);
                        const isOwner = cred.access_type === 'owner';
                        const isSharedWithMe = !isOwner;
                        return (
                            <CredentialRow
                                key={cred.id}
                                credential={cred}
                                shares={shares}
                                isExpanded={isExpanded}
                                onToggleExpand={() =>
                                    setExpandedIds((prev) => {
                                        const next = new Set(prev);
                                        if (next.has(cred.id))
                                            next.delete(cred.id);
                                        else next.add(cred.id);
                                        return next;
                                    })
                                }
                                onShare={
                                    isOwner
                                        ? () =>
                                              setShareCredential({
                                                  id: cred.id,
                                                  name: cred.name,
                                              })
                                        : undefined
                                }
                                onDelete={
                                    isOwner
                                        ? () =>
                                              setCredentialToDelete({
                                                  id: cred.id,
                                                  name: cred.name,
                                              })
                                        : undefined
                                }
                                onRemoveShare={
                                    isOwner
                                        ? (shareId) =>
                                              handleRemoveShare(
                                                  cred.id,
                                                  shareId
                                              )
                                        : undefined
                                }
                                onUpdatePermission={
                                    isOwner
                                        ? (shareId, perm) =>
                                              handleUpdatePermission(
                                                  cred.id,
                                                  shareId,
                                                  perm
                                              )
                                        : undefined
                                }
                                onUnshare={
                                    isSharedWithMe && cred.share_id
                                        ? () => handleUnshare(cred.id)
                                        : undefined
                                }
                            />
                        );
                    })}
                </div>
            )}

            {/* No search results */}
            {!loading &&
                currentList.length > 0 &&
                filteredCredentials.length === 0 &&
                searchQuery && (
                    <div className="flex flex-col items-center justify-center py-12 text-center">
                        <p className="text-sm text-muted-foreground dark:text-white/40">
                            No credentials matching &ldquo;{searchQuery}&rdquo;
                        </p>
                    </div>
                )}

            {/* Delete confirmation */}
            <DeleteConfirmPopup
                itemType="Credential"
                itemName={credentialToDelete?.name}
                isOpen={!!credentialToDelete}
                onOpenChange={(open) => {
                    if (!open) setCredentialToDelete(null);
                }}
                onConfirmDelete={handleDelete}
                customMessage={
                    affectedWorkflows.length > 0
                        ? `"${credentialToDelete?.name}" is used by ${affectedWorkflows.length} workflow${affectedWorkflows.length === 1 ? '' : 's'}: ${affectedWorkflows
                              .slice(0, 5)
                              .map((w) => w.workflow_name)
                              .join(
                                  ', '
                              )}${affectedWorkflows.length > 5 ? ', …' : ''}. Deleting it will deactivate their triggers and break those nodes until you connect a new credential.`
                        : undefined
                }
            />

            {/* Share dialog */}
            <ShareDialog
                isOpen={!!shareCredential}
                onOpenChange={(open) => {
                    if (!open) {
                        setShareCredential(null);
                        loadCredentials();
                    }
                }}
                resource={shareCredential}
                resourceType="credential"
            />
        </div>
    );
}

// ---------------------------------------------------------------------------
// Credential row
// ---------------------------------------------------------------------------

/** "F29_user_revoked" → "disconnected"; other auto-revoke codes keep their
 *  prose with the incident prefix stripped. */
function revokedReasonLabel(reason?: string | null): string | null {
    if (!reason) return null;
    const cleaned = reason.replace(/^F\d+_/, '').replace(/_/g, ' ');
    return cleaned === 'user revoked' ? 'disconnected' : cleaned;
}

function CredentialRow({
    credential,
    shares,
    isExpanded,
    onToggleExpand,
    onShare,
    onDelete,
    onRemoveShare,
    onUpdatePermission,
    onUnshare,
}: {
    credential: CredentialInfo;
    shares: ShareInfo[];
    isExpanded: boolean;
    onToggleExpand: () => void;
    onShare?: () => void;
    onDelete?: () => void;
    onRemoveShare?: (shareId: string) => void;
    onUpdatePermission?: (shareId: string, permission: 'view' | 'edit') => void;
    onUnshare?: () => void;
}) {
    const { Icon, iconColor, hasServiceIcon } = getCredentialIcon(
        credential.credential_type,
        credential.metadata
    );
    const isShared = credential.access_type !== 'owner';
    const hasShares = shares.length > 0;
    const isExpandable = !isShared && hasShares;
    const isRevoked = !!credential.revoked_at;
    const metadataEmail =
        typeof credential.metadata?.email === 'string'
            ? credential.metadata.email
            : null;

    const sharerName =
        credential.shared_by_name || credential.shared_by_email || '?';

    return (
        <div
            className={cn(
                'rounded-lg bg-card dark:bg-foreground/[0.03] border border-border dark:border-white/[0.06] overflow-hidden',
                isExpandable && 'border-l-2 border-l-border'
            )}
        >
            {/* Main row */}
            {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions */}
            <div
                className={cn(
                    'flex items-center px-3 py-2.5 transition-colors',
                    isExpandable &&
                        'hover:bg-muted dark:hover:bg-foreground/[0.03] cursor-pointer'
                )}
                onClick={isExpandable ? onToggleExpand : undefined}
            >
                {/* Service icon on a dark well. Use the node's brand color when known;
            otherwise fall back to foreground for service marks (currentColor brands
            like GitHub/X stay visible) and dimmed for the generic key. */}
                <div
                    className={cn(
                        'flex items-center justify-center w-11 h-11 rounded-lg bg-foreground/[0.06] flex-shrink-0 mr-3',
                        isRevoked && 'opacity-50'
                    )}
                >
                    <BrandIcon
                        Icon={Icon}
                        iconColor={
                            iconColor ||
                            (hasServiceIcon
                                ? 'text-foreground'
                                : 'text-muted-foreground dark:text-white/50')
                        }
                        className="w-7 h-7"
                    />
                </div>

                {/* Info */}
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                        <p
                            className={cn(
                                'text-[0.9375rem] font-medium truncate',
                                isRevoked
                                    ? 'text-muted-foreground'
                                    : 'text-foreground'
                            )}
                        >
                            {credential.name}
                        </p>
                        {isRevoked && (
                            <span
                                data-testid="credential-revoked-badge"
                                title="This credential was disconnected or revoked and can no longer be used by workflows — reconnect the account to revive it"
                                className="flex-shrink-0 rounded-full border border-red-200 dark:border-red-900/40 bg-red-50 dark:bg-red-950/30 px-1.5 py-px text-[10px] font-medium text-red-600 dark:text-red-400"
                            >
                                Revoked
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-1.5 mt-1 text-[0.8125rem] text-muted-foreground">
                        <span>
                            {formatCredentialTypeLabel(
                                credential.credential_type
                            )}
                        </span>
                        {metadataEmail && metadataEmail !== credential.name && (
                                <>
                                    <span>/</span>
                                    <span>{metadataEmail}</span>
                                </>
                            )}
                        <span>/</span>
                        <span>{formatDate(credential.created_at)}</span>
                        {!isShared && hasShares && (
                            <>
                                <span>/</span>
                                <span>
                                    {shares.length}{' '}
                                    {shares.length === 1 ? 'share' : 'shares'}
                                </span>
                            </>
                        )}
                        {isRevoked && (
                            <>
                                <span>/</span>
                                <span className="text-red-600 dark:text-red-400">
                                    revoked{' '}
                                    {formatDate(credential.revoked_at!)}
                                    {revokedReasonLabel(
                                        credential.revoked_reason
                                    )
                                        ? ` (${revokedReasonLabel(credential.revoked_reason)})`
                                        : ''}{' '}
                                    — reconnect to use again
                                </span>
                            </>
                        )}
                    </div>
                </div>

                {/* Sharer info inline for shared credentials */}
                {isShared && (
                    <div className="flex items-center gap-2.5 flex-shrink-0 ml-3">
                        <div className="w-7 h-7 rounded-full bg-foreground/[0.08] flex items-center justify-center flex-shrink-0">
                            <span className="text-[0.625rem] font-medium text-muted-foreground dark:text-white/50">
                                {getInitials(sharerName)}
                            </span>
                        </div>
                        <div className="min-w-0">
                            {credential.shared_by_name && (
                                <p className="text-xs text-muted-foreground dark:text-white/60">
                                    {credential.shared_by_name}
                                </p>
                            )}
                            {credential.shared_by_email && (
                                <p className="text-[0.6875rem] text-muted-foreground/70 dark:text-white/30">
                                    {credential.shared_by_email}
                                </p>
                            )}
                        </div>
                    </div>
                )}

                {/* Action buttons */}
                {(onShare || onDelete || onUnshare) && (
                    // eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-static-element-interactions
                    <div
                        className="flex items-center gap-1 flex-shrink-0 ml-2"
                        onClick={(e) => e.stopPropagation()}
                    >
                        {onShare && (
                            <button
                                onClick={onShare}
                                className="flex items-center justify-center h-8 w-8 rounded-md text-muted-foreground dark:text-white/40 hover:text-foreground/80 hover:bg-foreground/[0.06] transition-colors"
                            >
                                <Share2 className="w-4 h-4" />
                            </button>
                        )}
                        {onDelete && (
                            <button
                                onClick={onDelete}
                                className="flex items-center justify-center h-8 w-8 rounded-md text-muted-foreground dark:text-white/40 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-500/15 transition-colors"
                            >
                                <Trash2 className="w-4 h-4" />
                            </button>
                        )}
                        {onUnshare && (
                            <button
                                onClick={onUnshare}
                                className="flex items-center justify-center h-8 w-8 rounded-md text-muted-foreground dark:text-white/40 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-500/15 transition-colors"
                            >
                                <Trash2 className="w-4 h-4" />
                            </button>
                        )}
                    </div>
                )}
            </div>

            {/* Expanded section — share recipients (owned credentials only) */}
            {isExpanded && !isShared && hasShares && (
                <div className="border-t border-border dark:border-white/[0.06] px-4 py-3">
                    <p className="text-[0.6875rem] font-medium text-muted-foreground/70 dark:text-white/30 uppercase tracking-wider mb-2">
                        Shared with
                    </p>
                    <div className="space-y-1">
                        {shares.map((share) => (
                            <ShareRecipientRow
                                key={share.id}
                                share={share}
                                onRemove={
                                    onRemoveShare
                                        ? () => onRemoveShare(share.id)
                                        : undefined
                                }
                                onUpdatePermission={
                                    onUpdatePermission
                                        ? (perm) =>
                                              onUpdatePermission(share.id, perm)
                                        : undefined
                                }
                            />
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Share recipient row
// ---------------------------------------------------------------------------

function ShareRecipientRow({
    share,
    onRemove,
    onUpdatePermission,
}: {
    share: ShareInfo;
    onRemove?: () => void;
    onUpdatePermission?: (permission: 'view' | 'edit') => void;
}) {
    const displayName =
        share.target_type === 'organization'
            ? share.target_org_name || 'Organization'
            : share.target_display_name || share.target_email || 'Unknown user';

    return (
        <div className="flex items-center gap-3 py-1.5">
            <ShareAvatar share={share} />
            <div className="min-w-0 flex-1">
                <p className="text-sm text-muted-foreground dark:text-white/70 truncate">
                    {displayName}
                </p>
                {share.target_type === 'organization' && (
                    <p className="text-xs text-muted-foreground/70 dark:text-white/30">
                        All members
                    </p>
                )}
                {share.is_pending && (
                    <p className="text-xs text-amber-600 dark:text-amber-400/70">
                        Pending invite
                    </p>
                )}
            </div>
            {onUpdatePermission ? (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <button className="flex items-center gap-1 text-[0.6875rem] text-muted-foreground dark:text-white/40 hover:text-foreground/80 bg-foreground/[0.04] hover:bg-foreground/[0.08] px-2 py-0.5 rounded flex-shrink-0 transition-colors">
                            {share.permission === 'edit'
                                ? 'Can edit'
                                : 'Can view'}
                            <ChevronDown className="w-3 h-3 opacity-60" />
                        </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                        align="end"
                        className="bg-card border-border min-w-[120px]"
                    >
                        <DropdownMenuItem
                            onClick={() => onUpdatePermission('view')}
                            className="text-foreground/80 focus:text-foreground focus:bg-accent text-xs"
                        >
                            <span className="flex items-center justify-between w-full">
                                Can view
                                {share.permission === 'view' && (
                                    <Check className="w-3.5 h-3.5 ml-2" />
                                )}
                            </span>
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            onClick={() => onUpdatePermission('edit')}
                            className="text-foreground/80 focus:text-foreground focus:bg-accent text-xs"
                        >
                            <span className="flex items-center justify-between w-full">
                                Can edit
                                {share.permission === 'edit' && (
                                    <Check className="w-3.5 h-3.5 ml-2" />
                                )}
                            </span>
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            ) : (
                <span className="text-[0.6875rem] text-muted-foreground/70 dark:text-white/30 bg-foreground/[0.04] px-2 py-0.5 rounded flex-shrink-0">
                    {share.permission === 'edit' ? 'Can edit' : 'Can view'}
                </span>
            )}
            {onRemove && (
                <button
                    onClick={onRemove}
                    className="flex items-center justify-center h-7 w-7 rounded-md text-muted-foreground dark:text-white/40 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-500/15 transition-colors flex-shrink-0"
                >
                    <Trash2 className="w-3.5 h-3.5" />
                </button>
            )}
        </div>
    );
}

function ShareAvatar({ share }: { share: ShareInfo }) {
    const cls = 'w-7 h-7 rounded-full flex-shrink-0';

    if (share.target_type === 'organization') {
        if (share.target_org_icon_url) {
            return (
                <img
                    src={share.target_org_icon_url}
                    alt=""
                    className={`${cls} object-cover`}
                />
            );
        }
        return (
            <div
                className={`${cls} bg-blue-600/20 flex items-center justify-center`}
            >
                <Building2 className="w-3.5 h-3.5 text-blue-600 dark:text-blue-400" />
            </div>
        );
    }

    if (share.is_pending) {
        return (
            <div
                className={`${cls} bg-amber-600/20 flex items-center justify-center`}
            >
                <Clock className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
            </div>
        );
    }

    if (share.target_avatar_url) {
        return (
            <img
                src={share.target_avatar_url}
                alt=""
                className={`${cls} object-cover`}
                referrerPolicy="no-referrer"
            />
        );
    }

    const name = share.target_display_name || share.target_email || '?';
    return (
        <div
            className={`${cls} bg-foreground/[0.08] flex items-center justify-center`}
        >
            <span className="text-[0.625rem] font-medium text-muted-foreground dark:text-white/50">
                {getInitials(name)}
            </span>
        </div>
    );
}
