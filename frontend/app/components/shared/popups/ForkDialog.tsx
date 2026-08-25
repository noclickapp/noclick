/**
 * ForkDialog component for creating independent copies of shared resources.
 * Allows users to fork workflows and databases to their personal workspace
 * or an organization they belong to.
 */

import { useState, useEffect } from 'react';
import {
    GitFork,
    User,
    Building2,
    Loader2,
    Database,
    Workflow,
    Copy,
} from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from '~/components/ui/dialog';
import { Button } from '~/components/ui/button';
import { cn } from '~/lib/utils';
import { sendEventAsync } from '~/lib/socket-sender';
import { useOrganization } from '~/hooks/useOrganization';
import { ResourceForkRequest } from '~/types/socket-events.generated';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { isPlanLimitError } from '~/lib/planLimitErrors';

interface ForkableResource {
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

interface ForkDialogProps {
    /** Whether the dialog is open */
    isOpen: boolean;
    /** Callback to handle dialog open/close state */
    onOpenChange: (open: boolean) => void;
    /** The resource being forked */
    resource: ForkableResource | null;
    /** Type of resource (workflow or database) */
    resourceType: 'workflow' | 'database';
    /** Callback when fork is successful */
    onForkSuccess?: (forkedResourceId: string, forkedResourceName: string) => void;
}

/** Get initials from organization name (up to 2 characters) */
function getOrgInitials(name: string): string {
    const words = name.trim().split(/\s+/);
    if (words.length >= 2) {
        return (words[0][0] + words[1][0]).toUpperCase();
    }
    return name.slice(0, 2).toUpperCase();
}

export function ForkDialog({
    isOpen,
    onOpenChange,
    resource,
    resourceType,
    onForkSuccess,
}: ForkDialogProps) {
    const [destinationType, setDestinationType] = useState<'personal' | 'organization'>('personal');
    const [selectedOrgId, setSelectedOrgId] = useState<string | null>(null);
    const [newName, setNewName] = useState('');
    const [includeData, setIncludeData] = useState(false);
    const [forking, setForking] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [planLimitError, setPlanLimitError] = useState<string | null>(null);
    const [organizations, setOrganizations] = useState<UserOrg[]>([]);
    const [loadingOrgs, setLoadingOrgs] = useState(false);
    const { listMyOrganizations } = useOrganization();

    // Reset state when dialog opens
    useEffect(() => {
        if (isOpen && resource) {
            setDestinationType('personal');
            setSelectedOrgId(null);
            setNewName(`Copy of ${resource.name}`);
            setIncludeData(false);
            setError(null);
            setPlanLimitError(null);

            // Fetch organizations
            setLoadingOrgs(true);
            listMyOrganizations().then((orgs) => {
                if (orgs) {
                    setOrganizations(orgs);
                }
                setLoadingOrgs(false);
            });
        }
    }, [isOpen, resource, listMyOrganizations]);

    // Select first org when switching to organization destination
    useEffect(() => {
        if (destinationType === 'organization' && organizations.length > 0 && !selectedOrgId) {
            setSelectedOrgId(organizations[0].id);
        }
    }, [destinationType, organizations, selectedOrgId]);

    const handleFork = async () => {
        if (!resource) return;

        // Validate org selection
        if (destinationType === 'organization' && !selectedOrgId) {
            setError('Please select an organization');
            return;
        }

        setForking(true);
        setError(null);

        try {
            const request = ResourceForkRequest.create({
                request_id: crypto.randomUUID(),
                resource_type: resourceType,
                resource_id: resource.id,
                destination_type: destinationType,
                destination_org_id: destinationType === 'organization' ? selectedOrgId! : undefined,
                new_name: newName.trim() || undefined,
                include_data: resourceType === 'database' ? includeData : false,
            });

            const response = await sendEventAsync(request, undefined, 30000) as {
                success: boolean;
                forked_resource?: { id: string; name: string };
                message?: string;
                error?: string;
            };

            if (response.error) {
                if (isPlanLimitError(response.error)) {
                    setPlanLimitError(response.error);
                } else {
                    setError(response.error);
                }
            } else if (response.success && response.forked_resource) {
                onOpenChange(false);
                onForkSuccess?.(
                    response.forked_resource.id,
                    response.forked_resource.name
                );
            } else {
                setError(response.message || 'Failed to fork resource');
            }
        } catch (err) {
            const errMsg = err instanceof Error ? err.message : 'Failed to fork resource';
            if (isPlanLimitError(errMsg)) {
                setPlanLimitError(errMsg);
            } else {
                setError(errMsg);
            }
        } finally {
            setForking(false);
        }
    };

    const ResourceIcon = resourceType === 'workflow' ? Workflow : Database;

    return (<>
        <Dialog open={isOpen} onOpenChange={onOpenChange}>
            <DialogContent className="bg-sunken border-border text-foreground max-w-md p-6">
                <DialogHeader className="pb-4">
                    <DialogTitle className="text-xl text-foreground flex items-center gap-2">
                        <GitFork className="h-5 w-5" />
                        Fork {resourceType === 'workflow' ? 'Workflow' : 'Database'}
                    </DialogTitle>
                    <div className="text-sm text-muted-foreground pt-1.5">
                        Create an independent copy you can modify freely
                    </div>
                </DialogHeader>

                <div className="space-y-6">
                    {/* Source resource display */}
                    {resource && (
                        <div className="flex items-center gap-3 p-3 bg-card/50 rounded-lg border border-border/50 dark:border-zinc-800/50">
                            <div className="p-2 rounded-full bg-secondary">
                                <ResourceIcon className="w-4 h-4 text-muted-foreground" />
                            </div>
                            <div className="min-w-0 flex-1">
                                <p className="text-sm font-medium text-foreground truncate">
                                    {resource.name}
                                </p>
                                <p className="text-xs text-muted-foreground dark:text-zinc-500">
                                    Original {resourceType}
                                </p>
                            </div>
                        </div>
                    )}

                    {/* Destination selector */}
                    <div className="space-y-3">
                        <label className="text-sm font-medium text-foreground/80">
                            Fork to
                        </label>
                        <div className="grid grid-cols-2 gap-2">
                            <button
                                type="button"
                                onClick={() => setDestinationType('personal')}
                                className={cn(
                                    'flex items-center gap-3 p-3 rounded-lg border transition-all duration-200',
                                    destinationType === 'personal'
                                        ? 'bg-accent/80 border-muted-foreground/50 dark:border-zinc-600 ring-1 ring-muted-foreground/50 dark:ring-zinc-600'
                                        : 'bg-card/50 border-border/50 dark:border-zinc-800/50 hover:border-muted-foreground/40 dark:hover:border-zinc-700 hover:bg-card'
                                )}
                            >
                                <div className={cn(
                                    'p-1.5 rounded-full transition-colors',
                                    destinationType === 'personal' ? 'bg-foreground/10' : 'bg-secondary'
                                )}>
                                    <User className={cn(
                                        'w-4 h-4',
                                        destinationType === 'personal' ? 'text-foreground' : 'text-muted-foreground dark:text-zinc-500'
                                    )} />
                                </div>
                                <span className={cn(
                                    'text-sm font-medium',
                                    destinationType === 'personal' ? 'text-foreground' : 'text-muted-foreground'
                                )}>
                                    Personal
                                </span>
                            </button>
                            <button
                                type="button"
                                onClick={() => setDestinationType('organization')}
                                disabled={organizations.length === 0 && !loadingOrgs}
                                className={cn(
                                    'flex items-center gap-3 p-3 rounded-lg border transition-all duration-200',
                                    destinationType === 'organization'
                                        ? 'bg-accent/80 border-muted-foreground/50 dark:border-zinc-600 ring-1 ring-muted-foreground/50 dark:ring-zinc-600'
                                        : 'bg-card/50 border-border/50 dark:border-zinc-800/50 hover:border-muted-foreground/40 dark:hover:border-zinc-700 hover:bg-card',
                                    organizations.length === 0 && !loadingOrgs && 'opacity-50 cursor-not-allowed hover:bg-card/50 hover:border-border/50 dark:hover:border-zinc-800/50'
                                )}
                            >
                                <div className={cn(
                                    'p-1.5 rounded-full transition-colors',
                                    destinationType === 'organization' ? 'bg-foreground/10' : 'bg-secondary'
                                )}>
                                    <Building2 className={cn(
                                        'w-4 h-4',
                                        destinationType === 'organization' ? 'text-foreground' : 'text-muted-foreground dark:text-zinc-500'
                                    )} />
                                </div>
                                <span className={cn(
                                    'text-sm font-medium',
                                    destinationType === 'organization' ? 'text-foreground' : 'text-muted-foreground'
                                )}>
                                    Organization
                                </span>
                            </button>
                        </div>
                    </div>

                    {/* Organization selector (when organization is selected) */}
                    {destinationType === 'organization' && (
                        <div className="space-y-3">
                            <label className="text-sm font-medium text-foreground/80">
                                Select organization
                            </label>
                            {loadingOrgs ? (
                                <div className="flex items-center justify-center py-4">
                                    <Loader2 className="w-5 h-5 animate-spin text-muted-foreground dark:text-zinc-500" />
                                </div>
                            ) : (
                                <div className="space-y-1 max-h-32 overflow-y-auto rounded-lg border border-border/50 dark:border-zinc-800/50 bg-card/30">
                                    {organizations.map((org) => (
                                        <button
                                            key={org.id}
                                            type="button"
                                            onClick={() => setSelectedOrgId(org.id)}
                                            className={cn(
                                                'w-full flex items-center gap-3 p-2.5 transition-colors',
                                                selectedOrgId === org.id
                                                    ? 'bg-accent/80 text-foreground'
                                                    : 'hover:bg-accent/50 text-foreground/80'
                                            )}
                                        >
                                            {org.icon_url ? (
                                                <img
                                                    src={org.icon_url}
                                                    alt=""
                                                    className="w-6 h-6 rounded-full object-cover"
                                                />
                                            ) : (
                                                <div className={cn(
                                                    "w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium",
                                                    selectedOrgId === org.id
                                                        ? "bg-foreground/20 text-foreground"
                                                        : "bg-muted-foreground/30 dark:bg-zinc-700 text-foreground/80"
                                                )}>
                                                    {getOrgInitials(org.name)}
                                                </div>
                                            )}
                                            <span className="text-sm truncate">{org.name}</span>
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Name input */}
                    <div className="space-y-3">
                        <label className="text-sm font-medium text-foreground/80">
                            Name
                        </label>
                        <div className="bg-card/90 backdrop-blur-sm rounded-full transition-all duration-200 border border-input dark:border-zinc-700/60 focus-within:border-muted-foreground/40 dark:focus-within:border-zinc-600/80">
                            <input
                                type="text"
                                value={newName}
                                onChange={(e) => setNewName(e.target.value)}
                                placeholder={`Copy of ${resource?.name || ''}`}
                                className="bg-transparent text-foreground px-4 py-2.5 outline-none w-full text-sm placeholder:text-[hsl(var(--placeholder))]"
                            />
                        </div>
                    </div>

                    {/* Include data checkbox (databases only) */}
                    {resourceType === 'database' && (
                        <label className="flex items-center gap-3 cursor-pointer group">
                            <div className={cn(
                                'w-5 h-5 rounded border-2 flex items-center justify-center transition-all',
                                includeData
                                    ? 'bg-primary border-primary'
                                    : 'border-muted-foreground/50 dark:border-zinc-600 group-hover:border-muted-foreground/70 dark:group-hover:border-zinc-500'
                            )}>
                                {includeData && (
                                    <svg className="w-3 h-3 text-primary-foreground" viewBox="0 0 12 12" fill="none">
                                        <path d="M2 6L5 9L10 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                                    </svg>
                                )}
                            </div>
                            <input
                                type="checkbox"
                                checked={includeData}
                                onChange={(e) => setIncludeData(e.target.checked)}
                                className="sr-only"
                            />
                            <div>
                                <span className="text-sm text-foreground">Include existing data</span>
                                <p className="text-xs text-muted-foreground dark:text-zinc-500">Copy all rows from the original table</p>
                            </div>
                        </label>
                    )}

                    {/* Error message */}
                    {error && (
                        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                            <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
                        </div>
                    )}
                </div>

                {/* Actions */}
                <div className="flex justify-end gap-2 pt-6">
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                        disabled={forking}
                        className="h-10 bg-transparent text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] border border-border hover:border-muted-foreground/40 dark:hover:border-zinc-700 rounded-md"
                    >
                        Cancel
                    </Button>
                    <Button
                        type="button"
                        onClick={handleFork}
                        disabled={forking || !resource}
                        className="h-10 bg-primary hover:bg-primary text-primary-foreground font-medium rounded-md border-0 shadow-[0_2.5px_0_0_hsl(var(--primary)/0.6)] hover:shadow-[0_1px_0_0_hsl(var(--primary)/0.6)] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100 disabled:opacity-40 min-w-[100px]"
                    >
                        {forking ? (
                            <>
                                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                                Forking...
                            </>
                        ) : (
                            <>
                                <Copy className="w-4 h-4 mr-2" />
                                Create Copy
                            </>
                        )}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>

        <UpgradePopup
            isOpen={!!planLimitError}
            onOpenChange={(open) => { if (!open) setPlanLimitError(null); }}
            errorMessage={planLimitError || ''}
        />
    </>
    );
}
