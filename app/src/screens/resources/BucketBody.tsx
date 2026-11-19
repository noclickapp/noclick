// A bucket's page body: its files a folder at a time (`?path=`, a folder ending
// in /, or a file's key, whose panel opens over its folder), a page at a time in
// key order with the folders first. A file previews in place, downloads, copies
// a link and deletes; what it held before each change made through NoClick is
// kept 30 days, listed in its panel to restore. Files are added with a picker or
// by dropping them on the list, and the bucket is public or private. Buckets
// send no platform:resource frames, so its reads are read again on Refresh,
// after a change made here, and when the tab comes back.
import { useEffect, useRef, useState, type DragEvent } from 'react';
import { useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { ChevronRight, Copy, Download, Eye, Folder, Globe, Lock, PanelRightOpen, RefreshCw, RotateCcw, Upload } from 'lucide-react';
import { countOf, dateLabel, fmtBytes, relTime } from '@/ui/primitives';
import type { FileEntry, FileSource } from './files';
import { FilePreviewDialog, type FilePreviewRequest } from './FilePreview';
import { CopyButton } from '@/ui/CopyButton';
import { BUTTON_GHOST, BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { GridPager, PAGE_ROWS } from './DataGrid';
import { FileThumb, basename } from './fileParts';
import { RecordDrawer, type RecordField } from './RecordDrawer';
import { ConfirmAction, FolderTrail, RowDelete, Section, Surface } from './ui';
import { extensionOf, fileKindOf, previewType } from '@/lib/embedKind';
import { cn } from '@/ui/utils';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { NotFound, type Bucket, type BucketObject, type ObjectVersion } from 'noclick';
import { refusalText } from './items';
import { Pending, ROW } from './parts';

/** The most one upload here carries: the API's put. Bigger files go up from code, through a signed upload link. */
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
/** How long a link copied or downloaded here works. */
const LINK_S = 3600;
/** How long the platform keeps what a file held before a change. */
const VERSION_DAYS = 30;

const reads = (bucket: Bucket) => `resources:buckets/${bucket.id}`;

function entryOf(o: BucketObject, extra: Partial<FileEntry> = {}): FileEntry {
    return { path: o.key, size: o.size ?? 0, mtime: o.updatedAt?.toISOString() ?? '', kind: fileKindOf(o.key), ...extra };
}

/** "2h ago": a file written after the page's clock reads as now. */
function since(at: Date | null, now: string): string {
    if (!at) return '';
    const iso = at.toISOString();
    return relTime(iso, at.getTime() > Date.parse(now) ? iso : now);
}

const justNow = (when: string) => (when === 'now' ? 'just now' : when);

/** A link to a file: its public address while the bucket is public, else a signed link that works for an hour. */
async function fileLink(bucket: Bucket, key: string): Promise<string> {
    return bucket.public ? await bucket.url(key) : await bucket.signedUrl(key, { expiresIn: LINK_S });
}

async function copyLink(bucket: Bucket, key: string) {
    const name = basename(key);
    try {
        await navigator.clipboard.writeText(await fileLink(bucket, key));
        toast.success(bucket.public ? `Copied ${name}’s address` : `Copied a link to ${name}`, {
            description: bucket.public ? 'It works while the bucket is public.' : 'Anyone with it can open the file for the next hour.',
        });
    } catch (error) {
        toast.error(`Couldn’t copy a link to ${name}: ${refusalText(error)}`);
    }
}

/** Puts back a file deleted here: its last copy, kept with its versions. */
async function undoDelete(bucket: Bucket, key: string) {
    const name = basename(key);
    try {
        const last = (await bucket.versions(key)).find((v) => v.op === 'deleted');
        if (!last) throw new Error('Its last copy isn’t kept anymore.');
        await bucket.restoreVersion(key, last);
        invalidateV1('resources:buckets');
        toast.success(`Restored ${name}`);
    } catch (error) {
        toast.error(`Couldn’t restore ${name}: ${refusalText(error)}`);
    }
}

async function deleteFile(bucket: Bucket, key: string): Promise<boolean> {
    const name = basename(key);
    try {
        await bucket.remove(key);
    } catch (error) {
        toast.error(`Couldn’t delete ${name}: ${refusalText(error)}`);
        return false;
    }
    invalidateV1('resources:buckets');
    toast.success(`Deleted ${name}`, {
        description: `Its last copy is kept with its versions for ${VERSION_DAYS} days.`,
        action: { label: 'Undo', onClick: () => void undoDelete(bucket, key) },
    });
    return true;
}

/** A file in the preview dialog: opened at once, its content read as it shows (text through the API, the rest at a signed link). */
function useFilePreview(bucket: Bucket) {
    const [request, setRequest] = useState<FilePreviewRequest | null>(null);
    const showing = useRef<string | null>(null);
    const blobUrl = useRef<string | null>(null);
    const release = () => {
        if (blobUrl.current) URL.revokeObjectURL(blobUrl.current);
        blobUrl.current = null;
    };
    useEffect(() => release, []);
    const source: FileSource = { id: bucket.id, kind: 'resources', label: bucket.name, sublabel: 'Storage', files: [] };

    const close = () => {
        showing.current = null;
        release();
        setRequest(null);
    };
    const open = async (o: BucketObject) => {
        const mime = previewType(o.key, o.size);
        if (!mime) return;
        release();
        showing.current = o.key;
        setRequest({ file: entryOf(o, { mime, resourceType: 'file' }), source });
        try {
            // Text is read through the API (the store answers no other site's reads); the browser plays the rest from a link.
            const text = mime.startsWith('text/');
            const url = text ? URL.createObjectURL(new Blob([(await bucket.read(o.key)) as BlobPart], { type: mime })) : await bucket.signedUrl(o.key, { expiresIn: LINK_S });
            if (showing.current !== o.key) {
                if (text) URL.revokeObjectURL(url);
                return;
            }
            if (text) blobUrl.current = url;
            setRequest({ file: entryOf(o, { mime, resourceType: 'file', url }), source });
        } catch (error) {
            if (showing.current !== o.key) return;
            close();
            toast.error(`Couldn’t open ${basename(o.key)}: ${refusalText(error)}`);
        }
    };
    return { request, open, close };
}

/** Files picked or dropped, put in `folder` one at a time, the toast saying how far it got. */
function useUpload(bucket: Bucket, folder: string, listed: readonly BucketObject[]) {
    const [busy, setBusy] = useState(false);
    const upload = async (picked: File[]) => {
        const tooBig = picked.filter((f) => f.size > MAX_UPLOAD_BYTES);
        const files = picked.filter((f) => f.size <= MAX_UPLOAD_BYTES);
        if (tooBig.length) {
            toast.error(tooBig.length === 1 ? `${tooBig[0].name} is over 100 MB` : `${tooBig.length} files are over 100 MB`, {
                description: 'Files up to 100 MB upload here. Bigger ones go up from your code, through a signed upload link.',
            });
        }
        if (!files.length) return;
        const replaced = files.filter((f) => listed.some((o) => o.key === folder + f.name)).length;
        const id = toast.loading(`Uploading ${files[0].name}…`);
        setBusy(true);
        let done = 0;
        try {
            for (const file of files) {
                toast.loading(files.length > 1 ? `Uploading ${file.name} (${done + 1} of ${files.length})…` : `Uploading ${file.name}…`, { id });
                await bucket.put(folder + file.name, file, file.type ? { contentType: file.type } : {});
                done += 1;
            }
            toast.success(files.length === 1 ? `Uploaded ${files[0].name}` : `Uploaded ${files.length} files`, {
                id,
                description: replaced
                    ? replaced === 1 && files.length === 1
                        ? `It replaced the file of the same name, whose copy is kept with its versions for ${VERSION_DAYS} days.`
                        : `${countOf(replaced, 'file')} of the same names ${replaced === 1 ? 'was' : 'were'} replaced; their copies are kept with their versions for ${VERSION_DAYS} days.`
                    : undefined,
            });
        } catch (error) {
            toast.error(`Couldn’t upload ${files[done].name}: ${refusalText(error)}`, { id, description: done ? `${countOf(done, 'file')} before it uploaded.` : undefined });
        } finally {
            setBusy(false);
            // Its size and file count follow once the platform measures it again.
            invalidateV1('resources:buckets');
        }
    };
    return { upload, busy };
}

const LINE = 'border-b border-border last:border-0 dark:border-foreground/[0.06]';
const ROW_ICON = 'shrink-0 rounded-full p-1.5 text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

function Files({
    bucket,
    folder,
    now,
    onGo,
    onPreview,
}: {
    bucket: Bucket;
    folder: string;
    now: string;
    onGo: (path: string) => void;
    onPreview: (o: BucketObject) => void;
}) {
    // The pages read so far, back to the first: each the cursor that reads it and where it starts.
    const [pages, setPages] = useState<{ cursor?: string; from: number }[]>([{ from: 0 }]);
    const at = pages[pages.length - 1];
    const page = useV1(`${reads(bucket)}/objects?${JSON.stringify([folder, at.cursor ?? null])}`, () =>
        bucket.objectsPage({ prefix: folder || undefined, delimiter: '/', cursor: at.cursor, limit: PAGE_ROWS })
    );
    const entries = page.data?.data;
    const folders = entries?.filter((e) => e.isFolder) ?? [];
    const files = entries?.filter((e) => !e.isFolder) ?? [];
    const [confirming, setConfirming] = useState<string | null>(null);
    const { upload, busy } = useUpload(bucket, folder, files);
    const picker = useRef<HTMLInputElement>(null);
    const [dragging, setDragging] = useState(false);
    const depth = useRef(0);
    const where = folder ? folder.slice(0, -1).split('/').pop() : bucket.name;

    const carriesFiles = (e: DragEvent) => e.dataTransfer.types.includes('Files');
    const drop = (e: DragEvent) => {
        if (!carriesFiles(e)) return;
        e.preventDefault();
        depth.current = 0;
        setDragging(false);
        const items = [...e.dataTransfer.items].filter((i) => i.kind === 'file');
        const folderCount = items.filter((i) => i.webkitGetAsEntry()?.isDirectory).length;
        if (folderCount) toast(folderCount === 1 ? 'A folder isn’t uploaded here' : 'Folders aren’t uploaded here', { description: 'Drop the files in it instead.' });
        void upload(items.filter((i) => !i.webkitGetAsEntry()?.isDirectory).flatMap((i) => i.getAsFile() ?? []));
    };

    const pick = () => picker.current?.click();
    const empty = entries !== undefined && entries.length === 0 && pages.length === 1;

    return (
        <Section
            title="Files"
            meta={!folder && bucket.objectCount != null ? bucket.objectCount.toLocaleString('en-US') : undefined}
            action={
                <span className="flex items-center gap-1">
                    <button type="button" aria-label="Refresh" title="Read it again" onClick={() => invalidateV1(reads(bucket))} className={cn(BUTTON_GHOST, 'h-9 w-9 justify-center px-0')}>
                        <RefreshCw className="h-4 w-4" />
                    </button>
                    <button type="button" className={BUTTON_SECONDARY} onClick={pick} disabled={busy}>
                        <Upload className="h-4 w-4" />
                        Upload
                    </button>
                    <input
                        ref={picker}
                        type="file"
                        multiple
                        className="hidden"
                        aria-label="Files to upload"
                        onChange={(e) => {
                            const chosen = [...(e.target.files ?? [])];
                            e.target.value = '';
                            void upload(chosen);
                        }}
                    />
                </span>
            }
        >
            <FolderTrail dir={folder} onGo={onGo} />
            <div
                className="relative"
                data-testid="bucket-drop"
                onDragEnter={(e) => {
                    if (!carriesFiles(e)) return;
                    e.preventDefault();
                    depth.current += 1;
                    setDragging(true);
                }}
                onDragOver={(e) => {
                    if (!carriesFiles(e)) return;
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'copy';
                }}
                onDragLeave={(e) => {
                    if (!carriesFiles(e)) return;
                    depth.current = Math.max(0, depth.current - 1);
                    if (!depth.current) setDragging(false);
                }}
                onDrop={drop}
            >
                {page.data === undefined ? (
                    <Pending read={page} rows={4} />
                ) : empty && !folder ? (
                    <Surface>
                        <div className="flex flex-col items-center px-6 py-14 text-center">
                            <span className="grid h-11 w-11 place-items-center rounded-full bg-foreground/[0.05]">
                                <Upload className="h-5 w-5 text-foreground/70" strokeWidth={1.75} />
                            </span>
                            <p className="mt-4 text-[15px] font-semibold text-foreground">No files yet</p>
                            <p className="mt-1 max-w-sm text-[14px] leading-relaxed text-muted-foreground">Drop files here to upload them, up to 100 MB each. Your websites and agents add theirs as they work.</p>
                            <button type="button" className={cn(BUTTON_SECONDARY, 'mt-5')} onClick={pick} disabled={busy}>
                                Choose files
                            </button>
                        </div>
                    </Surface>
                ) : empty ? (
                    <p className="text-[13.5px] text-muted-foreground">
                        Nothing is in {folder} now.{' '}
                        <button type="button" onClick={() => onGo('')} className="font-medium text-foreground underline underline-offset-4">
                            See every file
                        </button>
                    </p>
                ) : (
                    <Surface>
                        <ul aria-label={`Files in ${where}`}>
                            {folders.map((f) => (
                                <li key={f.key} className={LINE}>
                                    <button
                                        type="button"
                                        onClick={() => onGo(f.key)}
                                        className="group flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-foreground/[0.03] focus-visible:bg-foreground/[0.03] focus-visible:outline-none"
                                    >
                                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-foreground/[0.05]">
                                            <Folder className="h-4 w-4 text-foreground/65 dark:text-foreground/50" strokeWidth={1.75} />
                                        </span>
                                        <span className="min-w-0 flex-1 truncate text-[14px] text-foreground">{f.key.slice(folder.length, -1)}</span>
                                        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-muted-foreground" />
                                    </button>
                                </li>
                            ))}
                            {files.map((o) => {
                                const name = basename(o.key);
                                return (
                                    <li key={o.key} className={cn(LINE, 'group flex items-center gap-3 py-2.5 pl-4 pr-2.5')}>
                                        <button
                                            type="button"
                                            title={o.key}
                                            // A file opens in place where it can; the rest open their panel, with the download.
                                            onClick={() => (previewType(o.key, o.size) ? onPreview(o) : onGo(o.key))}
                                            className="flex min-w-0 flex-1 items-center gap-3 rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                        >
                                            <FileThumb file={entryOf(o)} />
                                            <span className="min-w-0 flex-1 truncate text-[14px] text-foreground">{name}</span>
                                        </button>
                                        <span className="hidden w-12 shrink-0 truncate text-[12px] uppercase tracking-wide text-muted-foreground md:inline">{extensionOf(o.key)}</span>
                                        <span className="hidden w-16 shrink-0 text-right text-[12.5px] tabular-nums text-muted-foreground sm:inline">{o.size != null ? fmtBytes(o.size) : ''}</span>
                                        <span className="hidden w-20 shrink-0 text-right text-[12.5px] tabular-nums text-muted-foreground sm:inline">{since(o.updatedAt, now)}</span>
                                        <button type="button" aria-label={`Details of ${name}`} title="Details and versions" onClick={() => onGo(o.key)} className={cn(ROW_ICON, 'text-muted-foreground/70')}>
                                            <PanelRightOpen className="h-4 w-4" />
                                        </button>
                                        <RowDelete
                                            name={name}
                                            asking={confirming === o.key}
                                            onAsk={(ask) => setConfirming(ask ? o.key : null)}
                                            onConfirm={() => {
                                                setConfirming(null);
                                                void deleteFile(bucket, o.key);
                                            }}
                                        />
                                    </li>
                                );
                            })}
                        </ul>
                        {(pages.length > 1 || page.data.nextCursor) && (
                            <GridPager
                                noun="Items"
                                from={at.from}
                                shown={page.data.data.length}
                                total={null}
                                onPrevious={pages.length > 1 ? () => setPages((p) => p.slice(0, -1)) : undefined}
                                onNext={page.data.nextCursor ? () => setPages((p) => [...p, { cursor: page.data!.nextCursor!, from: at.from + page.data!.data.length }]) : undefined}
                            />
                        )}
                    </Surface>
                )}
                {dragging && (
                    <div
                        aria-hidden
                        className="pointer-events-none absolute inset-0 grid place-items-center rounded-2xl border-2 border-dashed border-foreground/30 bg-background/85 text-[14px] font-medium text-foreground backdrop-blur-[2px]"
                    >
                        <span className="flex items-center gap-2">
                            <Upload className="h-4 w-4" />
                            Drop to upload to {where}
                        </span>
                    </div>
                )}
            </div>
        </Section>
    );
}

/** Whether its files open at plain addresses, and the switch, asked once in place. */
function PublicAccess({ bucket }: { bucket: Bucket }) {
    // What a change answered, until the list read again carries it.
    const [changed, setChanged] = useState<{ public: boolean; base: string | null } | null>(null);
    useEffect(() => setChanged(null), [bucket]);
    const open = changed?.public ?? bucket.public;
    const base = changed ? changed.base : bucket.publicBaseUrl;
    const change = async (to: boolean) => {
        try {
            const updated = await bucket.update({ public: to });
            setChanged({ public: updated.public, base: updated.publicBaseUrl });
            invalidateV1('resources:buckets');
            toast.success(to ? `${bucket.name} is public` : `${bucket.name} is private`, {
                description: to ? 'Each file opens at its own address, for anyone who has it.' : 'Its public addresses stopped working. Links copied from here work until they expire.',
            });
        } catch (error) {
            toast.error(refusalText(error));
        }
    };
    const Icon = open ? Globe : Lock;
    return (
        <Section title="Public access">
            <Surface>
                <div className={cn(ROW, 'flex-wrap')}>
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-foreground/[0.05]">
                        <Icon className="h-4 w-4 text-foreground/65 dark:text-foreground/50" strokeWidth={1.75} />
                    </span>
                    <span className="min-w-0 flex-1 basis-56">
                        <span className="block text-[14px] text-foreground">{open ? 'Public' : 'Private'}</span>
                        <span className="block text-[12.5px] text-muted-foreground">
                            {open ? 'Each file opens at its own address, for anyone who has it.' : 'Its files open only through your code, or a link copied here that works for an hour.'}
                        </span>
                    </span>
                    {open ? (
                        <ConfirmAction label="Make private" confirm="Stop its public addresses" icon={Lock} onConfirm={() => change(false)} />
                    ) : (
                        <ConfirmAction label="Make public" confirm="Make every file public" icon={Globe} onConfirm={() => change(true)} />
                    )}
                </div>
                {open && base && (
                    <div className={cn(ROW, 'py-2.5')}>
                        <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-muted-foreground" title={`${base}/`}>
                            {base}/<span className="text-muted-foreground/60">your-file</span>
                        </span>
                        <CopyButton value={`${base}/`} className="-my-1 [&_svg]:h-3.5 [&_svg]:w-3.5" />
                    </div>
                )}
            </Surface>
        </Section>
    );
}

function VersionRow({ version, onRestore }: { version: ObjectVersion; onRestore: () => Promise<void> }) {
    const [busy, setBusy] = useState(false);
    return (
        <div className={cn(ROW, 'py-2.5')}>
            <span className="min-w-0 flex-1">
                <span className="block text-[14px] text-foreground">{version.op === 'deleted' ? 'Before it was deleted' : 'Before it was replaced'}</span>
                <span className="block text-[12.5px] tabular-nums text-muted-foreground">
                    {[version.replacedAt ? dateLabel(version.replacedAt.toISOString()) : null, version.size != null ? fmtBytes(version.size) : null].filter(Boolean).join(' · ')}
                </span>
            </span>
            <button
                type="button"
                disabled={busy}
                className={cn(BUTTON_GHOST, 'h-8 px-3')}
                onClick={async () => {
                    setBusy(true);
                    try {
                        await onRestore();
                    } finally {
                        setBusy(false);
                    }
                }}
            >
                <RotateCcw className="h-3.5 w-3.5" />
                Restore
            </button>
        </div>
    );
}

/** One file in full, over its folder: what it is, ways to open, link and delete it, and what it held before. */
function FilePanel({
    bucket,
    fileKey,
    now,
    onClose,
    onPreview,
}: {
    bucket: Bucket;
    fileKey: string | null;
    now: string;
    onClose: () => void;
    onPreview: (o: BucketObject) => void;
}) {
    const key = fileKey ?? '';
    const head = useV1(fileKey !== null ? `${reads(bucket)}/head?${key}` : null, () => bucket.head(key));
    const versions = useV1(fileKey !== null ? `${reads(bucket)}/versions?${key}` : null, () => bucket.versions(key));
    // A read that failed keeps what it last had: a file deleted from here is gone once its read says so.
    const gone = head.error instanceof NotFound;
    const file = !gone && head.data?.key === key ? head.data : undefined;
    // A signed link either way: the browser saves (or opens) it.
    const link = useV1(file ? `${reads(bucket)}/link?${key}` : null, () => bucket.signedUrl(key, { expiresIn: LINK_S }));
    const lastCopy = versions.data?.find((v) => v.op === 'deleted');
    const name = basename(key);
    const where = [bucket.name, ...key.split('/').slice(0, -1)].join(' / ');

    const restore = async (version: ObjectVersion) => {
        try {
            await bucket.restoreVersion(key, version);
        } catch (error) {
            toast.error(`Couldn’t restore ${name}: ${refusalText(error)}`);
            return;
        }
        invalidateV1('resources:buckets');
        toast.success(`Restored ${name}`, { description: 'What it held before is kept as a version too.' });
    };

    const fields: RecordField[] = [
        { name: 'Key', value: key, display: <span className="font-mono text-[13px]">{key}</span>, copy: true },
        ...(file
            ? [
                  { name: 'Type', value: file.contentType ?? '—' },
                  { name: 'Size', value: file.size != null ? `${fmtBytes(file.size)}${file.size >= 1024 ? ` (${file.size.toLocaleString('en-US')} bytes)` : ''}` : '—' },
                  { name: 'Modified', value: file.updatedAt ? `${dateLabel(file.updatedAt.toISOString())} · ${since(file.updatedAt, now)}` : '—' },
                  ...(Object.keys(file.metadata).length
                      ? [
                            {
                                name: 'Metadata',
                                value: file.metadata,
                                display: (
                                    <dl className="m-0 space-y-0.5 font-mono text-[12.5px]">
                                        {Object.entries(file.metadata).map(([k, v]) => (
                                            <div key={k} className="flex gap-2">
                                                <dt className="shrink-0 text-muted-foreground">{k}</dt>
                                                <dd className="m-0 min-w-0 break-all text-foreground">{v}</dd>
                                            </div>
                                        ))}
                                    </dl>
                                ),
                            },
                        ]
                      : []),
              ]
            : []),
    ];
    const previewable = file ? previewType(file.key, file.size) !== null : false;

    return (
        <RecordDrawer
            open={fileKey !== null}
            onOpenChange={(open) => !open && onClose()}
            title={name}
            description={where}
            names="words"
            fields={fields}
            actions={
                file ? (
                    <>
                        {previewable && (
                            <button type="button" className={BUTTON_PRIMARY} onClick={() => onPreview(file)}>
                                <Eye className="h-4 w-4" />
                                Preview
                            </button>
                        )}
                        <a
                            href={link.data}
                            download={name}
                            target="_blank"
                            rel="noreferrer"
                            aria-disabled={!link.data}
                            className={cn(previewable ? BUTTON_SECONDARY : BUTTON_PRIMARY, !link.data && 'pointer-events-none opacity-50')}
                        >
                            <Download className="h-4 w-4" />
                            Download
                        </a>
                        <button type="button" className={BUTTON_SECONDARY} onClick={() => void copyLink(bucket, key)}>
                            <Copy className="h-4 w-4" />
                            Copy link
                        </button>
                    </>
                ) : undefined
            }
        >
            {gone ? (
                <p className="m-0 mt-5 rounded-xl border border-border bg-foreground/[0.03] px-4 py-3 text-[13.5px] leading-snug text-foreground dark:border-foreground/[0.08]">
                    No file is at this key now.
                    {lastCopy ? ` It was deleted ${justNow(since(lastCopy.replacedAt, now))}: restore its last copy below.` : ''}
                </p>
            ) : (
                !file && (
                    <div className="mt-5">
                        <Pending read={head} rows={2} />
                    </div>
                )
            )}
            <section className="mt-8">
                <h3 className="mb-1 text-[14px] font-semibold text-foreground">Earlier versions</h3>
                <p className="m-0 mb-3 text-[12.5px] leading-snug text-muted-foreground">
                    What it held before each change made through NoClick, kept {VERSION_DAYS} days. Restoring one keeps what it holds now as a version too.
                </p>
                <Pending read={versions} rows={2} />
                {versions.data &&
                    (versions.data.length ? (
                        <Surface>
                            {versions.data.map((v) => (
                                <VersionRow key={v.id} version={v} onRestore={() => restore(v)} />
                            ))}
                        </Surface>
                    ) : (
                        <p className="m-0 text-[13.5px] text-muted-foreground">None yet.</p>
                    ))}
            </section>
            {file && (
                <section className="mt-8 flex flex-wrap items-center gap-x-3 gap-y-2">
                    <ConfirmAction label="Delete file" confirm={`Delete ${name}`} onConfirm={async () => void (await deleteFile(bucket, key))} />
                    <span className="text-[12.5px] text-muted-foreground">Its last copy is kept with its versions for {VERSION_DAYS} days.</span>
                </section>
            )}
        </RecordDrawer>
    );
}

export function BucketBody({ bucket, now }: { bucket: Bucket; now: string }) {
    const [params, setParams] = useSearchParams();
    const path = params.get('path') ?? '';
    const cut = path.lastIndexOf('/') + 1;
    const folder = path.slice(0, cut);
    const fileKey = cut < path.length ? path : null;
    const go = (to: string, replace = false) =>
        setParams(
            (prev) => {
                const next = new URLSearchParams(prev);
                if (to) next.set('path', to);
                else next.delete('path');
                return next;
            },
            { replace }
        );
    const preview = useFilePreview(bucket);
    return (
        <>
            <Files key={`${bucket.id}:${folder}`} bucket={bucket} folder={folder} now={now} onGo={(to) => go(to)} onPreview={(o) => void preview.open(o)} />
            <PublicAccess bucket={bucket} />
            <FilePanel bucket={bucket} fileKey={fileKey} now={now} onClose={() => go(folder, true)} onPreview={(o) => void preview.open(o)} />
            <FilePreviewDialog request={preview.request} onClose={preview.close} />
        </>
    );
}
