// An automation's table, a page of its rows at a time, read through the event
// the Table block pages with (`resource:dataset:rows`): each row opens in full,
// values in columns that look secret stay hidden until asked, and Download CSV
// saves every row. The table keeps its rows in the order they were added and
// reads no sort or filter, so the page offers none.
import { useEffect, useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { DownloadCsvButton } from '~/components/dashboard/FilePreviewDialog';
import { Skeleton } from '~/components/ui/skeleton';
import { sendEventAsync } from '~/lib/socket-sender';
import { cn } from '~/lib/utils';
import { ResourceDatasetRowsRequest } from '~/types/socket-events.generated';
import { BUTTON_GHOST } from '../buttons';
import { DataGrid, GridPager, PAGE_ROWS, SECRET_NOTE, columnsOf, useReveal, type GridRow } from './DataGrid';
import type { FileRef } from './model';
import { RecordDrawer } from './RecordDrawer';
import { Surface } from './ui';

export function DatasetRows({ table }: { table: FileRef }) {
    const id = table.entry.resourceId!;
    const name = table.entry.path;
    const [offset, setOffset] = useState(0);
    const [page, setPage] = useState<{ offset: number; rows: GridRow[]; total: number } | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [reads, setReads] = useState(0);
    const [open, setOpen] = useState<number | null>(null);
    useEffect(() => {
        let live = true;
        setError(null);
        sendEventAsync(ResourceDatasetRowsRequest.create({ resource_id: id, limit: PAGE_ROWS, offset })).then(
            (read) => live && setPage({ offset, rows: read.rows.map((r) => r.data as GridRow), total: read.total_count }),
            (e: unknown) => live && setError(e instanceof Error ? e.message : String(e))
        );
        return () => {
            live = false;
        };
    }, [id, offset, reads]);

    const rows = page?.offset === offset ? page.rows : undefined;
    // While the next page is read, the last one's columns hold the layout.
    const columns = useMemo(() => columnsOf(page?.rows ?? []), [page]);
    const reveal = useReveal(id, String(offset));
    const total = page?.total ?? null;
    const openRow = open !== null ? rows?.[open] : undefined;
    const turn = (to: number) => {
        setOpen(null);
        setOffset(to);
    };

    return (
        <>
            <div className="flex flex-wrap items-center justify-end gap-1">
                <DownloadCsvButton file={table.entry} className={cn(BUTTON_GHOST, 'h-8 px-2.5')} />
                <button type="button" aria-label="Refresh" title="Read it again" onClick={() => setReads((n) => n + 1)} className={cn(BUTTON_GHOST, 'h-8 w-8 justify-center px-0')}>
                    <RefreshCw className="h-4 w-4" />
                </button>
            </div>
            {error && !rows ? (
                <Surface>
                    <p role="alert" className="px-4 py-6 text-[13.5px] text-muted-foreground">
                        {error}{' '}
                        <button type="button" onClick={() => setReads((n) => n + 1)} className="font-medium text-foreground underline underline-offset-4">
                            Try again
                        </button>
                    </p>
                </Surface>
            ) : !page ? (
                <Surface>
                    {[0, 1, 2, 3].map((i) => (
                        <div key={i} className="flex items-center gap-6 border-b border-border px-4 py-3 last:border-0 dark:border-foreground/[0.06]" aria-busy>
                            <Skeleton className="h-3 w-24" />
                            <Skeleton className="h-3 w-32" />
                            <Skeleton className="h-3 w-16" />
                        </div>
                    ))}
                </Surface>
            ) : (
                <DataGrid
                    label={`Rows of ${name}`}
                    columns={columns}
                    rows={rows}
                    loadingRows={Math.min(PAGE_ROWS, Math.max(1, (total ?? PAGE_ROWS) - offset))}
                    onOpen={setOpen}
                    openRow={open}
                    reveal={reveal}
                    empty="No rows yet. Rows the automation or its interface adds land here."
                    footer={
                        rows && total !== null && total > 0 ? (
                            <GridPager
                                from={offset}
                                shown={rows.length}
                                total={total.toLocaleString('en-US')}
                                onPrevious={offset > 0 ? () => turn(Math.max(0, offset - PAGE_ROWS)) : undefined}
                                onNext={offset + rows.length < total ? () => turn(offset + PAGE_ROWS) : undefined}
                            />
                        ) : undefined
                    }
                />
            )}
            {columns.some((c) => c.secret) && <p className="text-[12.5px] leading-snug text-muted-foreground">{SECRET_NOTE}</p>}
            <RecordDrawer
                open={!!openRow}
                onOpenChange={(o) => !o && setOpen(null)}
                title={name}
                description={openRow ? `Row ${(offset + open! + 1).toLocaleString('en-US')}${total !== null ? ` of ${total.toLocaleString('en-US')}` : ''}` : undefined}
                fields={openRow ? columns.map((c) => ({ name: c.name, value: openRow[c.name], hidden: c.secret && !reveal.shown(open!, c.name), onReveal: () => reveal.showCell(open!, c.name) })) : []}
                steps={
                    openRow && rows
                        ? {
                              where: `Row ${(offset + open! + 1).toLocaleString('en-US')}`,
                              onPrevious: open! > 0 ? () => setOpen(open! - 1) : undefined,
                              onNext: open! < rows.length - 1 ? () => setOpen(open! + 1) : undefined,
                          }
                        : undefined
                }
            />
        </>
    );
}
