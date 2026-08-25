/**
 * Organization settings component with modern, subtle glassmorphism styling.
 * Two tabs: Overview (general info + members) and SSO configuration.
 * Integrated into the dashboard SPA as a tab view.
 * Uses useUrlSyncedTab hook for URL-persisted tab state.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { ArrowLeft, Building2, Users, Shield, Loader2, UserPlus, Upload, Copy, Check, X, Search, ChevronDown, Pencil, AlertTriangle, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router';
import { useOrganization, type Organization, type OrganizationMember, type OrganizationInvite } from '~/hooks/useOrganization';
import { useOrgContext } from '~/hooks/useOrgContext';
import { useUrlSyncedTab } from '~/hooks/useUrlSyncedTab';
import { navigateToTab, type OrgSettingsTab } from '~/lib/navigation';
import { cn } from '~/lib/utils';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { toast } from 'sonner';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { isMemberLimitError } from '~/lib/planLimitErrors';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu';
import { Button } from '~/components/ui/button';

interface OrganizationSettingsProps {
  organizationId: string;
  onNavigateBack?: () => void;
  /** When true, hides the header with back button (for embedding in Settings) */
  embedded?: boolean;
  /** When true, shows a simplified view for personal workspace (no name/slug editing, no SSO, no delete) */
  isPersonalWorkspace?: boolean;
}

export function OrganizationSettings({ organizationId, onNavigateBack, embedded = false, isPersonalWorkspace = false }: OrganizationSettingsProps) {
  const navigate = useNavigate();
  const [, setOrgContext] = useOrgContext();

  // Use standardized hook for URL-synced tab state
  const [activeTab, setActiveTab] = useUrlSyncedTab<OrgSettingsTab>({
    param: 'orgTab',
    defaultValue: 'overview',
    validValues: ['overview', 'sso', 'danger'],
    extraParams: { tab: 'settings', section: 'organization' },
  });

  const [organization, setOrganization] = useState<Organization | null>(null);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [invites, setInvites] = useState<OrganizationInvite[]>([]);
  const [pageLoading, setPageLoading] = useState(true);

  // Preserve the raw member-limit error for the compatibility dialog.
  const [memberLimitError, setMemberLimitError] = useState<string | null>(null);

  const {
    getOrganization,
    updateOrganization,
    deleteOrganization,
    transferOwnership,
    listMembers,
    listInvites,
    inviteMember,
    removeMember,
    updateMemberRole,
    revokeInvite,
    uploadIcon,
    loading,
    error,
    clearError,
  } = useOrganization();

  const userRole = organization?.user_role as 'owner' | 'admin' | 'member' | undefined;
  const canEdit = userRole === 'owner' || userRole === 'admin';
  const isOwner = userRole === 'owner';

  const fetchData = useCallback(async () => {
    if (!organizationId) return;
    setPageLoading(true);
    const [org, membersList, invitesList] = await Promise.all([
      getOrganization(organizationId),
      listMembers(organizationId),
      listInvites(organizationId),
    ]);
    if (org) {
      setOrganization(org);
      setMembers(membersList);
      setInvites(invitesList);
    }
    setPageLoading(false);
  }, [organizationId, getOrganization, listMembers, listInvites]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (error) {
      if (isMemberLimitError(error)) {
        setMemberLimitError(error);
      }
      toast.error(error);
      clearError();
    }
  }, [error, clearError]);

  const handleNavigateBack = () => {
    if (onNavigateBack) {
      onNavigateBack();
    } else {
      navigateToTab('vite');
    }
  };

  if (pageLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground/70 dark:text-white/30" />
      </div>
    );
  }

  if (!organization) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <p className="text-muted-foreground dark:text-white/50 text-sm">Organization not found or access denied.</p>
        <button
          onClick={handleNavigateBack}
          className="text-sm text-muted-foreground dark:text-white/70 hover:text-foreground transition-colors"
        >
          Back to Dashboard
        </button>
      </div>
    );
  }

  return (
    <div className={cn("w-full", !embedded && "max-w-4xl mx-auto")}>
      {/* Header - hidden when embedded in Settings */}
      {!embedded && (
        <div className="flex items-center gap-4 mb-8">
          <button
            onClick={handleNavigateBack}
            className="flex items-center justify-center w-10 h-10 text-muted-foreground dark:text-white/40 hover:text-foreground/80 hover:bg-foreground/[0.04] rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div className="flex items-center gap-3">
            {organization.icon_url ? (
              <img
                src={organization.icon_url}
                alt={organization.name}
                className="w-9 h-9 rounded-full object-cover"
              />
            ) : (
              <div className="w-9 h-9 rounded-full bg-blue-500/20 flex items-center justify-center">
                <Building2 className="w-4 h-4 text-blue-600 dark:text-blue-400" />
              </div>
            )}
            <div>
              <h2 className="text-lg font-medium text-foreground/90">{organization.name}</h2>
              <p className="text-xs text-muted-foreground dark:text-white/40">Organization Settings</p>
            </div>
          </div>
        </div>
      )}

      {/* Embedded header - simpler, without back button or avatar */}
      {embedded && (
        <div className="mb-8">
          <h2 className="text-2xl font-semibold text-foreground tracking-tight">
            {isPersonalWorkspace ? 'Members' : organization.name}
          </h2>
          <p className="text-sm text-muted-foreground dark:text-white/40 mt-1">
            {isPersonalWorkspace ? 'Invite members to your workspace' : 'Manage your organization'}
          </p>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-6">
        <button
          onClick={() => setActiveTab('overview')}
          className={cn(
            "flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors",
            activeTab === 'overview'
              ? "bg-foreground/[0.08] text-accent-foreground dark:text-white/90"
              : "text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:bg-foreground/[0.04]"
          )}
        >
          <Users className="w-3.5 h-3.5" />
          Overview
        </button>
        {canEdit && !isPersonalWorkspace && (
          <button
            onClick={() => setActiveTab('sso')}
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors",
              activeTab === 'sso'
                ? "bg-foreground/[0.08] text-accent-foreground dark:text-white/90"
                : "text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:bg-foreground/[0.04]"
            )}
          >
            <Shield className="w-3.5 h-3.5" />
            SSO
          </button>
        )}
        {isOwner && !isPersonalWorkspace && (
          <button
            onClick={() => setActiveTab('danger')}
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 text-sm rounded-md transition-colors ml-auto",
              activeTab === 'danger'
                ? "bg-red-500/20 text-red-600 dark:text-red-400"
                : "text-muted-foreground dark:text-white/50 hover:text-red-600/80 dark:hover:text-red-400/80 hover:bg-red-500/10"
            )}
          >
            <Trash2 className="w-3.5 h-3.5" />
            Danger Zone
          </button>
        )}
      </div>

      {/* Content */}
      {activeTab === 'overview' && (
        <OverviewTab
          organization={organization}
          members={members}
          invites={invites}
          canEdit={canEdit}
          loading={loading}
          isPersonalWorkspace={isPersonalWorkspace}
          onUpdate={async (updates) => {
            const updated = await updateOrganization(organizationId, updates);
            if (updated) {
              setOrganization(updated);
              toast.success('Organization updated');
            }
          }}
          onUploadIcon={async (imageData, contentType) => {
            const iconUrl = await uploadIcon(organizationId, imageData, contentType);
            if (iconUrl) {
              setOrganization({ ...organization, icon_url: iconUrl });
              toast.success('Icon uploaded');
            }
          }}
          onInvite={async (email, role) => {
            const invite = await inviteMember(organizationId, email, role);
            if (invite) {
              setInvites([...invites, invite]);
              toast.success(`Invitation sent to ${email}`);
            }
          }}
          onRemoveMember={async (userId) => {
            const success = await removeMember(organizationId, userId);
            if (success) {
              setMembers(members.filter(m => m.user_id !== userId));
              toast.success('Member removed');
            }
          }}
          onUpdateRole={async (userId, role) => {
            const success = await updateMemberRole(organizationId, userId, role);
            if (success) {
              setMembers(members.map(m => m.user_id === userId ? { ...m, role } : m));
              toast.success('Role updated');
            }
          }}
          onRevokeInvite={async (inviteId) => {
            const success = await revokeInvite(organizationId, inviteId);
            if (success) {
              setInvites(invites.filter(i => i.id !== inviteId));
              toast.success('Invitation revoked');
            }
          }}
        />
      )}

      {activeTab === 'sso' && canEdit && (
        <SSOTab
          organization={organization}
          organizationId={organizationId}
          onUpdate={fetchData}
        />
      )}

      {activeTab === 'danger' && isOwner && (
        <DangerZoneTab
          organization={organization}
          members={members}
          onTransferOwnership={async (userId) => {
            const success = await transferOwnership(organizationId, userId);
            if (success) {
              toast.success('Ownership transferred successfully');
              await fetchData();
              setActiveTab('overview');
            }
          }}
          onDelete={async () => {
            const success = await deleteOrganization(organizationId);
            if (success) {
              // Clear org context before navigating to ensure clean state
              setOrgContext({ id: null, role: 'owner', subscription_tier: null, isPersonalWorkspace: true });
              toast.success('Organization deleted');
              navigate('/dashboard');
            }
          }}
        />
      )}

      {/* Member limit compatibility dialog */}
      <UpgradePopup
        isOpen={!!memberLimitError}
        onOpenChange={(open) => { if (!open) setMemberLimitError(null); }}
        errorMessage={memberLimitError ?? undefined}
      />
    </div>
  );
}

