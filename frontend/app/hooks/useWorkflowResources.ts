// Hook for managing workflow resources: fetching the list, resolving download URLs,
// deleting, and previewing. Eagerly fetches presigned URLs for all blob resources
// so tiles can show inline thumbnails/previews. Used by the Resources tab.

import { useState, useCallback, useRef } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';
import {
  ResourceListRequest,
  ResourceDeleteRequest,
  ResourceDownloadUrlRequest,
} from '~/types/socket-events.generated';
import type { ResourceInfo } from '~/types/socket-events.generated';

export function useWorkflowResources(workflowId: string) {
  const [resources, setResources] = useState<ResourceInfo[]>([]);
  const [loading, setLoading] = useState(false);
  // Maps resource id → presigned download URL
  const [urlMap, setUrlMap] = useState<Record<string, string>>({});
  const [previewResource, setPreviewResource] = useState<ResourceInfo | null>(null);
  const fetchedRef = useRef(false);

  const resolveUrls = useCallback(async (items: ResourceInfo[]) => {
    const blobs = items.filter(r => r.resource_type !== 'dataset');
    const map: Record<string, string> = {};
    // Batch requests to stay under the rate limit (10/sec, 60/min)
    const BATCH_SIZE = 8;
    for (let i = 0; i < blobs.length; i += BATCH_SIZE) {
      const batch = blobs.slice(i, i + BATCH_SIZE);
      const results = await Promise.allSettled(
        batch.map(async r => {
          const res = await sendEventAsync(
            ResourceDownloadUrlRequest.create({ resource_id: r.id })
          );
          return { id: r.id, url: res.download_url };
        })
      );
      for (const result of results) {
        if (result.status === 'fulfilled') {
          map[result.value.id] = result.value.url;
        }
      }
      // Update progressively so tiles render as URLs resolve
      setUrlMap(prev => ({ ...prev, ...map }));
      // Pause between batches to respect rate limit
      if (i + BATCH_SIZE < blobs.length) {
        await new Promise(resolve => setTimeout(resolve, 1100));
      }
    }
    setUrlMap(map);
  }, []);

  const fetchResources = useCallback(async () => {
    if (!workflowId) return;
    setLoading(true);
    try {
      const res = await sendEventAsync(
        ResourceListRequest.create({ workflow_id: workflowId, limit: 100 })
      );
      setResources(res.resources);
      fetchedRef.current = true;
      // Eagerly resolve download URLs for all blob resources
      await resolveUrls(res.resources);
    } catch (err) {
      console.error('[useWorkflowResources] Fetch failed:', err);
      fetchedRef.current = true;
    } finally {
      setLoading(false);
    }
  }, [workflowId, resolveUrls]);

  const deleteResource = useCallback(async (resourceId: string) => {
    try {
      await sendEventAsync(ResourceDeleteRequest.create({ resource_id: resourceId }));
      setResources(prev => prev.filter(r => r.id !== resourceId));
      setUrlMap(prev => { const next = { ...prev }; delete next[resourceId]; return next; });
      setPreviewResource(prev => (prev?.id === resourceId ? null : prev));
    } catch (err) {
      console.error('[useWorkflowResources] Delete failed:', err);
    }
  }, []);

  const openPreview = useCallback((resource: ResourceInfo) => {
    setPreviewResource(resource);
  }, []);

  const closePreview = useCallback(() => {
    setPreviewResource(null);
  }, []);

  return {
    resources,
    loading,
    hasFetched: fetchedRef.current,
    urlMap,
    fetchResources,
    deleteResource,
    previewResource,
    openPreview,
    closePreview,
  };
}
