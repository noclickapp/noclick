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
    Users,
    Building2,
    Trash2,
    Loader2,
    Check,
    ChevronDown,
    Clock,
    AlertCircle,
    Globe,
    Link,
    Copy,
} from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '~/components/ui/dialog';
import { Button } from '~/components/ui/button';
import { Switch } from '~/components/ui/switch';
import { Input } from '~/components/ui/input';
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
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className="bg-sunken border-border text-foreground max-w-md p-6">
                <DialogHeader className="pb-4">
                    <DialogTitle className="text-xl text-foreground flex items-center gap-2">
                        <Share2 className="h-5 w-5" />
                        Share {{ workflow: 'Workflow', workflow_folder: 'Folder', database: 'Database', credential: 'Credential', saved_output: 'Saved Output', skill: 'Skill' }[resourceType]}
                    </DialogTitle>
                    <div className="text-sm text-muted-foreground pt-1.5">
                        {resource?.name || 'Resource'}
                    </div>
                </DialogHeader>

                <div className="space-y-6">
                    {/* Error display */}
                    {error && (
                        <div className="flex items-center gap-2 p-3 bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-900/50 rounded-lg text-red-600 dark:text-red-400 text-sm">
                            <AlertCircle className="h-4 w-4 flex-shrink-0" />
                            <span>{error}</span>
                        </div>
                    )}

                    {/* Public link sharing (workflows only) */}
                    {resourceType === 'workflow' && (
                        <div className="space-y-3">
                            <div className="flex items-center justify-between p-3 rounded-lg bg-card/50 border border-border">
                                <div className="flex items-center gap-3">
                                    <div className="w-8 h-8 rounded-full bg-blue-600/20 flex items-center justify-center">
                                        <Globe className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                                    </div>
                                    <div>
                                        <div className="text-sm font-medium text-foreground">
                                            Public access
                                        </div>
                                        <div className="text-xs text-muted-foreground dark:text-zinc-500">
                                            Anyone with the link can view
                                        </div>
                                    </div>
                                </div>
                                <Switch
                                    checked={isPublic}
                                    onCheckedChange={handlePublicToggle}
                                    disabled={togglingPublic}
                                />
                            </div>

                            {/* Public URL display when enabled */}
                            {isPublic && publicUrl && (
                                <div className="flex items-center gap-2">
                                    <div className="flex-1 relative">
                                        <Input
                                            value={publicUrl}
                                            readOnly
                                            className="pr-10 bg-card border-input dark:border-zinc-700 text-foreground/80 text-sm"
                                        />
                                        <Link className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground dark:text-zinc-500" />
                                    </div>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={handleCopyUrl}
                                        className="bg-secondary border-border dark:border-zinc-700 hover:bg-accent dark:hover:bg-zinc-700 hover:border-muted-foreground/40"
                                    >
                                        {copied ? (
                                            <Check className="h-4 w-4 text-green-600 dark:text-green-400" />
                                        ) : (
                                            <Copy className="h-4 w-4" />
                                        )}
                                    </Button>
                                </div>
                            )}

                        </div>
                    )}

                    {/* Divider between public and restricted sharing */}
                    {resourceType === 'workflow' && (
                        <div className="flex items-center gap-3">
                            <div className="flex-1 border-t border-border" />
                            <span className="text-xs text-muted-foreground dark:text-zinc-500">or share with specific people</span>
                            <div className="flex-1 border-t border-border" />
                        </div>
                    )}

                    {/* Unified recipient input with autocomplete */}
                    <ShareRecipientInput
                        suggestions={suggestions}
                        loading={loadingSuggestions}
                        permission={permission}
                        onPermissionChange={setPermission}
                        onSelect={handleSelectRecipient}
                        onSubmit={handleEmailSubmit}
                        submitting={sharing}
                        placeholder="Add people or organizations..."
                        hidePermission={hidePermission}
                    />

                    {/* Current shares list */}
                    <div className="space-y-3 pt-2 border-t border-border">
                        <div className="flex items-center gap-2">
                            <Users className="h-4 w-4 text-muted-foreground" />
                            <span className="text-sm font-medium text-foreground/80">
                                People with access
                            </span>
                        </div>

                        {loading ? (
                            <div className="flex items-center justify-center py-6">
                                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground dark:text-zinc-500" />
                            </div>
                        ) : shares.length === 0 ? (
                            <div className="text-sm text-muted-foreground dark:text-zinc-500 py-4 text-center">
                                No one else has access yet
                            </div>
                        ) : (
                            <div className="space-y-2 max-h-[200px] overflow-y-auto">
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
                </div>

                {/* Footer */}
                <div className="flex justify-end pt-4">
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                        className="h-10 bg-transparent text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] border border-border hover:border-muted-foreground/40 dark:hover:border-zinc-700 rounded-md"
                    >
                        Done
                    </Button>
                </div>
            </DialogContent>
        </Dialog>

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

    // Render avatar/icon based on type and available data
    const renderAvatar = () => {
        if (share.target_type === 'organization') {
            // Organization: show icon_url or fallback to Building2 icon
            if (share.target_org_icon_url) {
                return (
                    <img
                        src={share.target_org_icon_url}
                        alt=""
                        className="w-8 h-8 rounded-full object-cover"
                    />
                );
            }
            return (
                <div className="w-8 h-8 rounded-full bg-blue-600/20 flex items-center justify-center">
                    <Building2 className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                </div>
            );
        }

        // User: pending invites show Clock, existing users show avatar or initials
        if (share.is_pending) {
            return (
                <div className="w-8 h-8 rounded-full bg-amber-600/20 flex items-center justify-center">
                    <Clock className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                </div>
            );
        }

        // Existing user: show avatar_url or initials
        if (share.target_avatar_url) {
            return (
                <img
                    src={share.target_avatar_url}
                    alt=""
                    className="w-8 h-8 rounded-full object-cover"
                    referrerPolicy="no-referrer"
                />
            );
        }

        // Fallback: show initials
        return (
            <div className="w-8 h-8 rounded-full bg-secondary flex items-center justify-center text-xs font-medium text-foreground/80">
                {getInitials(displayName)}
            </div>
        );
    };

    return (
        <div className="flex items-center justify-between p-2.5 bg-card/50 rounded-lg border border-border/50 dark:border-zinc-800/50 group">
            <div className="flex items-center gap-3 min-w-0 flex-1">
                {renderAvatar()}
                <div className="min-w-0 flex-1">
                    <div className="text-sm text-foreground truncate">{displayName}</div>
                    {share.is_pending && (
                        <div className="text-xs text-amber-500">Pending invite</div>
                    )}
                    {share.target_type === 'organization' && (
                        <div className="text-xs text-muted-foreground dark:text-zinc-500">All members</div>
                    )}
                </div>
            </div>

            <div className="flex items-center gap-1.5">
                {/* Permission dropdown (hidden for credentials/saved outputs and public shares) */}
                {!hidePermission && share.target_type !== 'public' && (
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <Button
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground hover:bg-accent"
                            >
                                <span className="capitalize">{share.permission}</span>
                                <ChevronDown className="h-3 w-3 ml-1 opacity-60" />
                            </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                            align="end"
                            className="bg-card border-border"
                        >
                            <DropdownMenuItem
                                onClick={() => onUpdatePermission(share.id, 'view')}
                                className="text-foreground/80 focus:text-foreground focus:bg-accent"
                            >
                                <span className="flex items-center justify-between w-full">
                                    Can view
                                    {share.permission === 'view' && (
                                        <Check className="h-4 w-4 ml-2" />
                                    )}
                                </span>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                                onClick={() => onUpdatePermission(share.id, 'edit')}
                                className="text-foreground/80 focus:text-foreground focus:bg-accent"
                            >
                                <span className="flex items-center justify-between w-full">
                                    Can edit
                                    {share.permission === 'edit' && (
                                        <Check className="h-4 w-4 ml-2" />
                                    )}
                                </span>
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
                {/* Show static "View" label for public shares */}
                {share.target_type === 'public' && (
                    <span className="h-7 px-2 text-xs text-muted-foreground dark:text-zinc-500 flex items-center">
                        View only
                    </span>
                )}

                {/* Remove button */}
                <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onRemove(share.id)}
                    className="h-7 w-7 p-0 text-muted-foreground dark:text-zinc-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/50"
                >
                    <Trash2 className="h-3.5 w-3.5" />
                </Button>
            </div>
        </div>
    );
}
