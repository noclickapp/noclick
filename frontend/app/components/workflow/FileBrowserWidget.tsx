/**
 * FileBrowserWidget - Displays files in the managed workspace volume for a filesystem node.
 * Fetches file listing via the load_field_value socket event and renders a browsable list.
 * Also lets users upload files directly into the volume via the signed upload URL
 * the same load_value response carries.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { RefreshCw, Search, FolderOpen, Folder, File, X, Upload, Loader2 } from 'lucide-react';
import { sendEventAsync } from '~/lib/socket-sender';
import { uploadWorkspaceFiles, type WorkspaceUploadProgress } from '~/hooks/useAgentWorkspaceFiles';
import { UploadProgressBar } from '~/components/ui/upload-progress';
import { fuzzyFilter } from '~/utils/fuzzySearch';

interface FileEntry {
    path: string;
    type: 'file' | 'dir';
}

interface FileBrowserWidgetProps {
    nodeId: string;
    nodeType: string;
    workflowId: string;
    /** The node's volume_mode config — per-conversation mode gets a scope hint,
     *  since this browser (and uploads) target the shared base volume. */
    volumeMode?: string;
}

export function FileBrowserWidget({ nodeId, nodeType, workflowId, volumeMode }: FileBrowserWidgetProps) {
    const [files, setFiles] = useState<FileEntry[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [uploadUrlPath, setUploadUrlPath] = useState<string | null>(null);
    const [uploadProgress, setUploadProgress] = useState<WorkspaceUploadProgress | null>(null);
    const uploading = uploadProgress !== null;
    const fileInputRef = useRef<HTMLInputElement>(null);

    const fetchFiles = useCallback(async () => {
        if (!workflowId || !nodeId) return;

        setLoading(true);
        setError(null);

        try {
            const response = await sendEventAsync({
                event_name: 'workflow:node:load_value',
                node_type: nodeType,
                field_name: 'file_browser',
                workflow_id: workflowId,
                node_id: nodeId,
                context: {},
            }) as { success: boolean; value?: { files: FileEntry[]; volume_name?: string; count: number; error?: string; empty?: boolean; upload_url_path?: string }; message?: string };

            if (response?.success && response.value) {
                setUploadUrlPath(response.value.upload_url_path ?? null);
                if (response.value.error) {
                    setError(response.value.error);
                } else {
                    setFiles(response.value.files || []);
                }
            } else {
                setError(response?.message || 'Failed to load files');
            }
        } catch (e) {
            setError('Connection error');
        } finally {
            setLoading(false);
        }
    }, [workflowId, nodeId, nodeType]);

    useEffect(() => {
        fetchFiles();
    }, [fetchFiles]);

    const handleUpload = useCallback(async (selected: FileList | null) => {
        if (!selected?.length || !uploadUrlPath) return;
        const files = Array.from(selected);
        setError(null);
        setUploadProgress({ fileName: files[0].name, fileIndex: 0, fileCount: files.length, fraction: 0 });
        try {
            await uploadWorkspaceFiles(uploadUrlPath, files, setUploadProgress);
            await fetchFiles();
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Upload failed');
        } finally {
            setUploadProgress(null);
        }
    }, [uploadUrlPath, fetchFiles]);

    // Client-side filter
    const filteredFiles = fuzzyFilter(files, searchQuery, f => [
        { text: f.path.toLowerCase(), weight: 1, fuzzy: true },
    ]);

    // Sort: directories first, then alphabetical
    const sortedFiles = [...filteredFiles].sort((a, b) => {
        if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
        return a.path.localeCompare(b.path);
    });

    return (
        <div className="space-y-2">
            {volumeMode === 'per_conversation_key' && (
                <div className="px-3 py-2 text-[11px] leading-relaxed text-muted-foreground dark:text-zinc-500 bg-foreground/[0.03] rounded-md border border-border dark:border-white/[0.05]">
                    Per-conversation mode: each chat gets its own isolated volume. This browser and
                    uploads use the shared base volume; a conversation&rsquo;s own files live in that
                    chat&rsquo;s Files panel.
                </div>
            )}
            {/* Search + Upload + Refresh bar */}
            <div className="flex items-center gap-1.5">
                <div className="relative flex-1">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground dark:text-zinc-500" />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        placeholder="Filter files..."
                        className="w-full pl-8 pr-7 py-1.5 text-xs rounded-md border border-border dark:border-white/[0.08] bg-foreground/[0.03] text-foreground outline-none placeholder:text-[hsl(var(--placeholder))] focus:border-foreground/20"
                    />
                    {searchQuery && (
                        <button
                            onClick={() => setSearchQuery('')}
                            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80"
                        >
                            <X className="w-3 h-3" />
                        </button>
                    )}
                </div>
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
                    onClick={() => fileInputRef.current?.click()}
                    disabled={!uploadUrlPath || uploading}
                    className="flex items-center gap-1.5 px-2 py-1.5 rounded-md border border-border dark:border-white/[0.08] bg-foreground/[0.03] text-xs text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] transition-colors disabled:opacity-50"
                    title="Upload files to the volume"
                >
                    {uploading
                        ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        : <Upload className="w-3.5 h-3.5" />
                    }
                    <span className="tabular-nums">
                        {uploadProgress ? `${Math.round(uploadProgress.fraction * 100)}%` : 'Upload'}
                    </span>
                </button>
                <button
                    onClick={fetchFiles}
                    disabled={loading}
                    className="p-1.5 rounded-md border border-border dark:border-white/[0.08] bg-foreground/[0.03] text-muted-foreground hover:text-foreground hover:bg-foreground/[0.06] transition-colors disabled:opacity-50"
                    title="Refresh"
                >
                    <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                </button>
            </div>

            {/* Upload progress */}
            {uploadProgress && (
                <div className="px-1 py-1 space-y-1">
                    <div className="flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
                        <span className="truncate font-mono">{uploadProgress.fileName}</span>
                        {uploadProgress.fileCount > 1 && (
                            <span className="shrink-0 tabular-nums">
                                {uploadProgress.fileIndex + 1}/{uploadProgress.fileCount}
                            </span>
                        )}
                    </div>
                    <UploadProgressBar fraction={uploadProgress.fraction} />
                </div>
            )}

            {/* Error state */}
            {error && (
                <div className="px-3 py-2 text-xs text-red-600 dark:text-red-400 bg-red-500/10 rounded-md border border-red-500/20">
                    {error}
                </div>
            )}

            {/* File list */}
            {!error && sortedFiles.length === 0 && !loading && (
                <div className="px-3 py-4 text-center text-xs text-muted-foreground dark:text-zinc-500">
                    <FolderOpen className="w-4 h-4 mx-auto mb-1.5 opacity-50" />
                    {files.length === 0
                        ? 'Volume is empty. Upload files or run the agent to create some.'
                        : 'No files match filter'}
                </div>
            )}

            {sortedFiles.length > 0 && (
                <div className="space-y-0.5">
                    <div className="text-[10px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider px-1">
                        {sortedFiles.length} item{sortedFiles.length !== 1 ? 's' : ''}
                    </div>
                    {sortedFiles.map(entry => (
                        <div
                            key={entry.path}
                            className="flex items-center gap-2 px-2.5 py-1.5 rounded-md border border-border dark:border-white/[0.05] bg-foreground/[0.02] text-xs"
                        >
                            {entry.type === 'dir'
                                ? <Folder className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400 shrink-0" />
                                : <File className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                            }
                            <span className="text-foreground/80 font-mono truncate">{entry.path}</span>
                        </div>
                    ))}
                </div>
            )}

            {/* Loading skeleton */}
            {loading && files.length === 0 && (
                <div className="space-y-1">
                    {[1, 2, 3].map(i => (
                        <div key={i} className="h-8 rounded-md bg-foreground/[0.03] animate-pulse" />
                    ))}
                </div>
            )}
        </div>
    );
}
