// A machine's own files: its user's home folder and everything in it, agents' work or not, a folder at a time with
// crumbs that never go above home, a file previewed beside the list (text, a picture, or why not), downloaded, or
// uploaded into the folder open. On your own computer that's the noclick user's home there (in NoClick's VM on a Mac),
// not yours.
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Download, File, Folder, Upload, X } from 'lucide-react';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { Section, Surface } from '@/screens/resources/ui';
import { fmtBytes } from '@/lib/formatters';
import { relTime } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { useWorkV1 } from '../agents/reads';
import { useWorkClient } from '../client';
import {
    listMachineFiles,
    MACHINE_FILE_MAX,
    MACHINE_HOME,
    machineFiles,
    type MachineEntry,
} from './machineApi';
import { isUp, type MachineView } from './machineView';

const SMALL_SECONDARY = BUTTON_SECONDARY.replace('h-9', 'h-8').replace(
    'px-4',
    'px-3'
);
const ICON_BUTTON =
    'grid h-8 w-8 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground';
const IMAGE = /\.(png|jpe?g|gif|webp|svg)$/i;
const baseName = (path: string) => path.slice(path.lastIndexOf('/') + 1);

/** The crumbs from home down to `path`: each folder, and whether it's one you can open (home and below). */
export function crumbsOf(
    path: string
): { label: string; path: string; open: boolean }[] {
    const parts = path.split('/').filter(Boolean);
    const home = MACHINE_HOME.split('/').filter(Boolean).length;
    return parts.map((label, i) => ({
        label,
        path: `/${parts.slice(0, i + 1).join('/')}`,
        open: i + 1 >= home,
    }));
}

export function MachineDisk({ view }: { view: MachineView }) {
    const own = view.kind === 'own';
    return (
        <Section
            title="Files"
            meta={own ? 'the noclick user’s home folder' : 'its home folder'}
        >
            <div data-testid="machine-files">
                {isUp(view) ? (
                    <Browser view={view} />
                ) : (
                    <p className="text-[14px] text-muted-foreground">
                        {own
                            ? 'Its files show here while it’s online.'
                            : 'Its files show here while it runs.'}
                    </p>
                )}
            </div>
        </Section>
    );
}

