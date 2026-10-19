/**
 * ShareDialog component for sharing workflows, workflow folders, databases, credentials, and saved outputs
 * with users and organizations. Provides a unified interface for managing resource sharing
 * permissions.
 *
 * This component handles sharing via email (direct or pending invites) and
 * organization-wide sharing with configurable permissions (view/edit).
 * Uses a unified autocomplete input that shows orgs, org members, and freeform email.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import {
    Share2,
    Building2,
    Trash2,
    Loader2,
    Check,
    ChevronDown,
    Clock,
    Link,
    Copy,
} from 'lucide-react';
import { ShellDialog } from '~/components/shell/ShellDialog';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';
import { Switch } from '~/components/ui/switch';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu';
import { cn } from '~/lib/utils';
import { sendEventWithCallback, sendEventAsync } from '~/lib/socket-sender';
import { useOrganization, type OrganizationMember } from '~/hooks/useOrganization';
import type { ShareInfo } from '~/types/socket-events.generated';
import {
    ShareCreateRequest,
    ShareListRequest,
    ShareUpdateRequest,
    ShareDeleteRequest,
} from '~/types/socket-events.generated';
import { ShareRecipientInput, type ShareSuggestion } from '~/components/shared/ShareRecipientInput';

interface ShareableResource {
    id: string;
    name: string;
}

interface UserOrg {
    id: string;
    name: string;
    slug: string;
    icon_url: string | null;
    role: 'owner' | 'admin' | 'member';
    is_primary: boolean;
}

interface ShareDialogProps {
    /** Whether the dialog is open */
    isOpen: boolean;
    /** Callback to handle dialog open/close state */
    onOpenChange: (open: boolean) => void;
    /** The resource being shared */
    resource: ShareableResource | null;
    /** Type of resource (workflow, workflow_folder, database, credential, saved_output, or skill) */
    resourceType: 'workflow' | 'workflow_folder' | 'database' | 'credential' | 'saved_output' | 'skill';
}

/** What each resource is called where people see it. */
const RESOURCE_NOUNS: Record<ShareDialogProps['resourceType'], string> = {
    workflow: 'automation',
    workflow_folder: 'folder',
    database: 'database',
    credential: 'account',
    saved_output: 'saved output',
    skill: 'skill',
};

