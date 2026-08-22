// Resolve a durable workflow-resource UUID to a fresh, authenticated download
// URL for display. The UUID is what may be persisted; the returned object-store
// URL is deliberately ephemeral and must stay in component state.

import { useEffect, useState } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';
import { ResourceDownloadUrlRequest } from '~/types/socket-events.generated';

const WORKFLOW_RESOURCE_ID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isWorkflowResourceId(value: string): boolean {
  return WORKFLOW_RESOURCE_ID_RE.test(value.trim());
}

export function useRenewableResourceUrl(value: string) {
  const resourceId = isWorkflowResourceId(value) ? value.trim() : null;
  const [resolvedUrl, setResolvedUrl] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!resourceId) {
      setResolvedUrl(null);
      setResolving(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setResolvedUrl(null);
    setResolving(true);
    setError(null);
    sendEventAsync(
      ResourceDownloadUrlRequest.create({ resource_id: resourceId }),
    )
      .then((response) => {
        if (!cancelled) setResolvedUrl(response.download_url);
      })
      .catch(() => {
        if (!cancelled) setError('The uploaded file is no longer available.');
      })
      .finally(() => {
        if (!cancelled) setResolving(false);
      });

    return () => {
      cancelled = true;
    };
  }, [resourceId]);

  return {
    url: resourceId ? resolvedUrl : value,
    isResourceId: resourceId !== null,
    resolving,
    error,
  };
}
