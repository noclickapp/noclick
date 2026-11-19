// An agent's one /workspace, the folder as it is (design A): its real folders with a breadcrumb (the inbox, each chat
// in it by the chat's name, what you added, the agent's own), each file saying where it came from (read from its path),
// its size and when; the file open beside the list on a wide page, else as a sheet (a phone, the profile's Files tab),
// with its full /workspace path, Download and Copy path. Upload goes into `added/`; Delete asks on the row first.
// Shown on the agent's profile in Work and on its page under Resources → Agents.
import { useMemo, useRef, useState, type ChangeEvent } from 'react';
import { toast } from 'sonner';
import { ChevronRight, Copy, Download, Folder, Upload } from 'lucide-react';
import { invalidateV1 } from '@/sdk/useV1';
import { FilePreviewBody, fileDownloadHref } from '@/screens/resources/FilePreview';
import { useSlot } from '@/slots';
import { FILE_PREVIEW } from '../slots';
import { clockLabel, countOf, fmtBytes } from '@/lib/formatters';
import type { FileEntry, FileSource } from '@/screens/resources/files';
import { useInPhoneShell } from '@/ui/phoneBar';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { ShellDialog } from '@/ui/ShellDialog';
import { basename, FileThumb, folderListing } from '@/screens/resources/fileParts';
import { ConfirmAction, RowDelete, Surface } from '@/screens/resources/ui';
import { Skeleton } from '@/ui/skeleton';
import { cn } from '@/ui/utils';
import { listedAgent } from '../agents/reads';
import { useWorkClient } from '../client';
import { useActiveSession } from '../conversation/sessions';
import { dayOf } from '../conversation/Timeline';
import { AppMark } from '../newAgent/wakes';
import { ADDED, folderLabel, originLine, originOf, useAgentWorkspace, workspaceKey } from './workspace';

export interface AgentFilesProps {
    agentId: string;
    /** As Work names it ("Your NoClick" for the account's own). */
    name: string;
    /** `beside`: the open file sits beside the list (a sheet still on a phone); `sheet`: it always opens as a sheet. */
    preview: 'beside' | 'sheet';
}

const MOUNT = '/workspace';
const PILL = BUTTON_SECONDARY.replace('h-9', 'h-8').replace('px-4', 'px-3.5');
const ROW = 'group flex w-full min-w-0 items-center gap-3 border-b border-border px-4 py-2.5 text-left last:border-0 dark:border-foreground/[0.06]';

const whenOf = (file: FileEntry) => `${dayOf(Date.parse(file.mtime))} ${clockLabel(file.mtime)}`;

/** Where a file came from, as its row says it: a sent file with its app's mark. */
function Origin({ path, name, short }: { path: string; name: string; short?: boolean }) {
    const origin = originOf(path);
    return (
        <span className="inline-flex min-w-0 items-center gap-1.5">
            {origin.by === 'whatsapp' && <AppMark nodeType="automation-whatsapp" className="h-3.5 w-3.5" />}
            <span className="truncate">{originLine(origin, name, short)}</span>
        </span>
    );
}

