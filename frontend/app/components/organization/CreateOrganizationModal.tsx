/**
 * Making a workspace (an organization on the wire) from the workspace menu: its name, and the identifier its
 * sign-in link uses, checked for availability as it's typed.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { ShellDialog } from '~/components/shell/ShellDialog';
import { BUTTON_GHOST, BUTTON_PRIMARY } from '~/components/shell/buttons';
import { FIELD, FIELD_LABEL } from '~/components/shell/fields';
import { useOrganization } from '~/hooks/useOrganization';
import { useOrgContext } from '~/hooks/useOrgContext';
import { toast } from 'sonner';
import { Loader2, Users, Check, X } from 'lucide-react';
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
  const { createOrganization, switchOrganization, checkSlugAvailability, loading, clearError } = useOrganization();
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
        setSlugError('That identifier is taken.');
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
      toast.error('Give the workspace a name');
      return;
    }

    if (slugStatus === 'taken' || slugStatus === 'invalid') {
      toast.error('Choose a different identifier');
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
      toast.success(`${org.name} is ready`);
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
    <ShellDialog
      open={open}
      onOpenChange={handleOpenChange}
      mark={<Users className="h-5 w-5" strokeWidth={1.75} />}
      title="New workspace"
      description="Share automations and accounts with your team."
      onSubmit={handleSubmit}
      footer={
        <>
          <button type="button" onClick={() => onOpenChange(false)} disabled={creating || loading} className={BUTTON_GHOST}>
            Cancel
          </button>
          <button
            type="submit"
            disabled={!name.trim() || creating || loading || slugStatus === 'taken' || slugStatus === 'invalid' || slugStatus === 'checking'}
            className={BUTTON_PRIMARY}
          >
            {creating && <Loader2 className="h-4 w-4 animate-spin" />}
            {creating ? 'Creating…' : 'Create workspace'}
          </button>
        </>
      }
    >
      <div className="space-y-4 pt-2">
        <label className="block">
          <span className={FIELD_LABEL}>Name</span>
          <input
            id="orgName"
            name="name"
            type="text"
            required
            // eslint-disable-next-line jsx-a11y/no-autofocus -- the dialog opens to type a name
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={FIELD}
            placeholder="Acme Inc."
          />
        </label>
        <div>
          <label htmlFor="orgSlug" className={FIELD_LABEL}>
            Identifier
          </label>
          <div className="relative">
            <input
              id="orgSlug"
              name="slug"
              type="text"
              value={slug}
              onChange={(e) => {
                setSlugManuallyEdited(true);
                handleSlugChange(e.target.value);
              }}
              className={cn(FIELD, 'pr-10', slugStatus === 'taken' && 'border-red-500/60 focus:border-red-500/60 dark:border-red-400/50', slugStatus === 'invalid' && 'border-amber-500/60 dark:border-amber-400/50')}
              placeholder="acme"
              aria-invalid={slugStatus === 'taken' || slugStatus === 'invalid'}
            />
            <span className="pointer-events-none absolute inset-y-0 right-3.5 flex items-center">
              {slugStatus === 'checking' && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
              {slugStatus === 'available' && <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />}
              {(slugStatus === 'taken' || slugStatus === 'invalid') && <X className="h-4 w-4 text-red-600 dark:text-red-400" />}
            </span>
          </div>
          <p className={cn('mt-1.5 text-[12.5px]', slugError ? 'text-red-600 dark:text-red-400' : 'text-muted-foreground')} role={slugError ? 'alert' : undefined}>
            {slugError || 'Used in its single sign-on link. It can’t be changed later.'}
          </p>
        </div>
      </div>
    </ShellDialog>
    </>
  );
}
