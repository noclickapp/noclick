/**
 * Hook for accessing and updating the current organization context.
 * Uses useCachedValtioState with skipRedisSync=true for local-only persistence
 * (sessionStorage + IndexedDB) without syncing to Redis.
 *
 * This allows org switching without page refresh - components react to state changes.
 */

import { useCachedValtioState } from './useCachedValtioState';

export interface OrgContext {
  id: string | null;
  role: 'owner' | 'admin' | 'member' | null;
  subscription_tier: 'free' | 'pro' | 'team' | 'enterprise' | null;
  isPersonalWorkspace: boolean;
}

const DEFAULT_ORG_CONTEXT: OrgContext = { id: null, role: null, subscription_tier: null, isPersonalWorkspace: true };

/**
 * Hook to get and set the current organization context.
 * Persists across page refreshes via IndexedDB.
 * Updates are reactive - all components using this hook will re-render.
 */
export function useOrgContext(): [OrgContext, (context: OrgContext) => void] {
  return useCachedValtioState<OrgContext>(
    'global',
    'org_context',
    DEFAULT_ORG_CONTEXT,
    true // skipRedisSync - local-only persistence
  );
}
