// In-place preview for a dashboard file: workflow resources render through the
// shared ResourceRenderer (image/video/audio/pdf/dataset/markdown/csv/text by
// mime), agent-workspace files through their signed URL. Download is always a
// click away; nothing opens a new tab unless the type has no inline preview.
import { useEffect, useState } from 'react';
import { Download, ExternalLink, FileText } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '~/components/ui/dialog';
import { ResourceRenderer, isWidePreview } from '~/components/resource/ResourceRenderer';
import { MarkdownRenderer } from '~/components/chat/MarkdownRenderer';
import { workspaceFileUrl } from '~/hooks/useAgentWorkspaceFiles';
import type { ResourceInfo } from '~/types/socket-events.generated';
import { cn } from '~/lib/utils';
import { dateLabel, fmtBytes } from '~/components/dashboard/primitives';
import type { FileEntry, FileSource } from '~/components/dashboard/types';

const MAX_TEXT_PREVIEW_BYTES = 512 * 1024;

export interface FilePreviewRequest {
    file: FileEntry;
    source: FileSource;
}

/** The ResourceInfo shape the shared renderer keys on (mime, type, name, id). */
function toResourceInfo(file: FileEntry, source: FileSource): ResourceInfo {
    return {
        id: file.resourceId ?? '',
        owner_id: '',
        organization_id: null,
        workflow_id: source.workflow?.id ?? '',
        node_id: null,
        resource_type: (file.resourceType ?? 'file') as ResourceInfo['resource_type'],
        name: file.path,
        mime_type: file.mime ?? null,
        size_bytes: file.size,
        storage_ref: null,
        metadata: file.rows != null ? { row_count: file.rows } : {},
        created_at: file.mtime,
        updated_at: file.mtime,
    } as ResourceInfo;
}

function WorkspaceTextPreview({ url, markdown }: { url: string; markdown: boolean }) {
    const [content, setContent] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
        const controller = new AbortController();
        setContent(null);
        setError(null);
        fetch(url, { signal: controller.signal })
            .then(async (res) => {
                if (!res.ok) throw new Error(`Failed to load file (${res.status})`);
                setContent(await res.text());
            })
            .catch((e) => {
                if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Failed to load file');
            });
        return () => controller.abort();
    }, [url]);
    if (error) return <p className="m-0 py-4 text-[13px] text-red-600 dark:text-red-400">{error}</p>;
    if (content === null) return <p className="m-0 py-4 text-[13px] text-foreground/60 dark:text-foreground/40">Loading…</p>;
    if (markdown) return <MarkdownRenderer content={content} className="text-[14px]" />;
    return <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-3 text-xs leading-relaxed text-foreground/90">{content}</pre>;
}

function WorkspacePreview({ file }: { file: FileEntry }) {
    if (!file.urlPath) return <p className="m-0 py-4 text-[13px] text-foreground/60 dark:text-foreground/40">This file has no signed link yet — reopen the Files view to refresh it.</p>;
    const url = workspaceFileUrl(file.urlPath);
    const ext = file.path.includes('.') ? file.path.slice(file.path.lastIndexOf('.') + 1).toLowerCase() : '';
    if (file.kind === 'image') return <img src={url} alt={file.path} className="max-h-[65vh] max-w-full rounded-lg object-contain" />;
    if (file.kind === 'video') {
        return (
            <video src={url} controls playsInline className="max-h-[65vh] w-full rounded-lg bg-black">
                <track kind="captions" />
            </video>
        );
    }
    if (file.kind === 'audio') {
        return (
            <audio src={url} controls className="w-full py-6">
                <track kind="captions" />
            </audio>
        );
    }
    const textLike = file.kind === 'doc' || file.kind === 'code' || file.kind === 'data' || ext === 'log';
    if (textLike && file.size <= MAX_TEXT_PREVIEW_BYTES && ext !== 'pdf') return <WorkspaceTextPreview url={url} markdown={ext === 'md'} />;
    return (
        <p className="m-0 py-4 text-[13px] text-foreground/60 dark:text-foreground/40">
            No inline preview for this file{file.size > MAX_TEXT_PREVIEW_BYTES ? ' (too large)' : ' type'} — use Download.
        </p>
    );
}

export function FilePreviewDialog({ request, onClose, onOpenWorkflow }: { request: FilePreviewRequest | null; onClose: () => void; onOpenWorkflow?: (source: FileSource) => void }) {
    const file = request?.file;
    const source = request?.source;
    const isResource = source?.kind === 'resources';
    const resource = file && source && isResource ? toResourceInfo(file, source) : null;
    const downloadHref = file
        ? isResource
            ? file.url ?? undefined
            : file.urlPath
              ? workspaceFileUrl(file.urlPath, { download: true })
              : undefined
        : undefined;
    const wide = resource ? isWidePreview(resource) : file?.kind === 'image' || file?.kind === 'video';
    return (
        <Dialog open={!!request} onOpenChange={(open) => { if (!open) onClose(); }}>
            <DialogContent data-testid="dashboard-file-preview" className={cn('flex max-h-[85vh] flex-col', wide ? 'max-w-4xl' : 'max-w-2xl')}>
                <DialogHeader className="shrink-0">
                    <DialogTitle className="flex min-w-0 items-center gap-2 text-sm font-medium">
                        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">{file?.path}</span>
                    </DialogTitle>
                    {file && source && (
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                            <span>{file.rows != null ? `${file.rows} rows` : fmtBytes(file.size)}</span>
                            <span>{dateLabel(file.mtime)}</span>
                            <span className="truncate">{source.label}</span>
                            {downloadHref && (
                                <a href={downloadHref} download target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-foreground/80 transition-colors hover:text-foreground">
                                    <Download className="h-3.5 w-3.5" /> Download
                                </a>
                            )}
                            {source.workflow && onOpenWorkflow && (
                                <button type="button" onClick={() => onOpenWorkflow(source)} className="inline-flex items-center gap-1 text-foreground/80 transition-colors hover:text-foreground">
                                    <ExternalLink className="h-3.5 w-3.5" /> Open workflow
                                </button>
                            )}
                        </div>
                    )}
                </DialogHeader>
                <div className="scrollbar-subtle min-h-0 flex-1 overflow-y-auto">
                    {file && source && (resource ? <ResourceRenderer resource={resource} url={file.url ?? undefined} /> : <WorkspacePreview file={file} />)}
                </div>
            </DialogContent>
        </Dialog>
    );
}