export function AgentFiles({ agentId, name, preview }: AgentFilesProps) {
    const client = useWorkClient();
    const session = useActiveSession(agentId);
    const listing = useAgentWorkspace(agentId);
    const phone = useInPhoneShell();
    const beside = preview === 'beside' && !phone;
    // The folder open ('' its top, else ending in /), the file picked, the row asking to delete.
    const [dir, setDir] = useState('');
    const [picked, setPicked] = useState<string | null>(null);
    const [confirming, setConfirming] = useState<string | null>(null);
    const input = useRef<HTMLInputElement>(null);

    const files = listing.data;
    const here = useMemo(() => (files ? folderListing(files, dir) : null), [files, dir]);
    // Beside the list, the folder's newest file is open until another is picked.
    const open = files?.find((f) => f.path === picked) ?? (beside ? here?.files[0] : undefined);
    const source: FileSource = { id: `agent:${agentId}`, kind: 'workspace', label: name, sublabel: `${name}’s workspace`, mount: MOUNT, files: files ?? [] };
    const workspace = () => listedAgent(client, agentId).workspace(session!);
    const reread = () => invalidateV1(workspaceKey(agentId));
    const go = (to: string) => {
        setDir(to);
        setPicked(null);
        setConfirming(null);
    };

    const upload = async (e: ChangeEvent<HTMLInputElement>) => {
        const chosen = Array.from(e.target.files ?? []);
        e.target.value = '';
        if (!chosen.length || !session) return;
        const id = toast.loading(`Uploading ${chosen.length === 1 ? chosen[0].name : `${chosen.length} files`}…`);
        try {
            for (const file of chosen) await workspace().write(`${ADDED}/${file.name}`, new Uint8Array(await file.arrayBuffer()));
            toast.success(`Uploaded to ${MOUNT}/${ADDED}. ${name} can use ${chosen.length === 1 ? 'it' : 'them'} now.`, { id });
            go(`${ADDED}/`);
            reread();
        } catch (err) {
            toast.error(`Couldn’t upload: ${err instanceof Error ? err.message : String(err)}`, { id });
        }
    };
    const remove = async (file: FileEntry) => {
        setConfirming(null);
        try {
            await workspace().delete(file.path);
            if (picked === file.path) setPicked(null);
            toast(`Deleted ${basename(file.path)}. ${name} can’t see it any more.`);
            reread();
        } catch (err) {
            toast.error(`Couldn’t delete it: ${err instanceof Error ? err.message : String(err)}`);
        }
    };

    const segments = dir ? dir.slice(0, -1).split('/') : [];
    const upTo = (n: number) => (n ? `${segments.slice(0, n).join('/')}/` : '');
    const crumbs = (
        <nav aria-label="Folder" className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto text-[13px] text-muted-foreground scrollbar-hide">
            <button type="button" onClick={() => go('')} className="shrink-0 rounded-full px-2 py-1 transition-colors hover:bg-foreground/[0.05] hover:text-foreground">
                workspace
            </button>
            {segments.map((_, i) => {
                const label = folderLabel(segments.slice(0, i + 1).join('/'));
                return (
                    <span key={i} className="flex shrink-0 items-center gap-0.5">
                        <ChevronRight className="h-3.5 w-3.5 opacity-60" />
                        {i === segments.length - 1 ? (
                            <span aria-current="location" className="px-2 py-1 font-medium text-foreground">
                                {label}
                            </span>
                        ) : (
                            <button type="button" onClick={() => go(upTo(i + 1))} className="rounded-full px-2 py-1 transition-colors hover:bg-foreground/[0.05] hover:text-foreground">
                                {label}
                            </button>
                        )}
                    </span>
                );
            })}
        </nav>
    );

    let list;
    if (!files) {
        list =
            listing.error !== undefined ? (
                <p className="text-[13.5px] text-muted-foreground">
                    Couldn’t read its files.{' '}
                    <button type="button" onClick={() => void listing.refresh()} className="font-medium text-foreground underline underline-offset-4">
                        Try again
                    </button>
                </p>
            ) : (
                <Surface>
                    {[0, 1, 2].map((i) => (
                        <div key={i} className={ROW}>
                            <Skeleton className="h-8 w-8 rounded-lg" />
                            <Skeleton className="h-3.5 w-1/3" />
                        </div>
                    ))}
                </Surface>
            );
    } else if (!here!.folders.length && !here!.files.length) {
        list = (
            <p className="rounded-2xl border border-dashed border-border px-4 py-6 text-center text-[13.5px] text-muted-foreground dark:border-foreground/[0.1]">
                {dir ? 'Nothing here yet.' : `Nothing in ${MOUNT} yet. Files people send ${name}, what it makes and what you upload land here.`}
            </p>
        );
    } else {
        list = (
            <Surface>
                {here!.folders.map((f) => (
                    <button key={f.path} type="button" onClick={() => go(f.path)} className={cn(ROW, 'transition-colors hover:bg-foreground/[0.03] focus-visible:bg-foreground/[0.03] focus-visible:outline-none')}>
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-foreground/[0.05]">
                            <Folder className="h-4 w-4 text-foreground/65" strokeWidth={1.75} />
                        </span>
                        <span className="min-w-0 flex-1">
                            <span className="block truncate text-[14px] text-foreground">{folderLabel(f.path)}</span>
                            <span className="block text-[12.5px] text-muted-foreground">{countOf(f.files, 'file')}</span>
                        </span>
                        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform duration-200 group-hover:translate-x-0.5" />
                    </button>
                ))}
                {here!.files.map((file) => (
                    <div key={file.path} data-file={file.path} className={cn(ROW, open?.path === file.path && beside && 'bg-foreground/[0.04]')}>
                        <button type="button" onClick={() => setPicked(file.path)} className="flex min-w-0 flex-1 items-center gap-3 text-left focus-visible:outline-none">
                            <FileThumb file={file} />
                            <span className="min-w-0 flex-1">
                                <span className="block truncate text-[14px] text-foreground">{basename(file.path)}</span>
                                <span className="flex min-w-0 items-center gap-1.5 text-[12.5px] text-muted-foreground">
                                    <Origin path={file.path} name={name} short />
                                    <span aria-hidden>·</span>
                                    <span className="shrink-0 tabular-nums">{fmtBytes(file.size)}</span>
                                </span>
                            </span>
                        </button>
                        <span className={cn('shrink-0 text-[12.5px] tabular-nums text-muted-foreground', confirming === file.path && 'hidden')}>{whenOf(file)}</span>
                        <RowDelete name={basename(file.path)} asking={confirming === file.path} onAsk={(ask) => setConfirming(ask ? file.path : null)} onConfirm={() => void remove(file)} />
                    </div>
                ))}
            </Surface>
        );
    }

    return (
        <div data-testid="agent-files" data-preview={beside ? 'beside' : 'sheet'}>
            <div className="mb-3 flex items-center gap-2">
                {crumbs}
                <button type="button" disabled={!session} onClick={() => input.current?.click()} className={PILL}>
                    <Upload className="h-3.5 w-3.5" />
                    Upload
                </button>
                <input ref={input} type="file" multiple className="hidden" data-testid="agent-files-upload" onChange={(e) => void upload(e)} />
            </div>
            {beside ? (
                <div className="grid items-start gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,320px)]">
                    {list}
                    <Surface className="p-3">
                        {open ? <OpenFile file={open} source={source} name={name} /> : <p className="py-6 text-center text-[13px] text-muted-foreground">Pick a file to see it here.</p>}
                    </Surface>
                </div>
            ) : (
                <>
                    {list}
                    {open && (
                        <ShellDialog open onOpenChange={(o) => !o && setPicked(null)} title={basename(open.path)} size="md" testId="agent-file-sheet">
                            <div className="pb-4">
                                <OpenFile file={open} source={source} name={name} onDelete={() => remove(open)} />
                            </div>
                        </ShellDialog>
                    )}
                </>
            )}
        </div>
    );
}

