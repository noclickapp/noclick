// File view for an agent conversation's persistent workspace volume: a Files
// popover listing what the agent has written (with direct upload into the
// volume), and a preview dialog (markdown / code / image / download) that
// workspace-path links in chat messages also open. Added because agents
// reference files like /workspace/report.md and clicking those used to 404
// into the router (reported navigation incident, 2026-07-17).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Check, ChevronRight, Download, FileText, Folder, FolderOpen, Image as ImageIcon,
  Loader2, RefreshCw, Trash2, Upload, X,
} from 'lucide-react';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from '~/components/ui/dialog';
import { useAnchoredPopover } from '~/components/interface/blocks/useAnchoredPopover';
import { MarkdownRenderer } from '~/components/chat/MarkdownRenderer';
import { formatSize } from '~/components/resource/ResourceRenderer';
import {
  uploadWorkspaceFiles,
  workspaceFileUrl,
  workspaceRelativePath,
  type WorkspaceFile,
  type WorkspaceFilesState,
  type WorkspaceUploadProgress,
} from '~/hooks/useAgentWorkspaceFiles';
import { UploadProgressBar } from '~/components/ui/upload-progress';
import { cn } from '~/lib/utils';

const MARKDOWN_EXTENSIONS = new Set(['md', 'markdown']);
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp']);
const TEXT_EXTENSIONS = new Set([
  'txt', 'log', 'json', 'jsonl', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'csv',
  'tsv', 'py', 'ts', 'tsx', 'js', 'jsx', 'sh', 'sql', 'html', 'css', 'xml',
  'env', 'svg',
]);
const MAX_TEXT_PREVIEW_BYTES = 2 * 1024 * 1024;

function extOf(path: string): string {
  const dot = path.lastIndexOf('.');
  return dot === -1 ? '' : path.slice(dot + 1).toLowerCase();
}

function kindOf(file: WorkspaceFile): 'markdown' | 'text' | 'image' | 'binary' {
  const ext = extOf(file.path);
  if (MARKDOWN_EXTENSIONS.has(ext)) return 'markdown';
  if (IMAGE_EXTENSIONS.has(ext)) return 'image';
  if (TEXT_EXTENSIONS.has(ext)) return 'text';
  return 'binary';
}

/** What the preview dialog is being asked to show: a path the user clicked
 *  (from the panel or an in-message link). Absolute paths outside the
 *  workspace mount are ephemeral-sandbox paths we can't serve. */
export interface WorkspacePreviewRequest {
  /** Absolute path as mentioned in chat, OR volume-relative panel path. */
  path: string;
}

function resolveFile(
  request: WorkspacePreviewRequest,
  state: WorkspaceFilesState,
): { file?: WorkspaceFile; ephemeral?: boolean; relPath: string } {
  const raw = request.path;
  let rel: string | null;
  if (raw.startsWith('/')) {
    rel = workspaceRelativePath(raw, state.mount);
    if (rel === null) return { ephemeral: true, relPath: raw };
  } else {
    rel = raw;
  }
  const relPath = rel.replace(/^\/+/, '');
  return { file: state.files.find(f => f.path === relPath), relPath };
}

function TextOrMarkdownPreview({ file }: { file: WorkspaceFile }) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const kind = kindOf(file);

  useEffect(() => {
    const controller = new AbortController();
    setContent(null);
    setError(null);
    fetch(workspaceFileUrl(file.url_path), { signal: controller.signal })
      .then(async res => {
        if (!res.ok) throw new Error(`Failed to load file (${res.status})`);
        setContent(await res.text());
      })
      .catch(e => {
        if (controller.signal.aborted) return;
        setError(e instanceof Error ? e.message : 'Failed to load file');
      });
    return () => controller.abort();
  }, [file.url_path]);

  if (error) {
    return <div className="text-sm text-red-600/90 dark:text-red-400/90 py-4">{error}</div>;
  }
  if (content === null) {
    return <div className="text-sm text-muted-foreground py-4">Loading…</div>;
  }
  if (kind === 'markdown') {
    return <MarkdownRenderer content={content} className="text-[14px]" />;
  }
  return (
    <pre className="text-xs leading-relaxed text-foreground/90 bg-muted/50 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words">
      {content}
    </pre>
  );
}

