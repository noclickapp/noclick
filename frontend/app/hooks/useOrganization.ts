/**
 * Hook for managing organization data and operations.
 * Provides methods for fetching organization info, managing members, invites, and SSO configuration.
 */

import { useState, useCallback } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';

// Organization types
export interface Organization {
  id: string;
  name: string;
  slug: string;
  icon_url: string | null;
  subscription_tier: string;
  sso_enabled: boolean;
  sso_domain: string | null;
  sso_metadata_url: string | null;
  settings: Record<string, unknown>;
  member_count?: number;
  user_role?: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface OrganizationMember {
  id: string;
  user_id: string;
  email: string;
  full_name: string | null;
  username: string | null;
  avatar_url: string | null;
  role: 'owner' | 'admin' | 'member';
  joined_via: 'sso' | 'invite' | 'creator';
  joined_at: string | null;
}

export interface OrganizationInvite {
  id: string;
  email: string;
  role: string;
  token?: string;
  expires_at: string | null;
  created_at: string | null;
}

export interface SSOInfo {
  sp_entity_id: string;
  sp_acs_url: string;
  sp_metadata_url: string;
}

// Response types from backend - using Record for socket response compatibility
interface OrganizationResponse {
  organization?: Organization;
  success?: boolean;
  message?: string;
  error?: string;
}

interface MembersResponse {
  members?: OrganizationMember[];
  error?: string;
}

interface InvitesResponse {
  invites?: OrganizationInvite[];
  error?: string;
}

interface InviteResponse {
  success?: boolean;
  invite?: OrganizationInvite;
  message?: string;
  error?: string;
}

interface SSOConfigResponse {
  success?: boolean;
  sso_provider_id?: string;
  domain?: string;
  sp_entity_id?: string;
  sp_acs_url?: string;
  message?: string;
  error?: string;
}

interface SSOInfoResponse extends SSOInfo {
  error?: string;
}

interface GenericResponse {
  success?: boolean;
  message?: string;
  organization_id?: string;
  organization_name?: string;
  error?: string;
}

interface InviteDetailsResponse {
  invite?: {
    email: string;
    role: string;
    expires_at: string | null;
    organization_id: string;
    organization_name: string;
    organization_icon_url: string | null;
    inviter_name: string;
  };
  error?: string;
}

export interface InviteDetails {
  email: string;
  role: string;
  expiresAt: string | null;
  organizationId: string;
  organizationName: string;
  organizationIconUrl: string | null;
  inviterName: string;
}

interface IconUploadResponse {
  success?: boolean;
  icon_url?: string;
  message?: string;
  error?: string;
}

interface MyOrganizationsResponse {
  organizations?: Array<{
    id: string;
    name: string;
    slug: string;
    icon_url: string | null;
    subscription_tier: 'free' | 'plus' | 'pro' | 'enterprise';
    role: 'owner' | 'admin' | 'member';
    is_primary: boolean;
  }>;
  error?: string;
}

export function useOrganization() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createOrganization = useCallback(async (
    name: string,
    slug?: string,
    settings?: Record<string, unknown>
  ): Promise<{ organization: Organization | null; error: string | null }> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:create',
        name,
        slug,
        settings,
      } as any) as OrganizationResponse;
      if (response.error) {
        setError(response.error);
        return { organization: null, error: response.error };
      }
      return { organization: response.organization ?? null, error: null };
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to create organization';
      setError(errorMsg);
      return { organization: null, error: errorMsg };
    } finally {
      setLoading(false);
    }
  }, []);

  const checkSlugAvailability = useCallback(async (slug: string): Promise<{
    available: boolean;
    slug: string;
    error?: string;
  } | null> => {
    try {
      const response = await sendEventAsync({
        event_name: 'organization:check_slug',
        slug,
      } as any) as { available: boolean; slug: string; error?: string };
      return response;
    } catch {
      return null;
    }
  }, []);

  const getOrganization = useCallback(async (organizationId: string): Promise<Organization | null> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:get',
        organization_id: organizationId,
      } as any) as OrganizationResponse;
      if (response.error) {
        setError(response.error);
        return null;
      }
      return response.organization ?? null;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get organization');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const updateOrganization = useCallback(async (
    organizationId: string,
    updates: { name?: string; settings?: Record<string, unknown> }
  ): Promise<Organization | null> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:update',
        organization_id: organizationId,
        ...updates,
      } as any) as OrganizationResponse;
      if (response.error) {
        setError(response.error);
        return null;
      }
      return response.organization ?? null;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update organization');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const deleteOrganization = useCallback(async (organizationId: string): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:delete',
        organization_id: organizationId,
      } as any) as GenericResponse;
      if (response.error) {
        setError(response.error);
        return false;
      }
      return response.success ?? false;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete organization');
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const transferOwnership = useCallback(async (organizationId: string, userId: string): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:transfer_ownership',
        organization_id: organizationId,
        user_id: userId,
      } as any) as GenericResponse;
      if (response.error) {
        setError(response.error);
        return false;
      }
      return response.success ?? false;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to transfer ownership');
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const listMembers = useCallback(async (organizationId: string): Promise<OrganizationMember[]> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:members:list',
        organization_id: organizationId,
      } as any) as MembersResponse;
      if (response.error) {
        setError(response.error);
        return [];
      }
      return response.members ?? [];
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to list members');
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  const inviteMember = useCallback(async (
    organizationId: string,
    email: string,
    role: 'admin' | 'member' = 'member'
  ): Promise<OrganizationInvite | null> => {
    setLoading(true);
    setError(null);
    try {
      // Pass current frontend URL so invite links work in dev/prod
      const frontendUrl = typeof window !== 'undefined' ? window.location.origin : undefined;
      const response = await sendEventAsync({
        event_name: 'organization:members:invite',
        organization_id: organizationId,
        email,
        role,
        frontend_url: frontendUrl,
      } as any) as InviteResponse;
      if (response.error) {
        setError(response.error);
        return null;
      }
      return response.invite ?? null;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to invite member');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const removeMember = useCallback(async (organizationId: string, userId: string): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:members:remove',
        organization_id: organizationId,
        user_id: userId,
      } as any) as GenericResponse;
      if (response.error) {
        setError(response.error);
        return false;
      }
      return response.success ?? false;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove member');
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const updateMemberRole = useCallback(async (
    organizationId: string,
    userId: string,
    role: 'admin' | 'member'
  ): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:members:update_role',
        organization_id: organizationId,
        user_id: userId,
        role,
      } as any) as GenericResponse;
      if (response.error) {
        setError(response.error);
        return false;
      }
      return response.success ?? false;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update member role');
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const listInvites = useCallback(async (organizationId: string): Promise<OrganizationInvite[]> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:invites:list',
        organization_id: organizationId,
      } as any) as InvitesResponse;
      if (response.error) {
        setError(response.error);
        return [];
      }
      return response.invites ?? [];
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to list invites');
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  const acceptInvite = useCallback(async (token: string): Promise<{ organizationId: string; organizationName: string } | null> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:invites:accept',
        token,
      } as any) as GenericResponse;
      if (response.error) {
        setError(response.error);
        return null;
      }
      if (response.success && response.organization_id && response.organization_name) {
        return {
          organizationId: response.organization_id,
          organizationName: response.organization_name,
        };
      }
      return null;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to accept invite');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const getInviteDetails = useCallback(async (token: string): Promise<InviteDetails | null> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:invites:get',
        token,
      } as any) as InviteDetailsResponse;
      if (response.error) {
        setError(response.error);
        return null;
      }
      if (response.invite) {
        return {
          email: response.invite.email,
          role: response.invite.role,
          expiresAt: response.invite.expires_at,
          organizationId: response.invite.organization_id,
          organizationName: response.invite.organization_name,
          organizationIconUrl: response.invite.organization_icon_url,
          inviterName: response.invite.inviter_name,
        };
      }
      return null;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get invite details');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const revokeInvite = useCallback(async (organizationId: string, inviteId: string): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:invites:revoke',
        organization_id: organizationId,
        invite_id: inviteId,
      } as any) as GenericResponse;
      if (response.error) {
        setError(response.error);
        return false;
      }
      return response.success ?? false;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to revoke invite');
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const configureSSO = useCallback(async (
    organizationId: string,
    domain: string,
    metadataUrl: string,
    attributeMapping?: Record<string, string>
  ): Promise<SSOConfigResponse | null> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:sso:configure',
        organization_id: organizationId,
        domain,
        metadata_url: metadataUrl,
        attribute_mapping: attributeMapping,
      } as any) as SSOConfigResponse;
      if (response.error) {
        setError(response.error);
        return null;
      }
      return response;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to configure SSO');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const disableSSO = useCallback(async (organizationId: string): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:sso:disable',
        organization_id: organizationId,
      } as any) as GenericResponse;
      if (response.error) {
        setError(response.error);
        return false;
      }
      return response.success ?? false;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to disable SSO');
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const getSSOInfo = useCallback(async (organizationId: string): Promise<SSOInfo | null> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:sso:info',
        organization_id: organizationId,
      } as any) as SSOInfoResponse;
      if (response.error) {
        setError(response.error);
        return null;
      }
      return {
        sp_entity_id: response.sp_entity_id,
        sp_acs_url: response.sp_acs_url,
        sp_metadata_url: response.sp_metadata_url,
      };
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to get SSO info');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const uploadIcon = useCallback(async (
    organizationId: string,
    imageData: string,
    contentType: string
  ): Promise<string | null> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:upload_icon',
        organization_id: organizationId,
        image_data: imageData,
        content_type: contentType,
      } as any) as IconUploadResponse;
      if (response.error) {
        setError(response.error);
        return null;
      }
      return response.icon_url ?? null;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to upload icon');
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const listMyOrganizations = useCallback(async (): Promise<MyOrganizationsResponse['organizations']> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:list_mine',
      } as any) as MyOrganizationsResponse;
      if (response.error) {
        setError(response.error);
        return [];
      }
      return response.organizations ?? [];
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to list organizations');
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  const switchOrganization = useCallback(async (organizationId: string): Promise<boolean> => {
    setLoading(true);
    setError(null);
    try {
      const response = await sendEventAsync({
        event_name: 'organization:switch',
        organization_id: organizationId,
      } as any) as GenericResponse;
      if (response.error) {
        setError(response.error);
        return false;
      }
      return response.success ?? false;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to switch organization');
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    loading,
    error,
    clearError: () => setError(null),
    // Organization operations
    createOrganization,
    checkSlugAvailability,
    getOrganization,
    updateOrganization,
    deleteOrganization,
    transferOwnership,
    // Member operations
    listMembers,
    inviteMember,
    removeMember,
    updateMemberRole,
    // Invite operations
    listInvites,
    getInviteDetails,
    acceptInvite,
    revokeInvite,
    // SSO operations
    configureSSO,
    disableSSO,
    getSSOInfo,
    // Icon operations
    uploadIcon,
    // Multi-org operations
    listMyOrganizations,
    switchOrganization,
  };
}