export function ShareDialog({
    isOpen,
    onOpenChange,
    resource,
    resourceType,
}: ShareDialogProps) {
    const [permission, setPermission] = useState<'view' | 'edit'>('view');
    const [shares, setShares] = useState<ShareInfo[]>([]);
    const [loading, setLoading] = useState(false);
    const [sharing, setSharing] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [organizations, setOrganizations] = useState<UserOrg[]>([]);
    const [orgMembers, setOrgMembers] = useState<Map<string, OrganizationMember[]>>(new Map());
    const [loadingSuggestions, setLoadingSuggestions] = useState(false);
    const { listMyOrganizations, listMembers } = useOrganization();

    // Public sharing state (workflows only)
    const [isPublic, setIsPublic] = useState(false);
    const [publicUrl, setPublicUrl] = useState<string | null>(null);
    const [togglingPublic, setTogglingPublic] = useState(false);
    const [copied, setCopied] = useState(false);

    // Credentials and saved outputs don't have view/edit permissions - they're either accessible or not
    const hidePermission = resourceType === 'credential' || resourceType === 'saved_output';

    // Fetch user's organizations and their members when dialog opens
    useEffect(() => {
        if (isOpen) {
            setLoadingSuggestions(true);
            listMyOrganizations().then(async (orgs) => {
                if (orgs) {
                    setOrganizations(orgs);
                    // Fetch members for each org in parallel
                    const memberPromises = orgs.map(async (org) => {
                        const members = await listMembers(org.id);
                        return [org.id, members] as const;
                    });
                    const results = await Promise.all(memberPromises);
                    setOrgMembers(new Map(results));
                }
                setLoadingSuggestions(false);
            });
        }
    }, [isOpen, listMyOrganizations, listMembers]);

    // Load existing shares when dialog opens
    useEffect(() => {
        if (isOpen && resource) {
            setLoading(true);
            setError(null);
            sendEventWithCallback(
                ShareListRequest.create({
                    resource_type: resourceType,
                    resource_id: resource.id,
                }),
                (response) => {
                    setLoading(false);
                    if (response.error) {
                        setError(response.error);
                    } else {
                        const allShares = response.shares || [];
                        setShares(allShares);

                        // Check if there's a public share (for workflows)
                        if (resourceType === 'workflow') {
                            const publicShare = allShares.find(
                                (s: ShareInfo) => s.target_type === 'public'
                            );
                            if (publicShare) {
                                setIsPublic(true);
                                setPublicUrl(`${window.location.origin}/share/${resource.id}`);
                            } else {
                                setIsPublic(false);
                                setPublicUrl(null);
                            }
                        }
                    }
                }
            );
        } else {
            // Reset state when dialog closes
            setPermission('view');
            setShares([]);
            setError(null);
            setIsPublic(false);
            setPublicUrl(null);
            setCopied(false);
        }
    }, [isOpen, resource, resourceType]);

    // Handle toggling public visibility (workflows only)
    const handlePublicToggle = useCallback(async (checked: boolean) => {
        if (!resource || resourceType !== 'workflow') return;

        setTogglingPublic(true);
        setError(null);

        try {
            if (checked) {
                // Enable public sharing - use share:create with target_type='public'
                const response = await sendEventAsync(
                    ShareCreateRequest.create({
                        resource_type: resourceType,
                        resource_id: resource.id,
                        target_type: 'public',
                        permission: 'view',
                    })
                );

                if (response.error) {
                    setError(response.error);
                } else if (response.share) {
                    const newShare = response.share;
                    setIsPublic(true);
                    setPublicUrl(newShare.public_url || `${window.location.origin}/share/${resource.id}`);
                    // Add the new public share to the list
                    setShares((prev) => [newShare, ...prev.filter(s => s.target_type !== 'public')]);
                }
            } else {
                // Disable public sharing - find the public share and delete it
                const publicShare = shares.find(s => s.target_type === 'public');
                if (publicShare) {
                    const response = await sendEventAsync(
                        ShareDeleteRequest.create({
                            share_id: publicShare.id,
                        })
                    );

                    if (response.error) {
                        setError(response.error);
                    } else {
                        setIsPublic(false);
                        setPublicUrl(null);
                        setShares((prev) => prev.filter(s => s.target_type !== 'public'));
                    }
                } else {
                    // No public share found, just update state
                    setIsPublic(false);
                    setPublicUrl(null);
                }
            }
        } catch (err) {
            setError('Failed to update public visibility');
        } finally {
            setTogglingPublic(false);
        }
    }, [resource, resourceType, shares]);

    // Handle copying public URL
    const handleCopyUrl = useCallback(() => {
        if (publicUrl) {
            navigator.clipboard.writeText(publicUrl);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        }
    }, [publicUrl]);

    // Build suggestions from organizations and their members
    // Excludes orgs and users that are already shared with
    const suggestions = useMemo((): ShareSuggestion[] => {
        const result: ShareSuggestion[] = [];
        const sharedOrgIds = new Set(shares.filter(s => s.target_type === 'organization').map(s => s.target_org_id));
        const sharedEmails = new Set(shares.filter(s => s.target_type === 'user').map(s => s.target_email?.toLowerCase()));

        // Add organizations (that aren't already shared with)
        for (const org of organizations) {
            if (!sharedOrgIds.has(org.id)) {
                result.push({
                    type: 'organization',
                    id: org.id,
                    name: org.name,
                    subtitle: 'All members',
                    icon_url: org.icon_url ?? undefined,
                });
            }
        }

        // Add org members (that aren't already shared with)
        const seenEmails = new Set<string>();
        for (const [, members] of orgMembers) {
            for (const member of members) {
                // User shares are addressed by email; a phone-only member is reached via the org share.
                if (!member.email) continue;
                const email = member.email.toLowerCase();
                // Skip duplicates and already-shared users
                if (seenEmails.has(email) || sharedEmails.has(email)) continue;
                seenEmails.add(email);

                result.push({
                    type: 'user',
                    id: member.user_id,
                    email: member.email,
                    name: member.full_name || member.email,
                    subtitle: member.email,
                    icon_url: member.avatar_url ?? undefined,
                });
            }
        }

        return result;
    }, [organizations, orgMembers, shares]);

    // Handle selecting a recipient from suggestions (org or user)
    const handleSelectRecipient = useCallback((suggestion: ShareSuggestion) => {
        if (!resource) return;

        setSharing(true);
        setError(null);

        const request = suggestion.type === 'organization'
            ? ShareCreateRequest.create({
                resource_type: resourceType,
                resource_id: resource.id,
                target_type: 'organization',
                target_org_id: suggestion.id!,
                permission,
            })
            : ShareCreateRequest.create({
                resource_type: resourceType,
                resource_id: resource.id,
                target_type: 'user',
                target_email: suggestion.email!,
                permission,
            });

        sendEventWithCallback(request, (response) => {
            setSharing(false);
            if (response.error) {
                setError(response.error);
            } else if (response.share) {
                const newShare = response.share;
                setShares((prev) => [...prev, newShare]);
            }
        });
    }, [resource, resourceType, permission]);

    // Handle freeform email submission
    const handleEmailSubmit = useCallback((email: string) => {
        if (!resource) return;

        setSharing(true);
        setError(null);

        sendEventWithCallback(
            ShareCreateRequest.create({
                resource_type: resourceType,
                resource_id: resource.id,
                target_type: 'user',
                target_email: email,
                permission,
            }),
            (response) => {
                setSharing(false);
                if (response.error) {
                    setError(response.error);
                } else if (response.share) {
                    const newShare = response.share;
                    setShares((prev) => [...prev, newShare]);
                }
            }
        );
    }, [resource, resourceType, permission]);

    // Handle updating share permission
    const handleUpdatePermission = useCallback(
        (shareId: string, newPermission: 'view' | 'edit') => {
            sendEventWithCallback(
                ShareUpdateRequest.create({
                    share_id: shareId,
                    permission: newPermission,
                }),
                (response) => {
                    if (response.error) {
                        setError(response.error);
                    } else if (response.share) {
                        setShares((prev) =>
                            prev.map((s) =>
                                s.id === shareId ? { ...s, permission: newPermission } : s
                            )
                        );
                    }
                }
            );
        },
        []
    );

    // Handle removing a share
    const handleRemoveShare = useCallback((shareId: string) => {
        sendEventWithCallback(
            ShareDeleteRequest.create({
                share_id: shareId,
            }),
            (response) => {
                if (response.error) {
                    setError(response.error);
                } else {
                    setShares((prev) => prev.filter((s) => s.id !== shareId));
                }
            }
        );
    }, []);

    return (
        <>
            <ShellDialog
                open={isOpen}
                onOpenChange={onOpenChange}
                size="sm"
                title={`Share ${RESOURCE_NOUNS[resourceType]}`}
                description={<span className="block truncate">{resource?.name || 'Resource'}</span>}
                mark={<Share2 className="h-5 w-5" strokeWidth={1.75} />}
                footer={
                    <button type="button" onClick={() => onOpenChange(false)} className={BUTTON_PRIMARY}>
                        Done
                    </button>
                }
            >
                {error && (
                    <p role="alert" className="mb-3 text-[13px] text-red-600 dark:text-red-400">
                        {error}
                    </p>
                )}

                {/* Public link sharing (workflows only) */}
                {resourceType === 'workflow' && (
                    <div className="mb-4 border-b border-border pb-4 dark:border-foreground/[0.08]">
                        <div className="flex items-center justify-between gap-4">
                            <div className="min-w-0">
                                <div className="text-[14px] font-medium text-foreground">Public access</div>
                                <div className="mt-0.5 text-[12.5px] text-muted-foreground">Anyone with the link can view</div>
                            </div>
                            <Switch
                                checked={isPublic}
                                onCheckedChange={handlePublicToggle}
                                disabled={togglingPublic}
                                aria-label="Public access"
                            />
                        </div>

                        {isPublic && publicUrl && (
                            <div className="mt-3 flex items-center gap-2">
                                <div className="relative min-w-0 flex-1">
                                    <input value={publicUrl} readOnly aria-label="Public link" className={cn(FIELD, 'pr-10 text-foreground/80')} />
                                    <Link className="pointer-events-none absolute right-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                                </div>
                                <button type="button" onClick={handleCopyUrl} className={cn(BUTTON_SECONDARY, 'h-10 min-w-[6.25rem] justify-center')}>
                                    {copied ? (
                                        <>
                                            <Check className="h-4 w-4 text-green-600 dark:text-green-400" />
                                            Copied
                                        </>
                                    ) : (
                                        <>
                                            <Copy className="h-4 w-4" />
                                            Copy
                                        </>
                                    )}
                                </button>
                            </div>
                        )}
                    </div>
                )}

                {resourceType === 'workflow' && <div className={FIELD_LABEL}>Or share with specific people</div>}
                <ShareRecipientInput
                    suggestions={suggestions}
                    loading={loadingSuggestions}
                    permission={permission}
                    onPermissionChange={setPermission}
                    onSelect={handleSelectRecipient}
                    onSubmit={handleEmailSubmit}
                    submitting={sharing}
                    hidePermission={hidePermission}
                />

                {/* Current shares list */}
                <div className="mt-5">
                    <div className="mb-1.5 text-[13px] font-medium text-foreground/85">People with access</div>
                    {loading ? (
                        <div className="flex items-center justify-center py-6">
                            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                        </div>
                    ) : shares.length === 0 ? (
                        <div className="py-4 text-center text-[13px] text-muted-foreground">No one else has access yet</div>
                    ) : (
                        <div className="-mx-2 max-h-[200px] space-y-0.5 overflow-y-auto">
                            {shares.map((share) => (
                                <ShareItem
                                    key={share.id}
                                    share={share}
                                    onUpdatePermission={handleUpdatePermission}
                                    onRemove={handleRemoveShare}
                                    hidePermission={hidePermission}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </ShellDialog>
        </>
    );
}

/** Get initials from name or email */
function getInitials(name: string): string {
    // If it's an email, use the first two chars of the local part
    if (name.includes('@')) {
        return name.split('@')[0].slice(0, 2).toUpperCase();
    }
    // Otherwise use first two chars of name
    return name.slice(0, 2).toUpperCase();
}

const AVATAR_TILE = 'grid h-8 w-8 shrink-0 place-items-center bg-foreground/[0.06] text-muted-foreground';

/** Individual share item in the list */
function ShareItem({
    share,
    onUpdatePermission,
    onRemove,
    hidePermission = false,
}: {
    share: ShareInfo;
    onUpdatePermission: (shareId: string, permission: 'view' | 'edit') => void;
    onRemove: (shareId: string) => void;
    hidePermission?: boolean;
}) {
    // Determine display name
    const displayName =
        share.target_type === 'organization'
            ? share.target_org_name || 'Organization'
            : share.target_display_name ||
              share.target_email ||
              'Unknown user';

    // Render avatar/icon based on type and available data: organizations on a square tile, people on a round one
    const renderAvatar = () => {
        if (share.target_type === 'organization') {
            if (share.target_org_icon_url) {
                return <img src={share.target_org_icon_url} alt="" className="h-8 w-8 shrink-0 rounded-lg object-cover" />;
            }
            return (
                <div className={cn(AVATAR_TILE, 'rounded-lg')}>
                    <Building2 className="h-4 w-4" strokeWidth={1.75} />
                </div>
            );
        }

        // User: pending invites show Clock, existing users show avatar or initials
        if (share.is_pending) {
            return (
                <div className={cn(AVATAR_TILE, 'rounded-full')}>
                    <Clock className="h-4 w-4" strokeWidth={1.75} />
                </div>
            );
        }

        if (share.target_avatar_url) {
            return (
                <img
                    src={share.target_avatar_url}
                    alt=""
                    className="h-8 w-8 shrink-0 rounded-full object-cover"
                    referrerPolicy="no-referrer"
                />
            );
        }

        return <div className={cn(AVATAR_TILE, 'rounded-full text-[11px] font-medium text-foreground/80')}>{getInitials(displayName)}</div>;
    };

    return (
        <div className="group flex items-center justify-between gap-3 rounded-xl px-2 py-2 transition-colors hover:bg-foreground/[0.04]">
            <div className="flex min-w-0 flex-1 items-center gap-3">
                {renderAvatar()}
                <div className="min-w-0 flex-1">
                    <div className="truncate text-[13.5px] text-foreground">{displayName}</div>
                    {share.is_pending && <div className="text-[12px] text-amber-600 dark:text-amber-400">Pending invite</div>}
                    {share.target_type === 'organization' && <div className="text-[12px] text-muted-foreground">All members</div>}
                </div>
            </div>

            <div className="flex shrink-0 items-center gap-1">
                {/* Permission dropdown (hidden for credentials/saved outputs and public shares) */}
                {!hidePermission && share.target_type !== 'public' && (
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <button
                                type="button"
                                className="inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[12.5px] text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground"
                            >
                                <span className="capitalize">{share.permission}</span>
                                <ChevronDown className="h-3 w-3 opacity-60" />
                            </button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="rounded-xl">
                            <DropdownMenuItem
                                onClick={() => onUpdatePermission(share.id, 'view')}
                                className="text-foreground/80 focus:bg-accent focus:text-foreground"
                            >
                                <span className="flex w-full items-center justify-between">
                                    Can view
                                    {share.permission === 'view' && <Check className="ml-2 h-4 w-4" />}
                                </span>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                onClick={() => onUpdatePermission(share.id, 'edit')}
                                className="text-foreground/80 focus:bg-accent focus:text-foreground"
                            >
                                <span className="flex w-full items-center justify-between">
                                    Can edit
                                    {share.permission === 'edit' && <Check className="ml-2 h-4 w-4" />}
                                </span>
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
                {/* Show static "View" label for public shares */}
                {share.target_type === 'public' && (
                    <span className="flex h-7 items-center px-2.5 text-[12.5px] text-muted-foreground">View only</span>
                )}

                <button
                    type="button"
                    onClick={() => onRemove(share.id)}
                    aria-label={`Remove ${displayName}`}
                    className="grid h-7 w-7 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-red-500/10 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:hover:text-red-400"
                >
                    <Trash2 className="h-3.5 w-3.5" />
                </button>
            </div>
        </div>
    );
}
