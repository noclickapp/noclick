/**
 * useCredentialRequests - Hook for managing outgoing credential requests.
 * Allows users to request credentials from external email addresses,
 * list pending requests, and cancel them.
 */

import { useState, useCallback } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';

export interface CredentialRequest {
  id: string;
  target_email: string;
  credential_type: string;
  message?: string;
  status: 'pending' | 'fulfilled' | 'expired' | 'cancelled';
  credential_id?: string;
  expires_at?: string;
  created_at: string;
  fulfilled_at?: string;
}

interface CreateRequestResponse {
  success: boolean;
  request?: CredentialRequest;
  message?: string;
}

interface ListRequestsResponse {
  requests: CredentialRequest[];
}

interface CancelRequestResponse {
  success: boolean;
  message: string;
}

export function useCredentialRequests() {
  const [requests, setRequests] = useState<CredentialRequest[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createRequest = useCallback(
    async (
      targetEmail: string,
      credentialType: string,
      message?: string,
    ): Promise<CredentialRequest | null> => {
      setLoading(true);
      setError(null);

      try {
        const response = (await sendEventAsync({
          event_name: 'credential:request:create',
          request_id: `cred-req-${Date.now()}`,
          target_email: targetEmail,
          credential_type: credentialType,
          message,
          frontend_url: window.location.origin,
        } as any)) as CreateRequestResponse;

        if (response?.success && response.request) {
          setRequests((prev) => [response.request!, ...prev]);
          return response.request;
        }
        setError(response?.message || 'Failed to create credential request');
        return null;
      } catch (e: any) {
        setError(e?.message || 'Failed to create credential request');
        return null;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const listRequests = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const response = (await sendEventAsync({
        event_name: 'credential:request:list',
        request_id: `cred-req-list-${Date.now()}`,
      } as any)) as ListRequestsResponse;

      if (response?.requests) {
        setRequests(response.requests);
      }
    } catch (e: any) {
      setError(e?.message || 'Failed to list credential requests');
    } finally {
      setLoading(false);
    }
  }, []);

  const cancelRequest = useCallback(async (requestId: string): Promise<boolean> => {
    setError(null);

    try {
      const response = (await sendEventAsync({
        event_name: 'credential:request:cancel',
        request_id: `cred-req-cancel-${Date.now()}`,
        credential_request_id: requestId,
      } as any)) as CancelRequestResponse;

      if (response?.success) {
        setRequests((prev) =>
          prev.map((r) =>
            r.id === requestId ? { ...r, status: 'cancelled' as const } : r,
          ),
        );
        return true;
      }
      setError(response?.message || 'Failed to cancel request');
      return false;
    } catch (e: any) {
      setError(e?.message || 'Failed to cancel request');
      return false;
    }
  }, []);

  const pendingRequests = requests.filter((r) => r.status === 'pending');

  return {
    requests,
    pendingRequests,
    loading,
    error,
    createRequest,
    listRequests,
    cancelRequest,
    clearError: () => setError(null),
  };
}
