// The Volumes drawer's file browser: one folder at a
// time from `volume.listdirPage`, breadcrumbs back up, and a download of any file through
// `volume.read`, since a volume has no public or signed links.
import { useState } from 'react';
import { ChevronRight, Download, FileText, Folder } from 'lucide-react';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import type { Volume, VolumeEntry } from 'noclick';
import { usePaged } from '@/sdk/usePaged';
import { ConsoleButton } from '../../ui/Button';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { TimeCell } from '../../ui/TimeCell';
import { errorText, Section } from './shared';
import { formatSize } from './StorageShared';

const PAGE = 50;

/** `/raw/weather` → `["/raw", "/raw/weather"]`: the folders a breadcrumb walks. */
export function pathTrail(path: string): string[] {
    const parts = path.split('/').filter(Boolean);
    return parts.map((_, i) => `/${parts.slice(0, i + 1).join('/')}`);
}

/** The last segment of a path: `/raw/weather/porto.parquet` → `porto.parquet`. */
export function leafName(path: string): string {
    const trimmed = path.replace(/\/+$/, '');
    return trimmed.slice(trimmed.lastIndexOf('/') + 1) || '/';
}

function Breadcrumbs({ volume, path, onPath }: { volume: Volume; path: string; onPath: (path: string) => void }) {
    const trail = pathTrail(path);
    const crumb = 'rounded px-1 py-0.5 font-mono text-[12px] text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground';
    const here = 'px-1 py-0.5 font-mono text-[12px] text-foreground';
    return (
        <nav aria-label="Folder" className="mb-2 flex min-w-0 flex-wrap items-center gap-0.5">
            {trail.length ? (
                <button type="button" className={crumb} onClick={() => onPath('/')}>
                    {volume.name}
                </button>
            ) : (
                <span aria-current="page" className={here}>
                    {volume.name}
                </span>
            )}
            {trail.map((p, i) => (
                <span key={p} className="inline-flex items-center gap-0.5">
                    <ChevronRight aria-hidden className="h-3 w-3 text-muted-foreground" />
                    {i === trail.length - 1 ? (
                        <span aria-current="page" className={here}>
                            {leafName(p)}
                        </span>
                    ) : (
                        <button type="button" className={crumb} onClick={() => onPath(p)}>
                            {leafName(p)}
                        </button>
                    )}
                </span>
            ))}
        </nav>
    );
}

function DownloadFile({ volume, entry }: { volume: Volume; entry: VolumeEntry }) {
    const [busy, setBusy] = useState(false);
    const name = leafName(entry.path);
    const download = async () => {
        setBusy(true);
        try {
            const bytes = await volume.read(entry.path);
            const url = URL.createObjectURL(new Blob([bytes as BlobPart]));
            const link = document.createElement('a');
            link.href = url;
            link.download = name;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
        } catch (e) {
            toast.error(errorText(e));
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleButton variant="ghost" size="sm" disabled={busy} onClick={() => void download()} aria-label={`Download ${name}`} title="Download" icon={<Download className="h-3.5 w-3.5" />}>
            <span className="hidden sm:inline">{busy ? 'Downloading…' : 'Download'}</span>
        </ConsoleButton>
    );
}

export function VolumeFiles({ volume, path, onPath }: { volume: Volume; path: string; onPath: (path: string) => void }) {
    const paged = usePaged(`volumes/${volume.id}/files?${path}`, (cursor) => volume.listdirPage(path, { cursor, limit: PAGE }), (e) => e.path);
    return (
        <Section title="Files">
            <Breadcrumbs volume={volume} path={path} onPath={onPath} />
            {paged.error !== undefined && !paged.rows.length ? (
                <ErrorPanel error={paged.error} onRetry={() => void paged.refresh()} />
            ) : paged.loading ? (
                <div aria-busy className="h-32 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : paged.rows.length ? (
                <div className={cn('rounded-lg border', HAIRLINE)}>
                    <ul aria-label={`Files in ${path === '/' ? volume.name : path}`} className={'m-0 list-none p-0'}>
                        {paged.rows.map((e) =>
                            e.type === 'directory' ? (
                                <li key={e.path}>
                                    <button type="button" onClick={() => onPath(e.path)} className="flex h-10 w-full items-center gap-2.5 px-3 text-left text-[13px] transition-colors hover:bg-foreground/[0.03]">
                                        <Folder aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
                                        <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-foreground">{leafName(e.path)}/</span>
                                        <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                                    </button>
                                </li>
                            ) : (
                                <li key={e.path} className="group flex h-10 items-center gap-2.5 pl-3 pr-1.5 text-[13px]">
                                    <FileText aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
                                    <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-foreground" title={e.path}>
                                        {leafName(e.path)}
                                    </span>
                                    <span className="w-16 shrink-0 text-right text-[12px] tabular-nums text-muted-foreground">{formatSize(e.size)}</span>
                                    <span className="hidden w-20 shrink-0 text-right text-[12px] text-muted-foreground sm:block">
                                        <TimeCell value={e.updatedAt} />
                                    </span>
                                    <span className="shrink-0 transition-opacity md:opacity-0 md:focus-within:opacity-100 md:group-hover:opacity-100">
                                        <DownloadFile volume={volume} entry={e} />
                                    </span>
                                </li>
                            )
                        )}
                    </ul>
                    {paged.loadMoreError !== undefined && <ErrorPanel error={paged.loadMoreError} onRetry={() => void paged.loadMore()} className={cn('rounded-none border-0 border-t', HAIRLINE)} />}
                    {paged.nextCursor && paged.loadMoreError === undefined && (
                        <div className={cn('flex justify-center border-t py-1.5', HAIRLINE)}>
                            <ConsoleButton variant="ghost" size="sm" onClick={() => void paged.loadMore()} disabled={paged.loadingMore}>
                                {paged.loadingMore ? 'Loading…' : 'Load more'}
                            </ConsoleButton>
                        </div>
                    )}
                </div>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">
                    {path !== '/' ? `Nothing in ${path}.` : 'No files yet. Your code writes them with volume.write, or a sandbox that mounts the volume does.'}
                </p>
            )}
        </Section>
    );
}