function Browser({ view }: { view: MachineView }) {
    const client = useWorkClient();
    const [path, setPath] = useState(MACHINE_HOME);
    const [open, setOpen] = useState<MachineEntry | null>(null);
    const [uploading, setUploading] = useState(false);
    const picker = useRef<HTMLInputElement>(null);
    const key = `work:machine:${view.id}:files:${path}`;
    const listing = useWorkV1(key, (c) =>
        listMachineFiles(c, view.id, view.userId, path)
    );
    const now = new Date().toISOString();
    const go = (to: string) => {
        setPath(to);
        setOpen(null);
    };
    const upload = async (files: FileList | null) => {
        if (!files?.length) return;
        const list = [...files];
        const tooBig = list.find((f) => f.size > MACHINE_FILE_MAX);
        if (tooBig)
            return toast(`${tooBig.name} is over 16 MB`, {
                description:
                    'Uploads here are 16 MB or less. Copy bigger ones from the shell.',
            });
        setUploading(true);
        try {
            for (const f of list)
                await machineFiles(client, view.id, view.userId).write(
                    `${path}/${f.name}`,
                    f
                );
            toast(
                list.length === 1
                    ? `Uploaded ${list[0].name}`
                    : `Uploaded ${list.length} files`,
                { description: `Into ${path}.` }
            );
        } catch (error) {
            toast('Couldn’t upload it', {
                description:
                    error instanceof Error ? error.message : String(error),
            });
        } finally {
            setUploading(false);
            await listing.refresh();
        }
    };
    const entries = listing.data?.entries ?? [];
    return (
        <>
            <Surface>
                <div className="flex min-h-11 flex-wrap items-center gap-2 border-b border-border px-3 py-1.5 dark:border-foreground/[0.06]">
                    <nav
                        aria-label="Folder"
                        className="flex min-w-0 flex-1 flex-wrap items-center gap-0.5 font-mono text-[12.5px]"
                    >
                        <span className="text-muted-foreground">/</span>
                        {crumbsOf(path).map((c, i, all) => (
                            <span
                                key={c.path}
                                className="flex items-center gap-0.5"
                            >
                                <button
                                    type="button"
                                    disabled={!c.open || i === all.length - 1}
                                    onClick={() => go(c.path)}
                                    className={cn(
                                        'rounded-md px-1 py-0.5',
                                        c.open && i < all.length - 1
                                            ? 'text-foreground/85 hover:bg-foreground/[0.06]'
                                            : 'text-muted-foreground'
                                    )}
                                >
                                    {c.label}
                                </button>
                                {i < all.length - 1 && (
                                    <span className="text-muted-foreground">
                                        /
                                    </span>
                                )}
                            </span>
                        ))}
                    </nav>
                    <input
                        ref={picker}
                        type="file"
                        multiple
                        hidden
                        onChange={(e) =>
                            void upload(e.target.files).finally(
                                () => (e.target.value = '')
                            )
                        }
                        data-testid="machine-upload"
                    />
                    <button
                        type="button"
                        disabled={uploading}
                        onClick={() => picker.current?.click()}
                        className={SMALL_SECONDARY}
                    >
                        <Upload className="h-3.5 w-3.5" strokeWidth={2} />
                        {uploading ? 'Uploading…' : 'Upload'}
                    </button>
                </div>
                <div
                    className={cn(
                        'grid min-h-[180px]',
                        open && 'md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]'
                    )}
                >
                    <div
                        className={cn(
                            'min-w-0 py-1',
                            open &&
                                'max-md:hidden md:border-r md:border-border md:dark:border-foreground/[0.06]'
                        )}
                    >
                        {listing.data ? (
                            entries.length ? (
                                entries.map((e) => (
                                    <button
                                        key={e.path}
                                        type="button"
                                        aria-current={
                                            open?.path === e.path
                                                ? 'true'
                                                : undefined
                                        }
                                        onClick={() =>
                                            e.type === 'directory'
                                                ? go(e.path)
                                                : setOpen(
                                                      open?.path === e.path
                                                          ? null
                                                          : e
                                                  )
                                        }
                                        className={cn(
                                            'flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-[13.5px] transition-colors',
                                            open?.path === e.path
                                                ? 'bg-foreground/[0.07]'
                                                : 'hover:bg-foreground/[0.04]'
                                        )}
                                    >
                                        {e.type === 'directory' ? (
                                            <Folder
                                                className="h-4 w-4 shrink-0 text-muted-foreground"
                                                strokeWidth={1.75}
                                            />
                                        ) : (
                                            <File
                                                className="h-4 w-4 shrink-0 text-muted-foreground"
                                                strokeWidth={1.75}
                                            />
                                        )}
                                        <span className="min-w-0 flex-1 truncate">
                                            {baseName(e.path)}
                                        </span>
                                        {e.type === 'file' && (
                                            <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">
                                                {fmtBytes(e.size ?? 0)}
                                                {e.updatedAt
                                                    ? ` · ${relTime(e.updatedAt, now)}`
                                                    : ''}
                                            </span>
                                        )}
                                    </button>
                                ))
                            ) : (
                                <p className="px-3.5 py-3 text-[13.5px] text-muted-foreground">
                                    Nothing here yet.
                                </p>
                            )
                        ) : (
                            <p className="px-3.5 py-3 text-[13.5px] text-muted-foreground">
                                {listing.error !== undefined
                                    ? `Couldn’t list it: ${listing.error instanceof Error ? listing.error.message : String(listing.error)}`
                                    : 'Reading its files…'}
                            </p>
                        )}
                    </div>
                    {open && (
                        <Preview
                            view={view}
                            entry={open}
                            onClose={() => setOpen(null)}
                        />
                    )}
                </div>
            </Surface>
            <p className="mt-2 text-[12.5px] text-muted-foreground">
                {view.kind === 'own'
                    ? 'Everything in the noclick user’s home folder there, not your own home.'
                    : 'Everything in its home folder, what agents never touch included.'}{' '}
                Files up to 16 MB preview and download here.
            </p>
        </>
    );
}

