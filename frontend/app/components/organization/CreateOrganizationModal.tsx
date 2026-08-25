/**
 * Modal component for creating a new organization.
 * Used from the dashboard or account settings to create and join a new organization.
 * Supports custom slug input with real-time availability checking.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog';
import { Button } from '~/components/ui/button';
import { useOrganization } from '~/hooks/useOrganization';
import { useOrgContext } from '~/hooks/useOrgContext';
import { toast } from 'sonner';
import { Loader2, Building2, Check, X } from 'lucide-react';
import { cn } from '~/lib/utils';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { isPlanLimitError } from '~/lib/planLimitErrors';

interface CreateOrganizationModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateOrganizationModal({ open, onOpenChange }: CreateOrganizationModalProps) {
  const navigate = useNavigate();
  const [, setOrgContext] = useOrgContext();
  const { createOrganization, switchOrganization, checkSlugAvailability, loading, error, clearError } = useOrganization();
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [slugStatus, setSlugStatus] = useState<'idle' | 'checking' | 'available' | 'taken' | 'invalid'>('idle');
  const [slugError, setSlugError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [planLimitError, setPlanLimitError] = useState<string | null>(null);
  const checkTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Generate slug from name
  const generateSlugFromName = (name: string): string => {
    return name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 50);
  };

  // Debounced slug availability check
  const checkSlug = useCallback(async (slugToCheck: string) => {
    if (!slugToCheck || slugToCheck.length < 2) {
      setSlugStatus('idle');
      setSlugError(null);
      return;
    }

    setSlugStatus('checking');
    const result = await checkSlugAvailability(slugToCheck);

    if (result) {
      if (result.error) {
        setSlugStatus('invalid');
        setSlugError(result.error);
      } else if (result.available) {
        setSlugStatus('available');
        setSlugError(null);
      } else {
        setSlugStatus('taken');
        setSlugError('This identifier is already taken');
      }
    } else {
      setSlugStatus('idle');
      setSlugError(null);
    }
  }, [checkSlugAvailability]);

  // Handle slug input change with debounce
  const handleSlugChange = (value: string) => {
    // Only allow valid slug characters
    const sanitized = value.toLowerCase().replace(/[^a-z0-9-]/g, '');
    setSlug(sanitized);
    setSlugStatus('idle');
    setSlugError(null);

    // Clear existing timeout
    if (checkTimeoutRef.current) {
      clearTimeout(checkTimeoutRef.current);
    }

    // Debounce the availability check
    if (sanitized.length >= 2) {
      checkTimeoutRef.current = setTimeout(() => {
        checkSlug(sanitized);
      }, 400);
    }
  };

  // Auto-generate slug when name changes (if slug hasn't been manually edited)
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false);

  useEffect(() => {
    if (!slugManuallyEdited && name) {
      const generated = generateSlugFromName(name);
      setSlug(generated);
      setSlugStatus('idle');
      setSlugError(null);

      // Clear existing timeout
      if (checkTimeoutRef.current) {
        clearTimeout(checkTimeoutRef.current);
      }

      // Debounce the availability check
      if (generated.length >= 2) {
        checkTimeoutRef.current = setTimeout(() => {
          checkSlug(generated);
        }, 400);
      }
    }
  }, [name, slugManuallyEdited, checkSlug]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (checkTimeoutRef.current) {
        clearTimeout(checkTimeoutRef.current);
      }
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!name.trim()) {
      toast.error('Organization name is required');
      return;
    }

    if (slugStatus === 'taken' || slugStatus === 'invalid') {
      toast.error('Please choose a different identifier');
      return;
    }

    setCreating(true);
    const { organization: org, error: createError } = await createOrganization(name.trim(), slug.trim() || undefined);
    setCreating(false);

    if (org) {
      // Switch to the newly created organization on the backend (sets it as primary)
      await switchOrganization(org.id);
      // Update local context (creator is always owner)
      setOrgContext({ id: org.id, role: 'owner', subscription_tier: 'free', isPersonalWorkspace: false });
      toast.success(`${org.name} created successfully!`);
      setName('');
      setSlug('');
      setSlugManuallyEdited(false);
      onOpenChange(false);
      navigate('/dashboard?tab=settings&section=organization');
    } else if (createError) {
      if (isPlanLimitError(createError)) {
        // Close the create modal first to avoid nested Dialog conflicts, then show plan limit popup
        onOpenChange(false);
        setPlanLimitError(createError);
      } else {
        toast.error(createError);
      }
      clearError();
    }
  };

  const handleOpenChange = (open: boolean) => {
    onOpenChange(open);
    if (!open) {
      setName('');
      setSlug('');
      setSlugManuallyEdited(false);
      setSlugStatus('idle');
      setSlugError(null);
      // Don't reset planLimitError here — it may have just been set before closing
    }
  };

  return (
    <>
    <UpgradePopup
      isOpen={!!planLimitError}
      onOpenChange={(open) => { if (!open) setPlanLimitError(null); }}
      errorMessage={planLimitError || ''}
    />
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="bg-sunken border-border text-foreground max-w-md p-6">
        <DialogHeader className="pb-1">
          <DialogTitle className="text-xl text-foreground flex items-center gap-2">
            <Building2 className="h-5 w-5" />
            Create Organization
          </DialogTitle>
          <div className="text-sm text-muted-foreground pt-0.5">
            Collaborate with team members and share resources
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit}>
          <div className="space-y-5">
            {/* Organization Name */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground/80">
                Organization Name
              </label>
              <div className="bg-card/90 backdrop-blur-sm rounded-full transition-all duration-200 border border-border/60 dark:border-zinc-700/60 focus-within:border-muted-foreground/80 dark:focus-within:border-zinc-600/80">
                <input
                  id="orgName"
                  name="name"
                  type="text"
                  required
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="bg-transparent text-foreground px-4 py-2.5 outline-none w-full text-sm placeholder:text-[hsl(var(--placeholder))] rounded-full"
                  placeholder="Acme Inc."
                />
              </div>
            </div>

            {/* Identifier (Slug) */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground/80">
                Identifier
              </label>
              <div className={cn(
                "bg-card/90 backdrop-blur-sm rounded-full transition-all duration-200 border flex items-center",
                slugStatus === 'taken' && "border-red-500/50",
                slugStatus === 'invalid' && "border-amber-500/50",
                (slugStatus === 'idle' || slugStatus === 'checking' || slugStatus === 'available') && "border-border/60 dark:border-zinc-700/60 focus-within:border-muted-foreground/80 dark:focus-within:border-zinc-600/80"
              )}>
                <input
                  id="orgSlug"
                  name="slug"
                  type="text"
                  value={slug}
                  onChange={(e) => {
                    setSlugManuallyEdited(true);
                    handleSlugChange(e.target.value);
                  }}
                  className="bg-transparent text-foreground px-4 py-2.5 outline-none flex-1 text-sm placeholder:text-[hsl(var(--placeholder))] rounded-l-full"
                  placeholder="acme-corp"
                />
                <div className="pr-4 flex items-center justify-center w-8">
                  {slugStatus === 'checking' && (
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                  )}
                  {slugStatus === 'available' && (
                    <Check className="h-4 w-4 text-muted-foreground dark:text-white/70" />
                  )}
                  {(slugStatus === 'taken' || slugStatus === 'invalid') && (
                    <X className="h-4 w-4 text-red-600 dark:text-red-400" />
                  )}
                </div>
              </div>
              <p className={cn(
                "text-xs",
                slugError ? "text-red-600 dark:text-red-400" : "text-muted-foreground dark:text-zinc-500"
              )}>
                {slugError || (
                  <>
                    Used for SSO login URL · <span className="text-muted-foreground">Cannot be changed later</span>
                  </>
                )}
              </p>
            </div>
          </div>

          <div className="flex justify-between pt-6">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={creating || loading}
              className="h-10 bg-transparent text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] border border-border hover:border-border dark:hover:border-zinc-700 rounded-md"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!name.trim() || creating || loading || slugStatus === 'taken' || slugStatus === 'invalid' || slugStatus === 'checking'}
              className="h-10 bg-primary hover:bg-primary text-primary-foreground font-medium rounded-md border-0 shadow-[0_2.5px_0_0_#a0a0a0] hover:shadow-[0_1px_0_0_#a0a0a0] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100 disabled:opacity-40 min-w-[100px]"
            >
              {creating ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Creating...
                </>
              ) : (
                'Create'
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
    </>
  );
}