export function WorkspaceFilePreviewDialog({
  request,
  state,
  onClose,
  onRetry,
}: {
  request: WorkspacePreviewRequest | null;
  state: WorkspaceFilesState;
  onClose: () => void;
  /** Re-list the volume — files land a few seconds after the agent writes. */
  onRetry: () => void;
}) {
  const resolved = request ? resolveFile(request, state) : null;
  const file = resolved?.file;
  const kind = file ? kindOf(file) : null;
  const previewableText =
    file && (kind === 'markdown' || kind === 'text') && file.size <= MAX_TEXT_PREVIEW_BYTES;

  return (
    <Dialog open={!!request} onOpenChange={open => { if (!open) onClose(); }}>
      <DialogContent
        data-testid="workspace-file-preview"
        className="max-w-3xl max-h-[85vh] flex flex-col"
      >
        <DialogHeader className="shrink-0">
          <DialogTitle className="flex items-center gap-2 text-sm font-medium min-w-0">
            <FileText className="w-4 h-4 shrink-0 text-muted-foreground" />
            <span className="truncate">{resolved?.relPath || request?.path}</span>
          </DialogTitle>
          {file ? (
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span>{formatSize(file.size)}</span>
              {file.mtime ? <span>{new Date(file.mtime * 1000).toLocaleString()}</span> : null}
              <a
                href={workspaceFileUrl(file.url_path, { download: true })}
                className="inline-flex items-center gap-1 text-foreground/80 hover:text-foreground transition-colors"
                data-testid="workspace-file-download"
              >
                <Download className="w-3.5 h-3.5" />
                Download
              </a>
            </div>
          ) : null}
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto scrollbar-subtle">
          {/* Order matters: until the listing has loaded we don't know the
              real mount, so loading/error MUST precede the ephemeral verdict —
              a FilesystemNode custom-mount path would otherwise be branded
              "temporary filesystem" while (or because) the listing fetch is
              pending/failed. */}
          {!resolved ? null : !state.loaded && state.loading ? (
            <div className="text-sm text-muted-foreground py-4">Loading…</div>
          ) : !state.loaded ? (
            <div className="text-sm text-muted-foreground py-4 space-y-3">
              <p>Couldn&rsquo;t load the workspace listing{state.error ? ` (${state.error})` : ''}.</p>
              <button
                type="button"
                onClick={onRetry}
                disabled={state.loading}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground bg-foreground/[0.06] hover:bg-foreground/[0.12] border border-border rounded-md px-2.5 py-1 transition-colors disabled:opacity-50"
              >
                <RefreshCw className={cn('w-3.5 h-3.5', state.loading && 'animate-spin')} />
                Try again
              </button>
            </div>
          ) : resolved.ephemeral ? (
            <div className="text-sm text-muted-foreground py-4 space-y-2">
              <p>
                <code className="text-foreground/90">{request?.path}</code> lives in the
                sandbox&rsquo;s temporary filesystem, which is wiped when the agent&rsquo;s
                sandbox restarts — it can&rsquo;t be opened from here.
              </p>
              <p>
                Ask the agent to save files under{' '}
                <code className="text-foreground/90">{state.mount || '/workspace'}</code> — that
                folder is persistent and shows up in this file view.
              </p>
            </div>
          ) : !file && state.loading ? (
            <div className="text-sm text-muted-foreground py-4">Loading…</div>
          ) : !file ? (
            <div className="text-sm text-muted-foreground py-4 space-y-3">
              <p>
                This file isn&rsquo;t in the workspace listing{state.loaded ? '' : ' yet'}.
                Files the agent just wrote can take a few seconds to appear.
              </p>
              <button
                type="button"
                onClick={onRetry}
                disabled={state.loading}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-foreground bg-foreground/[0.06] hover:bg-foreground/[0.12] border border-border rounded-md px-2.5 py-1 transition-colors disabled:opacity-50"
              >
                <RefreshCw className={cn('w-3.5 h-3.5', state.loading && 'animate-spin')} />
                Check again
              </button>
            </div>
          ) : kind === 'image' ? (
            <img
              src={workspaceFileUrl(file.url_path)}
              alt={file.path}
              className="max-w-full max-h-[65vh] object-contain rounded-lg"
            />
          ) : previewableText ? (
            <TextOrMarkdownPreview file={file} />
          ) : (
            <div className="text-sm text-muted-foreground py-4">
              No inline preview for this file
              {file.size > MAX_TEXT_PREVIEW_BYTES ? ' (too large)' : ' type'} — use Download.
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

const PANEL_WIDTH = 380;

export function WorkspaceFilesMenu({
  state,
  onRefresh,
  onPreview,
}: {
  state: WorkspaceFilesState & {
    refresh: () => Promise<void>;
    deleteFile: (path: string) => Promise<void>;
  };
  onRefresh: () => void;
  onPreview: (request: WorkspacePreviewRequest) => void;
}) {
  // Mirrors AgentChatHistory/AgentModelPicker's anchored portal-popover
  // pattern so the header dropdowns share one look-and-feel — including the
  // left-edge anchor, since the trigger sits beside History in the header's
  // left cluster.
  const computePos = useCallback(
    (rect: DOMRect) => ({
      top: rect.bottom + 8,
      left: Math.max(8, rect.left - 4),
      width: PANEL_WIDTH,
    }),
    [],
  );
  const { open, setOpen, triggerRef, panelRef, pos } =
    useAnchoredPopover<HTMLButtonElement>(computePos);

  const handleToggle = useCallback(() => {
    const next = !open;
    setOpen(next);
    // Refetch on every open (History does the same) — files usually change
    // while the popover is closed.
    if (next) onRefresh();
  }, [open, setOpen, onRefresh]);

  // Upload into the workspace volume via the signed capability the listing
  // response carries. Errors surface inline in the panel; the listing
  // refreshes after so the new files show up.
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadProgress, setUploadProgress] = useState<WorkspaceUploadProgress | null>(null);
  const uploading = uploadProgress !== null;
  const [uploadError, setUploadError] = useState<string | null>(null);
  const handleUpload = useCallback(async (selected: FileList | null) => {
    const uploadUrlPath = state.uploadUrlPath;
    if (!selected?.length || !uploadUrlPath) return;
    const files = Array.from(selected);
    setUploadProgress({ fileName: files[0].name, fileIndex: 0, fileCount: files.length, fraction: 0 });
    setUploadError(null);
    try {
      await uploadWorkspaceFiles(uploadUrlPath, files, setUploadProgress);
      onRefresh();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setUploadProgress(null);
    }
  }, [state.uploadUrlPath, onRefresh]);

  // Delete a file. Two-step inline confirm (no blocking dialog): first click on
  // a row's trash arms it; the confirm/cancel controls then replace the size.
  const [confirmPath, setConfirmPath] = useState<string | null>(null);
  const [deletingPath, setDeletingPath] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { deleteFile } = state;
  const handleDelete = useCallback(async (path: string) => {
    setDeletingPath(path);
    setConfirmPath(null);
    setDeleteError(null);
    try {
      await deleteFile(path);
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : 'Delete failed');
    } finally {
      setDeletingPath(null);
    }
  }, [deleteFile]);

  // Collapsed directory groups. Lives on the (always-mounted) menu component,
  // so the state survives popover close/reopen within the session.
  const [collapsedDirs, setCollapsedDirs] = useState<ReadonlySet<string>>(new Set());
  const toggleDir = useCallback((dir: string) => {
    setCollapsedDirs(prev => {
      const next = new Set(prev);
      if (next.has(dir)) next.delete(dir);
      else next.add(dir);
      return next;
    });
  }, []);

  // Group by directory for a light tree feel without a tree widget.
  const groups = useMemo(() => {
    const byDir = new Map<string, WorkspaceFile[]>();
    for (const f of state.files) {
      const slash = f.path.lastIndexOf('/');
      const dir = slash === -1 ? '' : f.path.slice(0, slash);
      const list = byDir.get(dir);
      if (list) list.push(f);
      else byDir.set(dir, [f]);
    }
    return [...byDir.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [state.files]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={handleToggle}
        aria-label="Workspace files"
        title="Files the agent saved in this conversation"
        data-testid="workspace-files-button"
        className="shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border/60 hover:border-border hover:bg-foreground/[0.04] transition-colors text-muted-foreground hover:text-foreground"
      >
        <Folder className="w-3.5 h-3.5" />
        <span className="text-sm hidden @xl:inline">Files</span>
        {state.loaded && state.files.length > 0 ? (
          <span className="text-xs tabular-nums rounded-full bg-foreground/[0.06] px-1.5 py-px text-muted-foreground/80">
            {state.files.length}
          </span>
        ) : null}
      </button>

      {open && pos && createPortal(
        <div
          ref={panelRef}
          style={{ top: pos.top, left: pos.left, width: pos.width }}
          className="fixed z-[60] rounded-2xl border border-border bg-popover/95 dark:bg-zinc-950/95 backdrop-blur-md shadow-2xl overflow-hidden"
          data-testid="workspace-files-panel"
        >
          <div className="px-4 py-3 border-b border-border dark:border-zinc-900 flex items-center justify-between gap-2">
            <span className="text-xs uppercase tracking-wider text-muted-foreground dark:text-zinc-500">
              Workspace files
            </span>
            <div className="flex items-center gap-2 min-w-0">
              {state.mount ? (
                <code className="truncate font-mono text-[10px] text-muted-foreground/70 dark:text-zinc-600">
                  {state.mount}
                </code>
              ) : null}
              {state.uploadUrlPath ? (
                <>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={e => {
                      void handleUpload(e.target.files);
                      e.target.value = '';
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={uploading}
                    aria-label="Upload files"
                    title="Upload files to the workspace"
                    data-testid="workspace-upload-button"
                    className="shrink-0 text-muted-foreground dark:text-zinc-500 hover:text-foreground transition-colors disabled:opacity-50"
                  >
                    {uploading
                      ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      : <Upload className="w-3.5 h-3.5" />
                    }
                  </button>
                </>
              ) : null}
              <button
                type="button"
                onClick={onRefresh}
                disabled={state.loading}
                aria-label="Refresh files"
                title="Refresh files"
                className="shrink-0 text-muted-foreground dark:text-zinc-500 hover:text-foreground transition-colors disabled:opacity-50"
              >
                <RefreshCw className={cn('w-3.5 h-3.5', state.loading && 'animate-spin')} />
              </button>
            </div>
          </div>

          {uploadProgress ? (
            <div className="px-4 py-2 border-b border-border dark:border-zinc-900 space-y-1.5">
              <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                <span className="truncate">{uploadProgress.fileName}</span>
                <span className="shrink-0 tabular-nums">
                  {uploadProgress.fileCount > 1
                    ? `${uploadProgress.fileIndex + 1}/${uploadProgress.fileCount} · `
                    : ''}
                  {Math.round(uploadProgress.fraction * 100)}%
                </span>
              </div>
              <UploadProgressBar fraction={uploadProgress.fraction} />
            </div>
          ) : null}

          {uploadError ? (
            <div className="px-4 py-2 text-xs text-red-600/90 dark:text-red-400/90 border-b border-border dark:border-zinc-900">
              {uploadError}
            </div>
          ) : null}

          {deleteError ? (
            <div className="px-4 py-2 text-xs text-red-600/90 dark:text-red-400/90 border-b border-border dark:border-zinc-900">
              {deleteError}
            </div>
          ) : null}

          {state.error ? (
            <div className="px-4 py-6 text-center text-sm text-red-600/90 dark:text-red-400/90">
              {state.error}
            </div>
          ) : state.loading && !state.loaded ? (
            <div className="px-4 py-6 text-center text-sm text-muted-foreground/70 dark:text-zinc-600">
              Loading
            </div>
          ) : state.files.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-muted-foreground/70 dark:text-zinc-600">
              No files yet. Files the agent saves under{' '}
              <code className="font-mono text-[11px]">{state.mount || '/workspace'}</code>{' '}
              appear here{state.uploadUrlPath ? ', or upload your own' : ''}.
            </div>
          ) : (
            <div className="max-h-[420px] overflow-y-auto scrollbar-subtle px-2 py-2 space-y-0.5">
              {groups.map(([dir, files]) => {
                const rows = files.map(f => {
                  const name = f.path.slice(f.path.lastIndexOf('/') + 1);
                  const isImage = kindOf(f) === 'image';
                  const Icon = isImage ? ImageIcon : FileText;
                  const armed = confirmPath === f.path;
                  const deleting = deletingPath === f.path;
                  return (
                    <div
                      key={f.path}
                      data-testid="workspace-file-row"
                      className="group flex items-center gap-2 rounded-lg px-2.5 py-1.5 hover:bg-foreground/[0.03] transition-colors"
                    >
                      <button
                        type="button"
                        onClick={() => { setOpen(false); onPreview({ path: f.path }); }}
                        data-testid="workspace-file-open"
                        className="flex-1 min-w-0 flex items-center gap-2 text-left"
                      >
                        <Icon className="w-3.5 h-3.5 shrink-0 text-muted-foreground dark:text-zinc-500 group-hover:text-foreground/80 transition-colors" />
                        <span className="flex-1 min-w-0 truncate text-sm text-foreground/80 group-hover:text-foreground transition-colors">
                          {name}
                        </span>
                      </button>
                      {deleting ? (
                        <Loader2 className="w-3.5 h-3.5 shrink-0 animate-spin text-muted-foreground" />
                      ) : armed ? (
                        <span className="shrink-0 flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => handleDelete(f.path)}
                            aria-label={`Confirm delete ${name}`}
                            title="Confirm delete"
                            data-testid="workspace-file-delete-confirm"
                            className="text-red-500 hover:text-red-600 transition-colors"
                          >
                            <Check className="w-3.5 h-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmPath(null)}
                            aria-label="Cancel delete"
                            title="Cancel"
                            className="text-muted-foreground hover:text-foreground transition-colors"
                          >
                            <X className="w-3.5 h-3.5" />
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => { setConfirmPath(f.path); setDeleteError(null); }}
                          aria-label={`Delete ${name}`}
                          title="Delete file"
                          data-testid="workspace-file-delete"
                          className="shrink-0 text-muted-foreground/60 hover:text-red-500 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-all"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                      <span className="shrink-0 text-[10px] text-muted-foreground/70 dark:text-zinc-600 tabular-nums">
                        {formatSize(f.size)}
                      </span>
                    </div>
                  );
                });
                if (!dir) return <div key=".">{rows}</div>;
                // Files inside a directory render indented behind a guide
                // rail under a collapsible folder row, so containment is
                // legible — a flat label row between files read as a peer
                // (or an empty folder) instead of a parent.
                const collapsed = collapsedDirs.has(dir);
                const DirIcon = collapsed ? Folder : FolderOpen;
                return (
                  <div key={dir}>
                    <button
                      type="button"
                      onClick={() => toggleDir(dir)}
                      aria-expanded={!collapsed}
                      data-testid="workspace-dir-row"
                      className="group w-full flex items-center gap-1.5 rounded-lg px-1.5 py-1.5 text-left hover:bg-foreground/[0.03] transition-colors"
                    >
                      <ChevronRight
                        className={cn(
                          'w-3 h-3 shrink-0 text-muted-foreground/70 dark:text-zinc-600 transition-transform',
                          !collapsed && 'rotate-90',
                        )}
                      />
                      <DirIcon className="w-3.5 h-3.5 shrink-0 text-muted-foreground dark:text-zinc-500 group-hover:text-foreground/80 transition-colors" />
                      <span className="flex-1 min-w-0 truncate font-mono text-[11px] text-muted-foreground dark:text-zinc-500 group-hover:text-foreground/80 transition-colors">
                        {dir}/
                      </span>
                      <span className="shrink-0 pr-1 text-[10px] text-muted-foreground/70 dark:text-zinc-600 tabular-nums">
                        {files.length}
                      </span>
                    </button>
                    {collapsed ? null : (
                      // ml-3 = 12px: the rail sits under the caret's center
                      // (px-1.5 pad + half the w-3 chevron).
                      <div className="ml-3 border-l border-border/70 dark:border-zinc-800 pl-1">
                        {rows}
                      </div>
                    )}
                  </div>
                );
              })}
              {state.truncated ? (
                <div className="px-2.5 py-2 text-[10px] text-muted-foreground/70 dark:text-zinc-600">
                  Listing truncated — showing the first {state.files.length} files.
                </div>
              ) : null}
            </div>
          )}
        </div>,
        document.body,
      )}
    </>
  );
}
