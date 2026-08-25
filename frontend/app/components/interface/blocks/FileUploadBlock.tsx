// Drop zone with file picker for the interface builder.
// Uploads files to R2 via the resource system and persists resource_ids in node config.

import { useState, useCallback, useRef, useEffect } from 'react';
import { Check, Link2, Upload, X, Loader2 } from 'lucide-react';
import type { BlockComponentProps } from '../types';
import { useResourceUpload } from '~/hooks/useResourceUpload';
import { UploadProgressBar } from '~/components/ui/upload-progress';
import { useWorkflowId } from '~/components/workflow/WorkflowContext';
import { sendEventAsync } from '~/lib/socket-sender';
import {
  ResourceDeleteRequest,
  ResourceDownloadUrlRequest,
  ResourceGetRequest,
} from '~/types/socket-events.generated';

interface ResourceMeta {
  id: string;
  name: string;
  sizeBytes: number;
  /** Whether the backend has a blob to authorize and resolve for this row. */
  hasStoredFile: boolean;
}

interface ActiveUpload {
  name: string;
  status: 'uploading' | 'error';
  /** Byte fraction 0..1 of the in-flight PUT. */
  fraction: number;
  /** Why the upload failed (oversize, R2 rejection, …) — shown on the row. */
  error?: string;
}

function parseResourceIds(config: Record<string, unknown>): string[] {
  const raw = config.resource_ids;
  if (!raw || typeof raw !== 'string') return [];
  return raw.split(',').map(s => s.trim()).filter(Boolean);
}