function Preview({
    view,
    entry,
    onClose,
}: {
    view: MachineView;
    entry: MachineEntry;
    onClose: () => void;
}) {
    const client = useWorkClient();
    const tooBig = (entry.size ?? 0) > MACHINE_FILE_MAX;
    const bytes = useWorkV1(
        tooBig ? null : `work:machine:${view.id}:read:${entry.path}`,
        () => machineFiles(client, view.id, view.userId).read(entry.path)
    );
    const image = IMAGE.test(entry.path);
    const text = useMemo(
        () =>
            bytes.data && !image ? new TextDecoder().decode(bytes.data) : null,
        [bytes.data, image]
    );
    const [url, setUrl] = useState<string | null>(null);
    useEffect(() => {
        if (!bytes.data || !image) return;
        const made = URL.createObjectURL(new Blob([bytes.data as BlobPart]));
        setUrl(made);
        return () => URL.revokeObjectURL(made);
    }, [bytes.data, image]);
    const download = () => {
        if (!bytes.data) return;
        const href = URL.createObjectURL(new Blob([bytes.data as BlobPart]));
        const a = document.createElement('a');
        a.href = href;
        a.download = baseName(entry.path);
        a.click();
        URL.revokeObjectURL(href);
    };
    const binary = text !== null && text.includes('\u0000');
    return (
        <div className="flex min-w-0 flex-col" data-testid="machine-preview">
            <div className="flex items-center gap-2 border-b border-border py-1.5 pl-3.5 pr-2 dark:border-foreground/[0.06]">
                <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">
                    {baseName(entry.path)}
                </span>
                <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">
                    {fmtBytes(entry.size ?? 0)}
                </span>
                <button
                    type="button"
                    aria-label="Download"
                    disabled={!bytes.data}
                    onClick={download}
                    className={cn(ICON_BUTTON, 'disabled:opacity-40')}
                >
                    <Download className="h-4 w-4" strokeWidth={1.75} />
                </button>
                <button
                    type="button"
                    aria-label="Close the preview"
                    onClick={onClose}
                    className={ICON_BUTTON}
                >
                    <X className="h-4 w-4" />
                </button>
            </div>
            <div className="max-h-[340px] min-h-[140px] overflow-auto scrollbar-subtle">
                {tooBig ? (
                    <div className="grid gap-1 p-4 text-[13.5px]">
                        <span>
                            {fmtBytes(entry.size ?? 0)} is over the 16 MB a file
                            can be downloaded here.
                        </span>
                        <span className="text-muted-foreground">
                            Shrink it or split it from the shell first.
                        </span>
                    </div>
                ) : bytes.error !== undefined ? (
                    <p className="p-4 text-[13.5px] text-muted-foreground">
                        Couldn’t read it:{' '}
                        {bytes.error instanceof Error
                            ? bytes.error.message
                            : String(bytes.error)}
                    </p>
                ) : !bytes.data ? (
                    <p className="p-4 text-[13.5px] text-muted-foreground">
                        Reading…
                    </p>
                ) : image && url ? (
                    <img
                        src={url}
                        alt={baseName(entry.path)}
                        className="mx-auto max-h-[320px] p-3"
                    />
                ) : binary ? (
                    <p className="p-4 text-[13.5px] text-muted-foreground">
                        No preview for this kind of file. Download it to open
                        it.
                    </p>
                ) : (
                    <pre className="whitespace-pre-wrap break-words p-4 font-mono text-[12.5px] leading-relaxed text-foreground/90">
                        {text}
                    </pre>
                )}
            </div>
        </div>
    );
}