/** The file open: itself, where it came from, when and how big, its full path, and Download and Copy path. In a sheet
 *  (`onDelete`), whose title names it, Delete too: a phone has no row to hover. */
function OpenFile({ file, source, name, onDelete }: { file: FileEntry; source: FileSource; name: string; onDelete?: () => Promise<void> }) {
    const path = `${MOUNT}/${file.path}`;
    const parts = useSlot(FILE_PREVIEW);
    const href = fileDownloadHref(file, source, parts);
    const copy = () =>
        navigator.clipboard?.writeText(path).then(
            () => toast('Path copied'),
            () => toast.error('Couldn’t copy the path')
        );
    return (
        <div className="flex min-w-0 flex-col gap-3" data-testid="agent-file">
            <div className="grid max-h-[50vh] min-h-24 place-items-center overflow-auto rounded-xl bg-foreground/[0.03] p-2">
                <FilePreviewBody file={file} source={source} parts={parts} />
            </div>
            <div className="min-w-0 space-y-0.5 text-[12.5px] text-muted-foreground">
                {!onDelete && <p className="truncate text-[14px] font-medium text-foreground">{basename(file.path)}</p>}
                <p className="flex min-w-0">
                    <Origin path={file.path} name={name} />
                </p>
                <p className="tabular-nums">
                    {whenOf(file)} · {fmtBytes(file.size)}
                </p>
                <p className="break-all font-mono text-[11.5px]">{path}</p>
            </div>
            <div className="flex flex-wrap gap-2">
                {href && (
                    <a href={href} download={basename(file.path)} target="_blank" rel="noreferrer" className={PILL}>
                        <Download className="h-3.5 w-3.5" />
                        Download
                    </a>
                )}
                <button type="button" onClick={() => void copy()} className={PILL}>
                    <Copy className="h-3.5 w-3.5" />
                    Copy path
                </button>
                {onDelete && <ConfirmAction label="Delete" confirm="Delete file" quiet onConfirm={onDelete} />}
            </div>
        </div>
    );
}
