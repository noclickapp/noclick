// Lists files on the conversation's persistent workspace volume, mounted at
// /workspace) via the agent_workspace:list socket event. Added for the chat's
// file view: agents tell users about files they wrote (e.g. /workspace/report.md)
// and before this there was no way to open them from the browser.
import { useCallback, useEffect, useRef, useState } from 'react';
import { sendEventAsync } from '~/lib/socket-sender';
import { uploadWithProgress } from '~/lib/uploadWithProgress';

export interface WorkspaceFile {
  /** Volume-relative path (no leading slash), e.g. "seo/output/report.md". */
  path: string;
  size: number;
  mtime: number;
  /** Signed streaming URL path on the backend origin (append &dl=1 to download). */
  url_path: string;
}

export interface WorkspaceFilesState {
  files: WorkspaceFile[];
  /** The sandbox mount point, e.g. "/workspace" — needed to resolve absolute
   *  paths the agent mentions in chat against volume-relative listing paths. */
  mount: string | null;
  /** Signed upload URL path for the workspace volume (append &path=<name> and
   *  POST the raw bytes); null until loaded or when there's no durable workspace. */
  uploadUrlPath: string | null;
  /** False until the first successful load. */
  loaded: boolean;
  loading: boolean;
  /** A durable workspace exists; a conversation that never wrote a file may have none. */
  exists: boolean;
  truncated: boolean;
  error: string | null;
}

const EMPTY: WorkspaceFilesState = {
  files: [], mount: null, uploadUrlPath: null, loaded: false, loading: false,
  exists: false, truncated: false, error: null,
};

/** Join a signed url_path with the backend origin (same origin the socket
 *  connects to — the route lives on the FastAPI app, not the Remix app). */
export function workspaceFileUrl(urlPath: string, opts?: { download?: boolean }): string {
  const base = (import.meta.env.VITE_API_URL as string | undefined) ?? '';
  return `${base}${urlPath}${opts?.download ? '&dl=1' : ''}`;
}

export interface WorkspaceUploadProgress {
  fileName: string;
  fileIndex: number;
  fileCount: number;
  /** Byte-weighted 0..1 across the whole selection. */
  fraction: number;
}

/** POST files to a workspace volume via its signed upload URL path (from
 *  agent_workspace:list or the filesystem node's file_browser load_value).
 *  Sequential so one failure surfaces cleanly; throws on the first error. */
// Mirrors the server cap in backend/utils/agent_workspace_routes.py.
const MAX_WORKSPACE_UPLOAD_BYTES = 100 * 1024 * 1024;

export async function uploadWorkspaceFiles(
  uploadUrlPath: string,
  files: File[],
  onProgress?: (progress: WorkspaceUploadProgress) => void,
): Promise<void> {
  for (const file of files) {
    if (file.size > MAX_WORKSPACE_UPLOAD_BYTES) {
      throw new Error(
        `${file.name} is too large (${(file.size / (1024 * 1024)).toFixed(1)} MB). Maximum size is ${MAX_WORKSPACE_UPLOAD_BYTES / (1024 * 1024)} MB.`,
      );
    }
  }
  const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
  let doneBytes = 0;
  for (const [index, file] of files.entries()) {
    const url = `${workspaceFileUrl(uploadUrlPath)}&path=${encodeURIComponent(file.name)}`;
    const res = await uploadWithProgress(url, file, {
      method: 'POST',
      onProgress: fileFraction => onProgress?.({
        fileName: file.name,
        fileIndex: index,
        fileCount: files.length,
        // Zero-byte selections have no meaningful byte weight; fall back to count.
        fraction: totalBytes > 0
          ? (doneBytes + file.size * fileFraction) / totalBytes
          : (index + fileFraction) / files.length,
      }),
    });
    if (!res.ok) {
      let message: string | undefined;
      try { message = (JSON.parse(res.text) as { error?: string }).error; } catch { /* non-JSON body */ }
      throw new Error(message || `Upload failed for ${file.name}`);
    }
    doneBytes += file.size;
  }
}

/** Volume-relative path for an absolute sandbox path the agent mentioned, or
 *  null when it lives outside the persistent workspace (ephemeral disk). */
export function workspaceRelativePath(absPath: string, mount: string | null): string | null {
  const m = mount || '/workspace';
  if (absPath === m) return '';
  if (absPath.startsWith(`${m}/`)) return absPath.slice(m.length + 1);
  return null;
}

export function useAgentWorkspaceFiles(
  workflowId: string | undefined,
  nodeId: string,
  conversationKey: string,
  /** Bumps a refresh when a turn finishes (files usually change then). Only
   *  refetches once something has loaded — the listing is lazy until the
   *  user first opens the panel or a file link. */
  turnWatermark: number,
): WorkspaceFilesState & { refresh: () => Promise<void> } {
  const [state, setState] = useState<WorkspaceFilesState>(EMPTY);
  const loadedRef = useRef(false);
  const inflightRef = useRef(false);
  // Generation token: bumped on every conversation switch so an in-flight
  // response for the OLD conversation can never write its files (and signed
  // urls) into the NEW conversation's state — it also unblocks the new
  // conversation's first refresh, which the stale inflight flag used to eat.
  const genRef = useRef(0);

  // A conversation switch invalidates everything (different volume).
  useEffect(() => {
    genRef.current += 1;
    loadedRef.current = false;
    inflightRef.current = false;
    setState(EMPTY);
  }, [workflowId, nodeId, conversationKey]);

  const refresh = useCallback(async () => {
    if (!workflowId || inflightRef.current) return;
    const gen = genRef.current;
    inflightRef.current = true;
    setState(s => ({ ...s, loading: true, error: null }));
    try {
      const res = await sendEventAsync<{
        success: boolean; error?: string; workspace?: string | null;
        exists?: boolean; truncated?: boolean; files?: WorkspaceFile[];
        upload_url_path?: string | null;
      }>({
        event_name: 'agent_workspace:list',
        workflow_id: workflowId,
        node_id: nodeId,
        conversation_key: conversationKey,
      });
      if (gen !== genRef.current) return; // stale: conversation switched mid-flight
      if (!res.success) throw new Error(res.error || 'Failed to list files');
      loadedRef.current = true;
      setState({
        files: res.files ?? [],
        mount: res.workspace ?? null,
        uploadUrlPath: res.upload_url_path ?? null,
        loaded: true,
        loading: false,
        exists: !!res.exists,
        truncated: !!res.truncated,
        error: null,
      });
    } catch (e) {
      if (gen !== genRef.current) return;
      setState(s => ({
        ...s, loading: false,
        error: e instanceof Error ? e.message : 'Failed to list files',
      }));
    } finally {
      if (gen === genRef.current) inflightRef.current = false;
    }
  }, [workflowId, nodeId, conversationKey]);

  // Files usually change when a turn completes; keep an opened panel fresh.
  useEffect(() => {
    if (turnWatermark > 0 && loadedRef.current) void refresh();
  }, [turnWatermark, refresh]);

  return { ...state, refresh };
}