export function FileUploadBlock({ id, config, onConfigChange, isReadOnly, onInteraction }: BlockComponentProps) {
  const [activeUploads, setActiveUploads] = useState<ActiveUpload[]>([]);
  const [resources, setResources] = useState<ResourceMeta[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const { uploadFile } = useResourceUpload();
  const workflowId = useWorkflowId();

  const resourceIds = parseResourceIds(config);

  // Fetch metadata for persisted resource_ids on mount / when they change
  useEffect(() => {
    const ids = parseResourceIds(config);
    if (ids.length === 0) {
      setResources([]);
      return;
    }

    let cancelled = false;
    (async () => {
      const metas: ResourceMeta[] = [];
      for (const rid of ids) {
        try {
          const res = await sendEventAsync(ResourceGetRequest.create({ resource_id: rid }));
          if (!cancelled && res.resource) {
            metas.push({
              id: rid,
              name: res.resource.name,
              sizeBytes: res.resource.size_bytes ?? 0,
              hasStoredFile: Boolean(res.resource.storage_ref),
            });
          }
        } catch {
          // Resource may have been deleted externally — skip it
        }
      }
      if (!cancelled) setResources(metas);
    })();

    return () => { cancelled = true; };
  // Stringify to avoid re-running on every render when array reference changes
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resourceIds.join(',')]);

  const handleFiles = useCallback(
    async (fileList: FileList) => {
      if (!workflowId) return;

      const files = Array.from(fileList);
      // Add to active uploads
      setActiveUploads(prev => [
        ...prev,
        ...files.map(f => ({ name: f.name, status: 'uploading' as const, fraction: 0 })),
      ]);

      const newIds: string[] = [];
      const newMetas: ResourceMeta[] = [];

      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        try {
          const result = await uploadFile(file, workflowId, id, fraction =>
            setActiveUploads(prev =>
              prev.map(u => (u.name === file.name && u.status === 'uploading' ? { ...u, fraction } : u))
            )
          );
          newIds.push(result.resourceId);
          newMetas.push({
            id: result.resourceId, name: result.name,
            sizeBytes: result.sizeBytes, hasStoredFile: true,
          });
        } catch (err) {
          console.error('[FileUpload] Upload failed:', file.name, err);
          const message = err instanceof Error ? err.message : 'Upload failed';
          setActiveUploads(prev =>
            prev.map(u => (u.name === file.name && u.status === 'uploading' ? { ...u, status: 'error', error: message } : u))
          );
        }
      }

      // Remove completed uploads from active list
      setActiveUploads(prev => prev.filter(u => u.status === 'error'));

      if (newIds.length > 0) {
        const currentIds = parseResourceIds(config);
        const updatedIds = [...currentIds, ...newIds].join(',');
        onConfigChange({ ...config, resource_ids: updatedIds });
        setResources(prev => [...prev, ...newMetas]);
      }
    },
    [workflowId, id, uploadFile, config, onConfigChange]
  );

  // Which row's link was just copied — reverts the icon after a beat.
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const copyTimerRef = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(copyTimerRef.current), []);
  const copyLink = useCallback(async (resourceId: string) => {
    if (!navigator.clipboard) return;
    try {
      // storage_ref is an opaque object key, not proof that the bucket is
      // public. Let the authenticated backend choose the correct contract:
      // hosted may return its permanent CDN URL; private/self-hosted storage
      // returns a fresh short-lived signed URL.
      const response = await sendEventAsync(ResourceDownloadUrlRequest.create({ resource_id: resourceId }));
      await navigator.clipboard.writeText(response.download_url);
      setCopiedId(resourceId);
      window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(() => setCopiedId(null), 1500);
    } catch {
      // Keep the row usable if authorization, signing, or clipboard access
      // fails. A later click gets a fresh attempt rather than a cached URL.
    }
  }, []);

  const removeFile = useCallback(
    async (resourceId: string) => {
      try {
        await sendEventAsync(ResourceDeleteRequest.create({ resource_id: resourceId }));
      } catch {
        // Best-effort deletion
      }
      const currentIds = parseResourceIds(config);
      const updatedIds = currentIds.filter(rid => rid !== resourceId).join(',');
      onConfigChange({ ...config, resource_ids: updatedIds });
      setResources(prev => prev.filter(r => r.id !== resourceId));
    },
    [config, onConfigChange]
  );

  return (
    // p-2: the block chrome adds no padding of its own, so without this the
    // file list's border sits flush against the block's outer border.
    <div className="w-full h-full flex flex-col gap-2 overflow-auto p-2">
      <div
        className={`flex-1 min-h-[60px] flex flex-col items-center justify-center rounded-md border-2 border-dashed transition-colors cursor-pointer ${
          isDragOver ? 'border-blue-500 bg-blue-500/10' : 'border-border dark:border-zinc-700 bg-muted/50 hover:border-border dark:hover:border-zinc-600'
        }`}
        onDragOver={e => {
          e.preventDefault();
          setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={e => {
          e.preventDefault();
          setIsDragOver(false);
          if (isReadOnly) { onInteraction?.(); return; }
          if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
        }}
        onClick={() => { if (isReadOnly) { onInteraction?.(); return; } inputRef.current?.click(); }}
      >
        <Upload className="w-6 h-6 text-muted-foreground dark:text-zinc-500 mb-1" />
        <span className="text-[11px] text-muted-foreground dark:text-zinc-500">Drop files here or click to browse</span>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={e => {
            if (e.target.files?.length) handleFiles(e.target.files);
            e.target.value = '';
          }}
        />
      </div>

      {/* One contained list for in-flight + persisted files. The root's p-2
          keeps the last row clear of the grid's bottom-right resize handle. */}
      {(activeUploads.length > 0 || resources.length > 0) && (
        <div className="rounded-md border border-border dark:border-zinc-800 divide-y divide-border dark:divide-zinc-800 bg-muted/30 text-[11px]">
          {activeUploads.map((upload, i) => (
            <div key={`upload-${i}`} className="px-2.5 py-1.5" title={upload.error}>
              <div className="flex items-center gap-2">
                {upload.status === 'uploading' && (
                  <Loader2 className="w-3 h-3 text-blue-600 dark:text-blue-400 animate-spin flex-shrink-0" />
                )}
                <span className="flex-1 min-w-0 text-muted-foreground truncate">{upload.name}</span>
                {upload.status === 'error'
                  ? <span className="min-w-0 max-w-[60%] truncate text-red-600 dark:text-red-400 flex-shrink-0">{upload.error || 'Failed'}</span>
                  : <span className="text-muted-foreground/70 flex-shrink-0 tabular-nums">{Math.round(upload.fraction * 100)}%</span>}
              </div>
              {upload.status === 'uploading' && <UploadProgressBar fraction={upload.fraction} className="h-0.5 mt-1" />}
            </div>
          ))}
          {resources.map(r => (
            <div key={r.id} className="flex items-center gap-2 pl-2.5 pr-1 py-1 min-h-[26px]">
              <span className="flex-1 min-w-0 text-muted-foreground truncate">{r.name}</span>
              <span className="text-muted-foreground/70 dark:text-zinc-600 flex-shrink-0 tabular-nums">{formatSize(r.sizeBytes)}</span>
              {r.hasStoredFile && (
                <button
                  type="button"
                  aria-label={`Copy link to ${r.name}`}
                  title={copiedId === r.id ? 'Copied' : 'Copy link'}
                  onClick={e => {
                    e.stopPropagation();
                    void copyLink(r.id);
                  }}
                  className="relative z-[1] flex-shrink-0 rounded p-1 text-muted-foreground/70 dark:text-zinc-600 hover:text-foreground hover:bg-foreground/[0.06] transition-colors"
                >
                  {copiedId === r.id
                    ? <Check className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
                    : <Link2 className="w-3 h-3" />}
                </button>
              )}
              <button
                type="button"
                aria-label={`Remove ${r.name}`}
                onClick={e => {
                  e.stopPropagation();
                  removeFile(r.id);
                }}
                // relative z-[1] paints (and hit-tests) above the grid item's
                // resize handle, which otherwise swallows the last row's clicks.
                className="relative z-[1] mr-0.5 flex-shrink-0 rounded p-1 text-muted-foreground/70 dark:text-zinc-600 hover:text-foreground hover:bg-foreground/[0.06] transition-colors"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
