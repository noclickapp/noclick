// A stored file's preview, in place on its page or in a dialog: the shared renderer by its content type, at its link.
// Download is a click away. A host that shows other files (an agent's workspace) or previews a table's rows hands its
// own parts in (`PreviewParts`); without them this previews what a workflow or the account keeps.
import { useState, type ComponentType } from 'react';
import { toast } from 'sonner';
import { Download, ExternalLink, FileText, Loader2 } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/ui/dialog';
import { countOf, dateLabel, fmtBytes } from '@/ui/primitives';
import { useReturnFocus } from '@/ui/useReturnFocus';
import { cn } from '@/ui/utils';
import { downloadTableCsv, type TableRow } from '@/lib/tableCsv';
import type { FileEntry, FileSource } from './files';
import { ResourceRenderer, isWidePreview, type ResourceInfo } from './ResourceRenderer';

export interface FilePreviewRequest {
    file: FileEntry;
    source: FileSource;
}

/** What a host adds to a preview, for files this module can't read by itself. */
export interface PreviewParts {
    /** The body for a file that isn't a kept one (an agent workspace's). */
    Body?: ComponentType<{ file: FileEntry; source: FileSource }>;
    /** Where such a file downloads from. */
    href?: (file: FileEntry, source: FileSource, download: boolean) => string | undefined;
    /** How a table's rows preview. */
    Dataset?: ComponentType<{ resource: ResourceInfo }>;
    /** Every row of a table, for its CSV. */
    readRows?: (file: FileEntry) => Promise<TableRow[]>;
}

/** What the shared renderer keys on (content type, stored type, name, id). */
export function toResourceInfo(file: FileEntry): ResourceInfo {
    return { id: file.resourceId ?? '', name: file.path, mime_type: file.mime ?? null, resource_type: file.resourceType ?? 'file', created_at: file.mtime };
}

/** The preview itself: the shared renderer for a kept file, the host's body for any other. */
export function FilePreviewBody({ file, source, parts }: { file: FileEntry; source: FileSource; parts?: PreviewParts }) {
    if (source.kind !== 'resources' && parts?.Body) return <parts.Body file={file} source={source} />;
    return <ResourceRenderer resource={toResourceInfo(file)} url={file.url ?? undefined} Dataset={parts?.Dataset} />;
}

/** Where a file downloads from: a kept file's link, or what the host says for another. */
export function fileDownloadHref(file: FileEntry, source: FileSource, parts?: PreviewParts): string | undefined {
    if (source.kind === 'resources') return file.url ?? undefined;
    return parts?.href?.(file, source, true);
}

/** Saves a table as CSV: every row `read` gives. */
export function DownloadCsvButton({ file, className, read }: { file: FileEntry; className?: string; read: () => Promise<TableRow[]> }) {
    const [busy, setBusy] = useState(false);
    if (!file.resourceId) return null;
    const save = async () => {
        setBusy(true);
        try {
            await downloadTableCsv(read, file.path);
        } catch (err) {
            toast.error(`Download failed: ${err instanceof Error ? err.message : String(err)}`);
        } finally {
            setBusy(false);
        }
    };
    return (
        <button type="button" onClick={() => void save()} disabled={busy} className={className}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />} Download CSV
        </button>
    );
}

export function FilePreviewDialog({
    request,
    onClose,
    onOpenWorkflow,
    parts,
}: {
    request: FilePreviewRequest | null;
    onClose: () => void;
    onOpenWorkflow?: (source: FileSource) => void;
    parts?: PreviewParts;
}) {
    const file = request?.file;
    const source = request?.source;
    const resource = file && source?.kind === 'resources' ? toResourceInfo(file) : null;
    const downloadHref = file && source ? fileDownloadHref(file, source, parts) : undefined;
    const wide = resource ? isWidePreview(resource) : file?.kind === 'image' || file?.kind === 'video';
    const returnFocus = useReturnFocus();
    const readRows = parts?.readRows;
    return (
        <Dialog
            open={!!request}
            onOpenChange={(open) => {
                if (!open) onClose();
            }}
        >
            <DialogContent {...returnFocus} data-testid="dashboard-file-preview" className={cn('flex max-h-[85vh] flex-col', wide ? 'max-w-4xl' : 'max-w-2xl')}>
                <DialogHeader className="shrink-0">
                    <DialogTitle className="flex min-w-0 items-center gap-2 text-sm font-medium">
                        <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">{file?.path}</span>
                    </DialogTitle>
                    {file && source && (
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                            {/* A file linked from a message comes with no size, time or place. */}
                            {file.rows != null ? <span>{countOf(file.rows, 'row')}</span> : file.size > 0 && <span>{fmtBytes(file.size)}</span>}
                            {file.mtime && <span>{dateLabel(file.mtime)}</span>}
                            {source.label && <span className="truncate">{source.label}</span>}
                            {downloadHref && (
                                <a href={downloadHref} download={file.path.slice(file.path.lastIndexOf('/') + 1)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-foreground/80 transition-colors hover:text-foreground">
                                    <Download className="h-3.5 w-3.5" /> Download
                                </a>
                            )}
                            {file.resourceType === 'dataset' && readRows && (
                                <DownloadCsvButton file={file} read={() => readRows(file)} className="inline-flex items-center gap-1 text-foreground/80 transition-colors hover:text-foreground disabled:opacity-60" />
                            )}
                            {source.workflow && onOpenWorkflow && (
                                <button type="button" onClick={() => onOpenWorkflow(source)} className="inline-flex items-center gap-1 text-foreground/80 transition-colors hover:text-foreground">
                                    <ExternalLink className="h-3.5 w-3.5" /> Open workflow
                                </button>
                            )}
                        </div>
                    )}
                </DialogHeader>
                <div className="scrollbar-subtle min-h-0 flex-1 overflow-y-auto">{file && source && <FilePreviewBody file={file} source={source} parts={parts} />}</div>
            </DialogContent>
        </Dialog>
    );
}