// Overview Tab - Combined General + Members
function OverviewTab({
  organization,
  members,
  invites,
  canEdit,
  loading,
  isPersonalWorkspace,
  onUpdate,
  onUploadIcon,
  onInvite,
  onRemoveMember,
  onUpdateRole,
  onRevokeInvite,
}: {
  organization: Organization;
  members: OrganizationMember[];
  invites: OrganizationInvite[];
  canEdit: boolean;
  loading: boolean;
  isPersonalWorkspace?: boolean;
  onUpdate: (updates: { name?: string }) => Promise<void>;
  onUploadIcon: (imageData: string, contentType: string) => Promise<void>;
  onInvite: (email: string, role: 'admin' | 'member') => Promise<void>;
  onRemoveMember: (userId: string) => Promise<void>;
  onUpdateRole: (userId: string, role: 'admin' | 'member') => Promise<void>;
  onRevokeInvite: (inviteId: string) => Promise<void>;
}) {
  const [name, setName] = useState(organization.name);
  const [isEditingName, setIsEditingName] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<'admin' | 'member'>('member');
  const [confirmRemove, setConfirmRemove] = useState<OrganizationMember | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const nameInputRef = useRef<HTMLInputElement>(null);

  // Filter members based on search query
  const filteredMembers = fuzzyFilter(members, searchQuery, (member) => [
    {
      text: (member.full_name || member.username || member.email.split('@')[0]).toLowerCase(),
      weight: 1,
      fuzzy: true,
    },
    { text: member.email.toLowerCase(), weight: 0.6, fuzzy: true },
  ]);

  // Filter invites based on search query
  const filteredInvites = fuzzyFilter(invites, searchQuery, (invite) => [
    { text: invite.email.toLowerCase(), weight: 1, fuzzy: true },
  ]);

  // Current user's role for RBAC logic
  const userRole = organization.user_role as 'owner' | 'admin' | 'member';

  // Determine if current user can manage a specific member
  const canManageMember = (memberRole: string) => {
    if (!canEdit) return false;
    if (memberRole === 'owner') return false; // Can't manage owners
    if (userRole === 'owner') return true; // Owners can manage everyone else
    if (userRole === 'admin' && memberRole === 'member') return true; // Admins can manage members
    return false;
  };

  useEffect(() => {
    setName(organization.name);
  }, [organization.name]);

  useEffect(() => {
    if (isEditingName && nameInputRef.current) {
      nameInputRef.current.focus();
      nameInputRef.current.select();
    }
  }, [isEditingName]);

  const handleSaveName = async () => {
    if (name.trim() && name !== organization.name) {
      await onUpdate({ name: name.trim() });
    }
    setIsEditingName(false);
  };

  const handleCancelEdit = () => {
    setName(organization.name);
    setIsEditingName(false);
  };

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.type.startsWith('image/')) {
      toast.error('Please select an image file');
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      toast.error('Image must be less than 2MB');
      return;
    }

    setUploading(true);
    const reader = new FileReader();
    reader.onload = async () => {
      const base64 = (reader.result as string).split(',')[1];
      await onUploadIcon(base64, file.type);
      setUploading(false);
    };
    reader.onerror = () => {
      toast.error('Failed to read file');
      setUploading(false);
    };
    reader.readAsDataURL(file);

    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    await onInvite(inviteEmail.trim(), inviteRole);
    setInviteEmail('');
    setInviteRole('member');
  };

  const getRoleBadge = (role: string) => {
    switch (role) {
      case 'owner': return { bg: 'bg-amber-500/10', text: 'text-amber-600 dark:text-amber-400/90', label: 'Owner' };
      case 'admin': return { bg: 'bg-blue-500/10', text: 'text-blue-600 dark:text-blue-400/90', label: 'Admin' };
      default: return { bg: 'bg-foreground/[0.04]', text: 'text-muted-foreground dark:text-white/50', label: 'Member' };
    }
  };

  return (
    <div className="space-y-8">
      {/* Organization Info Card */}
      <div className="p-5 bg-card dark:bg-foreground/[0.02] border border-border dark:border-white/[0.06] rounded-xl space-y-5">
        {/* Icon + Name Row */}
        <div className="flex items-start gap-4">
          {/* Icon */}
          <div className="relative group">
            {organization.icon_url ? (
              <img
                src={organization.icon_url}
                alt=""
                className="w-14 h-14 rounded-full object-cover"
              />
            ) : (
              <div className="w-14 h-14 rounded-full bg-blue-500/15 flex items-center justify-center">
                <Building2 className="w-6 h-6 text-blue-600 dark:text-blue-400/80" />
              </div>
            )}
            {canEdit && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleFileSelect}
                  className="hidden"
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploading}
                  className="absolute inset-0 bg-black/60 rounded-full opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
                >
                  {uploading ? (
                    <Loader2 className="w-4 h-4 animate-spin text-muted-foreground dark:text-white/70" />
                  ) : (
                    <Upload className="w-4 h-4 text-muted-foreground dark:text-white/70" />
                  )}
                </button>
              </>
            )}
          </div>

          {/* Name + Slug */}
          <div className="flex-1 min-w-0">
            {isEditingName ? (
              <div className="flex items-center gap-2">
                <input
                  ref={nameInputRef}
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleSaveName();
                    if (e.key === 'Escape') handleCancelEdit();
                  }}
                  className="flex-1 bg-foreground/[0.04] border border-input dark:border-white/10 rounded-lg px-3 py-1.5 text-sm text-foreground/90 focus:outline-none focus:border-muted-foreground/40 dark:focus:border-white/20"
                />
                <button
                  onClick={handleSaveName}
                  disabled={loading}
                  className="p-1.5 text-green-600 dark:text-green-400/80 hover:text-green-700 dark:hover:text-green-400 hover:bg-green-500/10 rounded-md transition-colors"
                >
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                </button>
                <button
                  onClick={handleCancelEdit}
                  className="p-1.5 text-muted-foreground dark:text-white/40 hover:text-foreground/80 hover:bg-foreground/[0.04] rounded-md transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <h3 className="text-base font-medium text-foreground/90 truncate">{organization.name}</h3>
                {canEdit && (
                  <button
                    onClick={() => setIsEditingName(true)}
                    className="flex items-center gap-1 px-1.5 py-0.5 text-xs text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:bg-foreground/[0.06] rounded transition-colors"
                  >
                    <Pencil className="w-3 h-3" />
                    <span>Edit</span>
                  </button>
                )}
              </div>
            )}
            {!isPersonalWorkspace && (
              <p className="text-xs text-muted-foreground/70 dark:text-white/30 mt-0.5">{organization.slug}</p>
            )}
          </div>

          {/* Subscription Badge */}
          <div className={cn(
            "px-2.5 py-1 rounded-md text-xs font-medium",
            organization.subscription_tier === 'enterprise' && "bg-purple-500/15 text-purple-600 dark:text-purple-400/90",
            organization.subscription_tier === 'pro' && "bg-blue-500/15 text-blue-600 dark:text-blue-400/90",
            organization.subscription_tier === 'plus' && "bg-amber-500/15 text-amber-600 dark:text-amber-400/90",
            organization.subscription_tier === 'free' && "bg-foreground/[0.04] text-muted-foreground dark:text-white/40"
          )}>
            {organization.subscription_tier}
          </div>
        </div>
      </div>

      {/* Members Section */}
      <div className="space-y-3">
        {/* Header with search - both sides have matching height */}
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2 h-9">
            <h4 className="text-sm font-medium text-muted-foreground dark:text-white/70">Members</h4>
            <span className="text-xs text-muted-foreground/70 dark:text-white/30 bg-foreground/[0.04] px-1.5 py-0.5 rounded tabular-nums">{members.length}</span>
          </div>

          {/* Modern search input */}
          <div className="relative group">
            <Search className={cn(
              "absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 transition-colors",
              searchQuery ? "text-muted-foreground dark:text-white/50" : "text-muted-foreground/60 dark:text-white/25"
            )} />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search members..."
              className={cn(
                "w-48 h-9 pl-9 pr-8 text-sm rounded-lg transition-all duration-200",
                "bg-foreground/[0.03] border border-input dark:border-white/[0.06]",
                "text-foreground/80 placeholder:text-[hsl(var(--placeholder))]",
                "focus:outline-none focus:bg-foreground/[0.05] focus:border-muted-foreground/40 dark:focus:border-white/15 focus:ring-1 focus:ring-ring/10 dark:focus:ring-white/10"
              )}
            />
            {/* Clear button */}
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 text-muted-foreground/70 dark:text-white/30 hover:text-foreground/80 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Invite Member - more compact */}
        {canEdit && (
          <div className="flex gap-2">
            <input
              type="email"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleInvite()}
              placeholder="Invite by email..."
              className="flex-1 bg-foreground/[0.03] border border-input dark:border-white/[0.06] rounded-md px-3 py-1.5 text-sm text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-muted-foreground/40 dark:focus:border-white/10 transition-colors"
            />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="flex items-center gap-1.5 bg-foreground/[0.03] border border-input dark:border-white/[0.06] rounded-md px-2.5 py-1.5 text-xs text-muted-foreground dark:text-white/60 hover:text-foreground/80 hover:border-muted-foreground/30 dark:hover:border-white/10 focus:outline-none focus:border-muted-foreground/40 dark:focus:border-white/15 transition-colors">
                  <span className="capitalize">{inviteRole}</span>
                  <ChevronDown className="w-3 h-3 text-muted-foreground dark:text-white/40" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="end"
                sideOffset={4}
                className={cn(
                  "min-w-[100px] p-1",
                  "bg-popover/98 backdrop-blur-xl",
                  "border border-border dark:border-white/10",
                  "shadow-xl dark:shadow-black/40",
                  "rounded-lg"
                )}
              >
                <DropdownMenuItem
                  onClick={() => setInviteRole('member')}
                  className={cn(
                    "flex items-center justify-between px-2.5 py-1.5 rounded-md cursor-pointer text-xs",
                    "transition-colors duration-100",
                    inviteRole === 'member'
                      ? "bg-foreground/[0.06] text-accent-foreground"
                      : "text-foreground/80 hover:bg-foreground/[0.04]"
                  )}
                >
                  <span>Member</span>
                  {inviteRole === 'member' && <Check className="w-3 h-3 text-muted-foreground dark:text-white/50" />}
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => setInviteRole('admin')}
                  className={cn(
                    "flex items-center justify-between px-2.5 py-1.5 rounded-md cursor-pointer text-xs",
                    "transition-colors duration-100",
                    inviteRole === 'admin'
                      ? "bg-foreground/[0.06] text-accent-foreground"
                      : "text-foreground/80 hover:bg-foreground/[0.04]"
                  )}
                >
                  <span>Admin</span>
                  {inviteRole === 'admin' && <Check className="w-3 h-3 text-muted-foreground dark:text-white/50" />}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <button
              onClick={handleInvite}
              disabled={!inviteEmail.trim() || loading}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
                inviteEmail.trim()
                  ? "bg-foreground/90 text-primary-foreground hover:bg-primary"
                  : "bg-foreground/[0.04] text-muted-foreground/70 dark:text-white/30 cursor-not-allowed"
              )}
            >
              <UserPlus className="w-3 h-3" />
              Invite
            </button>
          </div>
        )}

        {/* Scrollable members container */}
        <div className="max-h-[400px] overflow-y-auto -mx-1 px-1">
          {/* Pending Invites - compact */}
          {filteredInvites.length > 0 && (
            <div className="mb-2">
              {filteredInvites.map((invite) => (
                <div
                  key={invite.id}
                  className="flex items-center gap-2 px-2 py-1.5 hover:bg-foreground/[0.02] rounded transition-colors group"
                >
                  <div className="w-6 h-6 rounded-full bg-foreground/[0.04] border border-dashed border-border dark:border-white/10 flex items-center justify-center flex-shrink-0">
                    <span className="text-[9px] text-muted-foreground/70 dark:text-white/30">?</span>
                  </div>
                  <div className="flex-1 min-w-0 flex items-center gap-2">
                    <span className="text-sm text-muted-foreground dark:text-white/50 truncate">{invite.email}</span>
                    <span className="text-[10px] text-muted-foreground/60 dark:text-white/25 flex-shrink-0">pending</span>
                  </div>
                  <span className={cn(
                    "px-1.5 py-0.5 rounded text-[10px] flex-shrink-0",
                    invite.role === 'admin' ? "bg-blue-500/10 text-blue-600/80 dark:text-blue-400/70" : "bg-foreground/[0.04] text-muted-foreground dark:text-white/40"
                  )}>
                    {invite.role}
                  </span>
                  {canEdit && (
                    <button
                      onClick={() => onRevokeInvite(invite.id)}
                      className="p-1 text-muted-foreground/50 dark:text-white/20 hover:text-red-600/80 dark:hover:text-red-400/80 opacity-0 group-hover:opacity-100 transition-all flex-shrink-0"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Members List - compact */}
          <div className="space-y-0.5">
            {filteredMembers.map((member) => {
              const badge = getRoleBadge(member.role);
              const canManage = canManageMember(member.role);

              return (
                <div
                  key={member.id}
                  className="flex items-center gap-2 px-2 py-1.5 hover:bg-foreground/[0.02] rounded transition-colors group"
                >
                  {/* Avatar */}
                  {member.avatar_url ? (
                    <img src={member.avatar_url} alt="" className="w-6 h-6 rounded-full flex-shrink-0" referrerPolicy="no-referrer" />
                  ) : (
                    <div className="w-6 h-6 rounded-full bg-foreground/[0.06] flex items-center justify-center flex-shrink-0">
                      <span className="text-[9px] text-muted-foreground dark:text-white/50">
                        {member.email.slice(0, 2).toUpperCase()}
                      </span>
                    </div>
                  )}

                  {/* Name + Email inline */}
                  <div className="flex-1 min-w-0 flex items-center gap-2">
                    <span className="text-sm text-foreground/80 truncate">
                      {member.full_name || member.username || member.email.split('@')[0]}
                    </span>
                    <span className="text-xs text-muted-foreground/70 dark:text-white/30 truncate hidden sm:block">
                      {member.email}
                    </span>
                  </div>

                  {/* Remove button - to the left of role dropdown */}
                  {canManage && (
                    <button
                      onClick={() => setConfirmRemove(member)}
                      className="px-2 py-0.5 text-[10px] text-red-600/70 hover:text-red-600 dark:text-red-400/60 dark:hover:text-red-400 hover:bg-red-500/10 rounded transition-colors flex-shrink-0"
                    >
                      Remove
                    </button>
                  )}

                  {/* Role - dropdown if can manage, badge otherwise */}
                  {canManage ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          disabled={loading}
                          className="flex items-center gap-1 bg-transparent border border-border dark:border-white/[0.06] rounded px-1.5 py-0.5 text-[10px] text-muted-foreground dark:text-white/50 hover:text-foreground/80 hover:border-muted-foreground/30 dark:hover:border-white/10 focus:outline-none focus:border-muted-foreground/40 dark:focus:border-white/15 cursor-pointer transition-colors flex-shrink-0"
                        >
                          <span className="capitalize">{member.role}</span>
                          <ChevronDown className="w-2.5 h-2.5 text-muted-foreground/70 dark:text-white/30" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align="end"
                        sideOffset={4}
                        className={cn(
                          "min-w-[90px] p-1",
                          "bg-popover/98 backdrop-blur-xl",
                          "border border-border dark:border-white/10",
                          "shadow-xl dark:shadow-black/40",
                          "rounded-lg"
                        )}
                      >
                        <DropdownMenuItem
                          onClick={() => onUpdateRole(member.user_id, 'member')}
                          className={cn(
                            "flex items-center justify-between px-2 py-1 rounded-md cursor-pointer text-[10px]",
                            "transition-colors duration-100",
                            member.role === 'member'
                              ? "bg-foreground/[0.06] text-accent-foreground"
                              : "text-foreground/80 hover:bg-foreground/[0.04]"
                          )}
                        >
                          <span>Member</span>
                          {member.role === 'member' && <Check className="w-2.5 h-2.5 text-muted-foreground dark:text-white/50" />}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => onUpdateRole(member.user_id, 'admin')}
                          className={cn(
                            "flex items-center justify-between px-2 py-1 rounded-md cursor-pointer text-[10px]",
                            "transition-colors duration-100",
                            member.role === 'admin'
                              ? "bg-foreground/[0.06] text-accent-foreground"
                              : "text-foreground/80 hover:bg-foreground/[0.04]"
                          )}
                        >
                          <span>Admin</span>
                          {member.role === 'admin' && <Check className="w-2.5 h-2.5 text-muted-foreground dark:text-white/50" />}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : (
                    <span className={cn("px-1.5 py-0.5 rounded text-[10px] flex-shrink-0", badge.bg, badge.text)}>
                      {badge.label}
                    </span>
                  )}
                </div>
              );
            })}

            {/* Empty state for search */}
            {filteredMembers.length === 0 && searchQuery && (
              <div className="py-6 text-center">
                <p className="text-xs text-muted-foreground/70 dark:text-white/30">No members match "{searchQuery}"</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Confirm Remove Dialog */}
      <Dialog open={!!confirmRemove} onOpenChange={() => setConfirmRemove(null)}>
        <DialogContent className="bg-sunken border-border text-foreground max-w-md p-6">
          <DialogHeader className="pb-2">
            <DialogTitle className="text-xl text-foreground flex items-center gap-2.5">
              <div className="p-2 bg-red-500/10 rounded-full">
                <AlertTriangle className="h-5 w-5 text-red-600 dark:text-red-400" />
              </div>
              Remove Member
            </DialogTitle>
            <DialogDescription className="text-[15px] text-foreground/80 leading-relaxed pt-4">
              Are you sure you want to remove{' '}
              <span className="font-semibold text-foreground">{confirmRemove?.email}</span>?
            </DialogDescription>
          </DialogHeader>

          <div className="py-2 pb-4">
            <p className="text-sm text-muted-foreground dark:text-zinc-500 leading-relaxed">
              They will lose access to all shared workflows, databases, and credentials.
            </p>
          </div>

          <div className="flex justify-between pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmRemove(null)}
              className="h-10 bg-transparent text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] border border-border hover:border-muted-foreground/30 dark:hover:border-zinc-700 rounded-md"
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => {
                if (confirmRemove) {
                  onRemoveMember(confirmRemove.user_id);
                  setConfirmRemove(null);
                }
              }}
              className="h-10 bg-primary hover:bg-primary text-primary-foreground font-medium rounded-md border-0 shadow-[0_2.5px_0_0_#a0a0a0] hover:shadow-[0_1px_0_0_#a0a0a0] hover:translate-y-[1.5px] active:shadow-none active:translate-y-[2.5px] transition-all duration-100 disabled:opacity-40 min-w-[100px]"
            >
              Remove
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// SSO Tab - Refined configuration interface
function SSOTab({ organization, organizationId, onUpdate }: {
  organization: Organization;
  organizationId: string;
  onUpdate: () => void;
}) {
  const { configureSSO, disableSSO, getSSOInfo, loading } = useOrganization();
  const [ssoInfo, setSsoInfo] = useState<{ sp_entity_id: string; sp_acs_url: string; sp_metadata_url: string } | null>(null);
  const [domain, setDomain] = useState(organization.sso_domain || '');
  const [metadataUrl, setMetadataUrl] = useState(organization.sso_metadata_url || '');
  const [configuring, setConfiguring] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    const fetchSSOInfo = async () => {
      const info = await getSSOInfo(organizationId);
      if (info) setSsoInfo(info);
    };
    fetchSSOInfo();
  }, [organizationId, getSSOInfo]);

  useEffect(() => {
    setDomain(organization.sso_domain || '');
    setMetadataUrl(organization.sso_metadata_url || '');
  }, [organization.sso_domain, organization.sso_metadata_url]);

  // Compute full SSO login URL
  const publicUrl = import.meta.env.VITE_PUBLIC_URL || (typeof window !== 'undefined' ? window.location.origin : '');
  const ssoLoginUrl = `${publicUrl}/auth/sso?org=${organization.slug}`;

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopied(label);
    toast.success(`Copied`);
    setTimeout(() => setCopied(null), 2000);
  };

  const handleConfigure = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!metadataUrl.trim()) {
      toast.error('Metadata URL is required');
      return;
    }

    setConfiguring(true);
    // Domain is optional - pass empty string if not provided
    const result = await configureSSO(organizationId, domain.trim() || '', metadataUrl.trim());
    setConfiguring(false);

    if (result?.success) {
      toast.success('SSO configured');
      onUpdate();
    }
  };

  const handleDisable = async () => {
    setDisabling(true);
    const success = await disableSSO(organizationId);
    setDisabling(false);

    if (success) {
      toast.success('SSO disabled');
      setDomain('');
      setMetadataUrl('');
      onUpdate();
    }
  };

  return (
    <div className="space-y-8">
      {/* Status + Configuration */}
      <div className="space-y-6">
        {/* SSO Login URL - always show when org has a slug */}
        <div
          onClick={() => copyToClipboard(ssoLoginUrl, 'SSO URL')}
          className={cn(
            "group p-4 rounded-xl cursor-pointer transition-all duration-150",
            "bg-foreground/[0.02] hover:bg-foreground/[0.04]",
            "border border-border dark:border-white/[0.04] hover:border-muted-foreground/30 dark:hover:border-white/[0.08]"
          )}
        >
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1 min-w-0">
              <p className="text-[11px] text-muted-foreground dark:text-white/40 uppercase tracking-wide mb-1">SSO Login URL</p>
              <p className="text-[13px] text-muted-foreground dark:text-white/70 font-mono truncate">
                {ssoLoginUrl}
              </p>
            </div>
            <div className="flex items-center gap-3 flex-shrink-0">
              {organization.sso_enabled && (
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-emerald-500 dark:bg-emerald-400/80" />
                  <span className="text-xs text-muted-foreground dark:text-white/50">Active</span>
                </div>
              )}
              <div className={cn(
                "w-6 h-6 flex items-center justify-center rounded-md",
                "opacity-0 group-hover:opacity-100 transition-opacity",
                copied === 'SSO URL' && "opacity-100"
              )}>
                {copied === 'SSO URL' ? (
                  <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400/80" />
                ) : (
                  <Copy className="w-3.5 h-3.5 text-muted-foreground dark:text-white/40" />
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Inline status indicator when enabled */}
        {organization.sso_enabled && (
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground dark:text-white/50">
              {organization.sso_domain ? (
                <>Auto-join domain: <span className="text-foreground/80">@{organization.sso_domain}</span></>
              ) : (
                <>SSO users join via <span className="text-foreground/80">/auth/sso?org={organization.slug}</span></>
              )}
            </span>
            <button
              onClick={handleDisable}
              disabled={disabling}
              className={cn(
                "text-xs text-muted-foreground dark:text-white/40 hover:text-foreground/80 transition-colors",
                disabling && "opacity-50"
              )}
            >
              {disabling ? 'Disabling...' : 'Disable SSO'}
            </button>
          </div>
        )}

        {/* Configuration Form */}
        <form onSubmit={handleConfigure} className="space-y-5">
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-[13px] text-muted-foreground dark:text-white/60 block">
                Email Domain <span className="text-muted-foreground/70 dark:text-white/30">(optional)</span>
              </label>
              <input
                type="text"
                value={domain}
                onChange={(e) => setDomain(e.target.value.toLowerCase().replace(/^@/, ''))}
                placeholder="acme.com"
                className={cn(
                  "w-full bg-foreground/[0.03] border border-input dark:border-white/[0.06] rounded-xl px-4 py-3",
                  "text-[15px] text-foreground/90 placeholder:text-[hsl(var(--placeholder))]",
                  "focus:outline-none focus:border-muted-foreground/40 dark:focus:border-white/15 focus:bg-foreground/[0.04]",
                  "transition-all duration-150"
                )}
              />
              <p className="text-[11px] text-muted-foreground/70 dark:text-white/30 leading-relaxed">
                {domain
                  ? `Users with @${domain} emails can be auto-added to this organization`
                  : 'If set, users with matching email domains can be auto-added'
                }
              </p>
            </div>

            <div className="space-y-2">
              <label className="text-[13px] text-muted-foreground dark:text-white/60 block">Metadata URL</label>
              <input
                type="url"
                value={metadataUrl}
                onChange={(e) => setMetadataUrl(e.target.value)}
                placeholder="https://idp.example.com/metadata"
                disabled={organization.sso_enabled}
                className={cn(
                  "w-full bg-foreground/[0.03] border border-input dark:border-white/[0.06] rounded-xl px-4 py-3",
                  "text-[15px] text-foreground/90 placeholder:text-[hsl(var(--placeholder))]",
                  "focus:outline-none focus:border-muted-foreground/40 dark:focus:border-white/15 focus:bg-foreground/[0.04]",
                  "transition-all duration-150",
                  organization.sso_enabled && "opacity-50 cursor-not-allowed"
                )}
              />
              <p className="text-[11px] text-muted-foreground/70 dark:text-white/30 leading-relaxed">
                {organization.sso_enabled
                  ? 'Disable SSO to change the metadata URL'
                  : 'SAML metadata endpoint from Okta, Azure AD, or your identity provider'
                }
              </p>
            </div>
          </div>

          <button
            type="submit"
            disabled={configuring || loading || !metadataUrl.trim()}
            className={cn(
              "w-full py-3 rounded-full text-sm font-medium transition-all duration-150",
              metadataUrl.trim()
                ? "bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm"
                : "bg-foreground/[0.04] text-muted-foreground/70 dark:text-white/30 cursor-not-allowed"
            )}
          >
            {configuring ? (
              <span className="flex items-center justify-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                {organization.sso_enabled ? 'Updating...' : 'Enabling...'}
              </span>
            ) : (
              organization.sso_enabled ? 'Update Configuration' : 'Enable SSO'
            )}
          </button>

          {/* Subtle testing hint */}
          {!organization.sso_enabled && (
            <p className="text-[11px] text-muted-foreground/60 dark:text-white/25 text-center">
              For testing, use <span className="text-muted-foreground dark:text-white/40">mocksaml.com/api/saml/metadata</span>
            </p>
          )}
        </form>
      </div>

      {/* Service Provider Details - Collapsed section */}
      {ssoInfo && (
        <div className="pt-6 border-t border-border dark:border-white/[0.04]">
          <div className="mb-4">
            <h4 className="text-[13px] text-muted-foreground dark:text-white/50 font-medium">Service Provider</h4>
            <p className="text-[11px] text-muted-foreground/60 dark:text-white/25 mt-0.5">
              Configure in your identity provider
            </p>
          </div>

          <div className="space-y-2">
            <CopyableField
              label="Entity ID"
              value={ssoInfo.sp_entity_id}
              onCopy={() => copyToClipboard(ssoInfo.sp_entity_id, 'Entity ID')}
              copied={copied === 'Entity ID'}
            />
            <CopyableField
              label="ACS URL"
              value={ssoInfo.sp_acs_url}
              onCopy={() => copyToClipboard(ssoInfo.sp_acs_url, 'ACS URL')}
              copied={copied === 'ACS URL'}
            />
            <CopyableField
              label="Metadata"
              value={ssoInfo.sp_metadata_url}
              onCopy={() => copyToClipboard(ssoInfo.sp_metadata_url, 'Metadata')}
              copied={copied === 'Metadata'}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function CopyableField({ label, value, onCopy, copied }: {
  label: string;
  value: string;
  onCopy: () => void;
  copied: boolean;
}) {
  return (
    <div
      onClick={onCopy}
      className={cn(
        "group flex items-center gap-4 px-4 py-3 rounded-xl cursor-pointer",
        "bg-foreground/[0.02] hover:bg-foreground/[0.04]",
        "border border-transparent hover:border-border dark:hover:border-white/[0.06]",
        "transition-all duration-150"
      )}
    >
      <span className="text-[11px] text-muted-foreground/70 dark:text-white/35 w-16 flex-shrink-0">{label}</span>
      <span className="text-[13px] text-muted-foreground dark:text-white/60 font-mono truncate flex-1">{value}</span>
      <div className={cn(
        "w-6 h-6 flex items-center justify-center rounded-md",
        "opacity-0 group-hover:opacity-100 transition-opacity",
        copied && "opacity-100"
      )}>
        {copied ? (
          <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400/80" />
        ) : (
          <Copy className="w-3.5 h-3.5 text-muted-foreground dark:text-white/40" />
        )}
      </div>
    </div>
  );
}


function DangerZoneTab({ organization, members, onTransferOwnership, onDelete }: {
  organization: Organization;
  members: OrganizationMember[];
  onTransferOwnership: (userId: string) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const [confirmName, setConfirmName] = useState('');
  const [showConfirm, setShowConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Transfer ownership state
  const [selectedMemberId, setSelectedMemberId] = useState('');
  const [showTransferConfirm, setShowTransferConfirm] = useState(false);
  const [transferConfirmEmail, setTransferConfirmEmail] = useState('');
  const [transferring, setTransferring] = useState(false);
  const [transferSearch, setTransferSearch] = useState('');
  const [transferDropdownOpen, setTransferDropdownOpen] = useState(false);
  const transferSearchRef = useRef<HTMLInputElement>(null);

  const eligibleMembers = members.filter(m => m.role !== 'owner');
  const filteredEligible = fuzzyFilter(eligibleMembers, transferSearch, m => [
    { text: (m.full_name || '').toLowerCase(), weight: 1, fuzzy: true },
    { text: m.email.toLowerCase(), weight: 0.6, fuzzy: true },
  ]);
  const selectedMember = eligibleMembers.find(m => m.user_id === selectedMemberId);

  const handleTransfer = async () => {
    if (!selectedMember || transferConfirmEmail !== selectedMember.email) return;
    setTransferring(true);
    await onTransferOwnership(selectedMemberId);
    setTransferring(false);
    setShowTransferConfirm(false);
    setTransferConfirmEmail('');
    setSelectedMemberId('');
  };

  const handleDelete = async () => {
    if (confirmName !== organization.name) return;
    setDeleting(true);
    await onDelete();
    setDeleting(false);
  };

  const isConfirmValid = confirmName === organization.name;
  const isTransferConfirmValid = selectedMember && transferConfirmEmail === selectedMember.email;

  return (
    <div className="space-y-8">
      {/* Transfer Ownership Section */}
      <div className="p-5 bg-amber-500/[0.04] border border-amber-500/10 rounded-xl">
        <div className="flex gap-4">
          <div className="flex-shrink-0">
            <div className="w-10 h-10 rounded-full bg-amber-500/10 flex items-center justify-center">
              <Shield className="w-5 h-5 text-amber-600 dark:text-amber-400" />
            </div>
          </div>
          <div className="space-y-4 flex-1">
            <div className="space-y-2">
              <h3 className="text-base font-medium text-amber-600 dark:text-amber-400">Transfer Ownership</h3>
              <p className="text-sm text-muted-foreground dark:text-white/50 leading-relaxed">
                Transfer this organization to another member. You will be demoted to admin.
                The new owner will control this organization's instance-managed resources.
              </p>
            </div>

            {eligibleMembers.length === 0 ? (
              <p className="text-sm text-muted-foreground dark:text-white/40">
                No eligible members to transfer to. Invite a member first.
              </p>
            ) : !showTransferConfirm ? (
              <div className="flex items-center gap-3">
                <div className="relative max-w-xs flex-1">
                  {selectedMember && !transferDropdownOpen ? (
                    <button
                      onClick={() => {
                        setTransferDropdownOpen(true);
                        setTransferSearch('');
                        setTimeout(() => transferSearchRef.current?.focus(), 0);
                      }}
                      className="w-full bg-foreground/[0.03] border border-input dark:border-white/[0.06] rounded-xl px-4 py-2.5 text-sm text-foreground/90 text-left focus:outline-none focus:border-muted-foreground/40 dark:focus:border-white/15 transition-all duration-150 flex items-center justify-between"
                    >
                      <span>{selectedMember.full_name || selectedMember.email} <span className="text-muted-foreground dark:text-white/40">({selectedMember.role})</span></span>
                      <ChevronDown className="w-3.5 h-3.5 text-muted-foreground dark:text-white/40" />
                    </button>
                  ) : (
                    <>
                      <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/70 dark:text-white/30" />
                      <input
                        ref={transferSearchRef}
                        type="text"
                        value={transferSearch}
                        onChange={(e) => {
                          setTransferSearch(e.target.value);
                          setTransferDropdownOpen(true);
                        }}
                        onFocus={() => setTransferDropdownOpen(true)}
                        placeholder="Search members..."
                        className="w-full bg-foreground/[0.03] border border-input dark:border-white/[0.06] rounded-xl pl-9 pr-4 py-2.5 text-sm text-foreground/90 placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-muted-foreground/40 dark:focus:border-white/15 transition-all duration-150"
                      />
                    </>
                  )}
                  {transferDropdownOpen && (
                    <>
                      <div className="fixed inset-0 z-10" onClick={() => setTransferDropdownOpen(false)} />
                      <div className="absolute z-20 mt-1 w-full bg-popover border border-border dark:border-white/[0.08] rounded-xl shadow-xl max-h-48 overflow-y-auto">
                        {filteredEligible.length === 0 ? (
                          <div className="px-4 py-3 text-xs text-muted-foreground/70 dark:text-white/30">No members found</div>
                        ) : (
                          filteredEligible.map(m => (
                            <button
                              key={m.user_id}
                              onClick={() => {
                                setSelectedMemberId(m.user_id);
                                setTransferDropdownOpen(false);
                                setTransferSearch('');
                              }}
                              className={cn(
                                "w-full px-4 py-2.5 text-left text-sm transition-colors flex items-center gap-3 hover:bg-foreground/[0.06]",
                                m.user_id === selectedMemberId ? "bg-foreground/[0.04]" : ""
                              )}
                            >
                              <div className="min-w-0 flex-1">
                                <div className="text-foreground/90 truncate">{m.full_name || m.email.split('@')[0]}</div>
                                <div className="text-xs text-muted-foreground dark:text-white/40 truncate">{m.email}</div>
                              </div>
                              <span className="text-xs text-muted-foreground/70 dark:text-white/30 flex-shrink-0">{m.role}</span>
                            </button>
                          ))
                        )}
                      </div>
                    </>
                  )}
                </div>
                <button
                  onClick={() => setShowTransferConfirm(true)}
                  disabled={!selectedMemberId}
                  className={cn(
                    "py-2.5 px-5 rounded-full text-sm font-medium transition-colors border",
                    selectedMemberId
                      ? "bg-amber-500/10 hover:bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/20 hover:border-amber-500/30"
                      : "bg-foreground/[0.02] text-muted-foreground/70 dark:text-white/30 border-border dark:border-white/[0.06] cursor-not-allowed"
                  )}
                >
                  Transfer
                </button>
              </div>
            ) : (
              <div className="space-y-4 p-5 bg-card dark:bg-foreground/[0.02] border border-border dark:border-white/[0.06] rounded-xl max-w-sm">
                <div className="space-y-2">
                  <label className="text-sm text-muted-foreground dark:text-white/60 block">
                    Type <span className="font-mono text-foreground/80">{selectedMember?.email}</span> to confirm
                  </label>
                  <input
                    type="text"
                    value={transferConfirmEmail}
                    onChange={(e) => setTransferConfirmEmail(e.target.value)}
                    placeholder={selectedMember?.email}
                    autoFocus
                    className={cn(
                      "w-full bg-foreground/[0.03] border rounded-xl px-4 py-2.5",
                      "text-sm text-foreground/90 placeholder:text-[hsl(var(--placeholder))]",
                      "focus:outline-none transition-all duration-150",
                      transferConfirmEmail && !isTransferConfirmValid
                        ? "border-amber-500/30 focus:border-amber-500/50"
                        : "border-input dark:border-white/[0.06] focus:border-muted-foreground/40 dark:focus:border-white/15"
                    )}
                  />
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      setShowTransferConfirm(false);
                      setTransferConfirmEmail('');
                    }}
                    className="px-4 py-2 bg-foreground/[0.04] hover:bg-foreground/[0.06] text-muted-foreground dark:text-white/60 rounded-full text-sm font-medium transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleTransfer}
                    disabled={!isTransferConfirmValid || transferring}
                    className={cn(
                      "px-4 py-2 rounded-full text-sm font-medium transition-colors flex items-center justify-center gap-2",
                      isTransferConfirmValid
                        ? "bg-amber-600 hover:bg-amber-700 text-white"
                        : "bg-amber-500/10 text-amber-400/40 cursor-not-allowed"
                    )}
                  >
                    {transferring ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Transferring...
                      </>
                    ) : (
                      'Confirm Transfer'
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Delete Organization Section */}
      <div className="p-5 bg-red-500/[0.04] border border-red-500/10 rounded-xl">
        <div className="flex gap-4">
          <div className="flex-shrink-0">
            <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center">
              <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
            </div>
          </div>
          <div className="space-y-2">
            <h3 className="text-base font-medium text-red-600 dark:text-red-400">Delete Organization</h3>
            <p className="text-sm text-muted-foreground dark:text-white/50 leading-relaxed">
              Once you delete an organization, there is no going back. This action is permanent and cannot be undone.
            </p>
          </div>
        </div>
      </div>

      {/* Consequences List */}
      <div className="space-y-3">
        <h4 className="text-sm text-muted-foreground dark:text-white/40">Deleting this organization will:</h4>
        <ul className="space-y-2 text-sm text-muted-foreground dark:text-white/60">
          <li className="flex items-start gap-2">
            <span className="text-red-400/60 mt-0.5">•</span>
            Remove all members from the organization
          </li>
          <li className="flex items-start gap-2">
            <span className="text-red-400/60 mt-0.5">•</span>
            Delete all shared workflows and their execution history
          </li>
          <li className="flex items-start gap-2">
            <span className="text-red-400/60 mt-0.5">•</span>
            Delete all shared databases and their data
          </li>
          <li className="flex items-start gap-2">
            <span className="text-red-400/60 mt-0.5">•</span>
            Remove all stored credentials and API keys
          </li>
          {organization.sso_enabled && (
            <li className="flex items-start gap-2">
              <span className="text-red-400/60 mt-0.5">•</span>
              Disable and remove SSO configuration
            </li>
          )}
        </ul>
      </div>

      {/* Delete Button */}
      {!showConfirm ? (
        <button
          onClick={() => setShowConfirm(true)}
          className="py-2.5 px-5 bg-red-500/10 hover:bg-red-500/15 text-red-600 dark:text-red-400 rounded-full text-sm font-medium transition-colors border border-red-500/20 hover:border-red-500/30"
        >
          I understand, delete this organization
        </button>
      ) : (
        <div className="space-y-4 p-5 bg-card dark:bg-foreground/[0.02] border border-border dark:border-white/[0.06] rounded-xl max-w-sm">
          <div className="space-y-2">
            <label className="text-sm text-muted-foreground dark:text-white/60 block">
              Type <span className="font-mono text-foreground/80">{organization.name}</span> to confirm
            </label>
            <input
              type="text"
              value={confirmName}
              onChange={(e) => setConfirmName(e.target.value)}
              placeholder={organization.name}
              autoFocus
              className={cn(
                "w-full bg-foreground/[0.03] border rounded-xl px-4 py-2.5",
                "text-sm text-foreground/90 placeholder:text-[hsl(var(--placeholder))]",
                "focus:outline-none transition-all duration-150",
                confirmName && !isConfirmValid
                  ? "border-red-500/30 focus:border-red-500/50"
                  : "border-input dark:border-white/[0.06] focus:border-muted-foreground/40 dark:focus:border-white/15"
              )}
            />
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => {
                setShowConfirm(false);
                setConfirmName('');
              }}
              className="px-4 py-2 bg-foreground/[0.04] hover:bg-foreground/[0.06] text-muted-foreground dark:text-white/60 rounded-full text-sm font-medium transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={!isConfirmValid || deleting}
              className={cn(
                "px-4 py-2 rounded-full text-sm font-medium transition-colors flex items-center justify-center gap-2",
                isConfirmValid
                  ? "bg-red-600 hover:bg-red-700 text-white"
                  : "bg-red-500/10 text-red-400/40 cursor-not-allowed"
              )}
            >
              {deleting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Deleting...
                </>
              ) : (
                'Delete'
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
