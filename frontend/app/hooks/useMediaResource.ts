// Shared hook for interface blocks that display a single uploaded media resource.
// Handles upload, presigned URL fetching, deletion, drag-and-drop state,
// and frontend-side resolution of template references (e.g. {{nodeId.path}}).

import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useStore } from '@xyflow/react';
import { sendEventAsync } from '~/lib/socket-sender';
import {
  ResourceDownloadUrlRequest,
  ResourceDeleteRequest,
} from '~/types/socket-events.generated';
import { useResourceUpload } from './useResourceUpload';
import { useWorkflowId } from '~/components/workflow/WorkflowContext';
import type { BlockConfig } from '~/components/interface/types';

/**
 * Parse a single template reference and extract nodeId + path segments.
 * Returns null for non-reference strings or mixed text+reference strings.
 */
function parseTemplateRef(value: string): { nodeId: string; path: string[] } | null {
  const match = value.trim().match(/^\{\{([^}]+)\}\}$/);
  if (!match) return null;
  const parts = match[1].split('.');
  if (parts.length < 1) return null;
  return { nodeId: parts[0], path: parts.slice(1) };
}

/**
 * Navigate a dot-separated path with optional array indices through an object.
 * Handles patterns like "videos[0].video_url" or "data.items[2].name".
 */
function navigatePath(obj: unknown, path: string[]): unknown {
  let current: unknown = obj;
  for (const part of path) {
    if (current === null || current === undefined) return undefined;
    const keyMatch = part.match(/^([^\[]*)((?:\[\d+\])*)$/);
    if (!keyMatch) return undefined;

    const keyName = keyMatch[1];
    const indicesStr = keyMatch[2];

    if (keyName) {
      if (typeof current !== 'object') return undefined;
      current = (current as Record<string, unknown>)[keyName];
      if (current === undefined) return undefined;
    }
    if (indicesStr) {
      for (const m of indicesStr.matchAll(/\[(\d+)\]/g)) {
        const idx = parseInt(m[1]);
        if (!Array.isArray(current) || idx >= current.length) return undefined;
        current = current[idx];
      }
    }
  }
  return current;
}

// 'file' accepts any type (empty prefix → the type gate below never rejects).
const MIME_PREFIX: Record<'image' | 'audio' | 'video' | 'file', string> = {
  image: 'image/',
  audio: 'audio/',
  video: 'video/',
  file: '',
};

export function useMediaResource(
  id: string,
  config: BlockConfig,
  onConfigChange: (config: BlockConfig) => void,
  resourceType: 'image' | 'audio' | 'video' | 'file',
) {
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  // User-facing upload/validation error (null = no error). Surfaced by the block
  // so failures are never silent (dropping a video into an audio block, R2 PUT
  // failure, oversize, socket error).
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { uploadFile, uploading, progress } = useResourceUpload();
  const workflowId = useWorkflowId();

  // Guard against setState after unmount (upload can resolve post-unmount).
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const resourceId = (config.resource_id as string) || '';
  const rawConfigSrc = (config.src as string) || '';

  // Parse template reference info once (stable across renders for the same src)
  const templateRef = useMemo(
    () => (rawConfigSrc ? parseTemplateRef(rawConfigSrc) : null),
    [rawConfigSrc],
  );

  // Reactively resolve template references by subscribing to the referenced
  // node's output in the ReactFlow store.  When the upstream node produces
  // output (e.g. an agent emits a video URL), this selector re-evaluates and
  // the block re-renders with the resolved URL — no explicit execution of the
  // interface node is needed.
  const resolvedSrc = useStore(
    useCallback(
      (state: { nodeLookup: Map<string, { data?: Record<string, unknown> }> }) => {
        if (!templateRef) return '';
        const node = state.nodeLookup.get(templateRef.nodeId);
        if (!node?.data?.output) return '';
        const value = navigatePath(node.data.output, templateRef.path);
        return typeof value === 'string' ? value : '';
      },
      [templateRef],
    ),
  );

  // Use the raw src only if it's NOT a template reference (i.e. a real URL).
  // Template references are resolved above via the ReactFlow store.
  const configSrc = templateRef ? resolvedSrc : rawConfigSrc;

  // Fetch presigned download URL when resource_id is set
  useEffect(() => {
    if (!resourceId) {
      setMediaUrl(null);
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const res = await sendEventAsync(
          ResourceDownloadUrlRequest.create({ resource_id: resourceId })
        );
        if (!cancelled) setMediaUrl(res.download_url);
      } catch {
        if (!cancelled) setMediaUrl(null);
      }
    })();

    return () => { cancelled = true; };
  }, [resourceId]);

  const handleUpload = useCallback(
    async (file: File) => {
      if (!workflowId) return;
      setError(null);
      // Reject wrong media type up front. The picker's accept="" is only an
      // advisory hint — the browser still lets users choose "All Files" (and some
      // list .mp4 under the audio filter), and drag-drop isn't gated at all — so
      // a .mp4 in an audio block would otherwise upload then silently fail to
      // render. Give an actionable message that points to the right block.
      const prefix = MIME_PREFIX[resourceType];
      if (file.type && !file.type.startsWith(prefix)) {
        const kind = file.type.split('/')[0]; // 'video' | 'image' | 'audio' | 'application' | ...
        const suggestion =
          kind === 'image' ? ' Use an Image block for this file.'
          : kind === 'video' ? ' Use a Video block for this file.'
          : kind === 'audio' ? ' Use an Audio block for this file.'
          : '';
        setError(`This is a ${resourceType} block — it can't take a "${file.type}" file.${suggestion}`);
        return;
      }
      try {
        const result = await uploadFile(file, workflowId, id);
        if (!mountedRef.current) return;
        onConfigChange({ ...config, resource_id: result.resourceId });
      } catch (err) {
        if (mountedRef.current) {
          setError(err instanceof Error ? err.message : `Failed to upload ${resourceType}.`);
        }
        console.error(`[${resourceType}] Upload failed:`, err);
      }
    },
    [workflowId, id, uploadFile, config, onConfigChange, resourceType]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
    setError(null);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleUpload(file);
    },
    [handleUpload]
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleUpload(file);
      e.target.value = '';
    },
    [handleUpload]
  );

  const handleDelete = useCallback(async () => {
    if (!resourceId) return;
    try {
      await sendEventAsync(ResourceDeleteRequest.create({ resource_id: resourceId }));
    } catch {
      // Best-effort deletion
    }
    setMediaUrl(null);
    setError(null);
    onConfigChange({ ...config, resource_id: '' });
  }, [resourceId, config, onConfigChange]);

  const clearError = useCallback(() => setError(null), []);

  // Effective URL: resource download URL takes priority, then config.src fallback
  const effectiveUrl = mediaUrl || configSrc || null;

  return {
    mediaUrl: effectiveUrl,
    uploading,
    progress,
    isDragOver,
    inputRef,
    error,
    clearError,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handleFileSelect,
    handleDelete,
    hasResource: !!resourceId,
  };
}
