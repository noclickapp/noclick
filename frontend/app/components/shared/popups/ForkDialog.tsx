/**
 * ForkDialog component for creating independent copies of shared resources.
 * Allows users to fork workflows and databases to their personal workspace
 * or an organization they belong to.
 */

import { useState, useEffect, useId } from 'react';
import type { ReactNode } from 'react';
import {
    Check,
    GitFork,
    User,
    Loader2,
    Database,
    Workflow,
    Copy,
} from 'lucide-react';
import { ShellDialog } from '~/components/shell/ShellDialog';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';
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

const TILE =
    'grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-lg bg-foreground/[0.06] text-foreground/80';

function DestinationRow({
    selected,
    onSelect,
    tile,
    label,
}: {
    selected: boolean;
    onSelect: () => void;
    tile: ReactNode;
    label: string;
}) {
    return (
        <button
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={onSelect}
            className={cn(
                'flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                selected
                    ? 'bg-foreground/[0.06] text-foreground'
                    : 'text-foreground/80 hover:bg-foreground/[0.04] hover:text-foreground'
            )}
        >
            {tile}
            <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">
                {label}
            </span>
            {selected && (
                <Check className="h-4 w-4 shrink-0" strokeWidth={2} />
            )}
        </button>
    );
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
    const ids = useId();
    const noun = resourceType === 'workflow' ? 'automation' : 'database';

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
            setError('Choose a workspace.');
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
                setError(response.message || `Couldn’t fork this ${noun}.`);
            }
        } catch (err) {
            const errMsg = err instanceof Error ? err.message : `Couldn’t fork this ${noun}.`;
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
        <ShellDialog
            open={isOpen}
            onOpenChange={onOpenChange}
            size="sm"
            mark={<GitFork className="h-5 w-5" strokeWidth={1.75} />}
            title={`Fork ${noun}`}
            description="An independent copy you can change freely."
            onSubmit={(e) => {
                e.preventDefault();
                void handleFork();
            }}
            footer={
                <>
                    <button
                        type="button"
                        onClick={() => onOpenChange(false)}
                        disabled={forking}
                        className={BUTTON_GHOST}
                    >
                        Cancel
                    </button>
                    <button
                        type="submit"
                        disabled={forking || !resource}
                        className={BUTTON_PRIMARY}
                    >
                        {forking ? (
                            <>
                                <Loader2 className="h-4 w-4 animate-spin" />
                                Forking…
                            </>
                        ) : (
                            <>
                                <Copy className="h-4 w-4" strokeWidth={1.75} />
                                Create copy
                            </>
                        )}
                    </button>
                </>
            }
        >
            <div className="space-y-5">
                {/* Source resource display */}
                {resource && (
                    <div className="flex items-center gap-3 rounded-xl bg-foreground/[0.04] px-3 py-2.5">
                        <span className={TILE}>
                            <ResourceIcon className="h-4 w-4" strokeWidth={1.75} />
                        </span>
                        <div className="min-w-0 flex-1">
                            <p className="truncate text-[13.5px] font-medium text-foreground">
                                {resource.name}
                            </p>
                            <p className="text-[12.5px] text-muted-foreground">
                                Original {noun}
                            </p>
                        </div>
                    </div>
                )}

                {/* Destination: personal, or one of the user's workspaces */}
                <div>
                    <p id={`${ids}-destination`} className={FIELD_LABEL}>
                        Fork to
                    </p>
                    <div
                        role="radiogroup"
                        aria-labelledby={`${ids}-destination`}
                        className="space-y-1"
                    >
                        <DestinationRow
                            selected={destinationType === 'personal'}
                            onSelect={() => setDestinationType('personal')}
                            tile={
                                <span className={TILE}>
                                    <User className="h-4 w-4" strokeWidth={1.75} />
                                </span>
                            }
                            label="Personal"
                        />
                        {organizations.map((org) => (
                            <DestinationRow
                                key={org.id}
                                selected={destinationType === 'organization' && selectedOrgId === org.id}
                                onSelect={() => {
                                    setDestinationType('organization');
                                    setSelectedOrgId(org.id);
                                }}
                                tile={
                                    <span className={cn(TILE, 'text-[11px] font-medium')}>
                                        {org.icon_url ? (
                                            <img
                                                src={org.icon_url}
                                                alt=""
                                                className="h-full w-full object-cover"
                                            />
                                        ) : (
                                            getOrgInitials(org.name)
                                        )}
                                    </span>
                                }
                                label={org.name}
                            />
                        ))}
                        {loadingOrgs && organizations.length === 0 && (
                            <div className="flex items-center gap-2 px-3 py-2 text-[13px] text-muted-foreground">
                                <Loader2 className="h-4 w-4 animate-spin" />
                                Loading workspaces…
                            </div>
                        )}
                    </div>
                </div>

                {/* Name input */}
                <div>
                    <label htmlFor={`${ids}-name`} className={FIELD_LABEL}>
                        Name
                    </label>
                    <input
                        id={`${ids}-name`}
                        type="text"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        placeholder={`Copy of ${resource?.name || ''}`}
                        className={FIELD}
                    />
                </div>

                {/* Include data checkbox (databases only) */}
                {resourceType === 'database' && (
                    <label className="group flex cursor-pointer items-start gap-3">
                        <input
                            type="checkbox"
                            checked={includeData}
                            onChange={(e) => setIncludeData(e.target.checked)}
                            className="peer sr-only"
                        />
                        <span
                            className={cn(
                                'mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-[5px] border transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-ring',
                                includeData
                                    ? 'border-primary bg-primary text-primary-foreground'
                                    : 'border-foreground/25 group-hover:border-foreground/40'
                            )}
                        >
                            {includeData && (
                                <Check className="h-3 w-3" strokeWidth={2.5} />
                            )}
                        </span>
                        <span>
                            <span className="block text-[13.5px] text-foreground">Include existing data</span>
                            <span className="block text-[12.5px] text-muted-foreground">Copy all rows from the original table</span>
                        </span>
                    </label>
                )}

                {/* Error message */}
                {error && (
                    <p role="alert" className="text-[13px] text-red-600 dark:text-red-400">
                        {error}
                    </p>
                )}
            </div>
        </ShellDialog>

        <UpgradePopup
            isOpen={!!planLimitError}
            onOpenChange={(open) => { if (!open) setPlanLimitError(null); }}
            errorMessage={planLimitError || ''}
        />
    </>
    );
}
