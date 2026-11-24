// A repo's files in the Code repos drawer, on the branch the drawer is on: a tree that loads each directory when it
// opens, and a read-only viewer for the file picked (`?file=`). Binary files are named, never dumped, and a file too
// big to show is named with its size, which its directory's listing gives (read again only for a linked file).
import { useState } from 'react';
import { ChevronRight, File, Folder, FolderOpen, Link2 } from 'lucide-react';
import { fmtBytes, HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import type { Repo, RepoFile } from 'noclick';
import { MAX_SHOWN_BYTES, decodeText, isBinaryPath, parentDir, refFor } from '@/lib/repoText';
import { useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { CopyButton } from '../../ui/CopyButton';
import { ErrorPanel } from '../../ui/ErrorPanel';

const baseName = (path: string) => path.slice(path.lastIndexOf('/') + 1);

/** A directory's listing on a branch (none while `prefix` is null), one read however many views show it. */
function useListing(repo: Repo, branch: string, prefix: string | null) {
    return useV1(prefix === null ? null : `repos/${repo.id}/files?${branch}:${prefix}`, () => repo.files(prefix!, { ref: refFor(branch, repo.defaultBranch) }));
}

type TreeProps = { repo: Repo; branch: string; open: Set<string>; onToggle: (path: string) => void; selected: string | null; onSelect: (entry: RepoFile) => void };

function Directory({ prefix, depth, ...tree }: TreeProps & { prefix: string; depth: number }) {
    const { repo, branch, open, onToggle, selected, onSelect } = tree;
    const listing = useListing(repo, branch, prefix);
    const indent = { paddingLeft: `${0.5 + depth * 0.875}rem` };
    if (listing.error !== undefined) {
        return (
            <li className="px-2 py-1.5" style={indent}>
                <ErrorPanel error={listing.error} onRetry={() => void listing.refresh()} className="p-3" />
            </li>
        );
    }
    if (!listing.data) {
        return (
            <li aria-busy className="px-2 py-1.5" style={indent}>
                <span className="block h-3 w-2/3 animate-pulse rounded bg-foreground/[0.07]" />
            </li>
        );
    }
    if (!listing.data.length && depth === 0) return <li className="px-3 py-3 text-[13px] text-muted-foreground">Nothing on {branch} yet. Commit a file to start it.</li>;
    return (
        <>
            {listing.data.map((entry) => {
                const isDir = entry.type === 'dir';
                const expanded = isDir && open.has(entry.path);
                // A link someone committed is one entry, never a folder to open: picked, it reads as the path it points to.
                const Icon = isDir ? (expanded ? FolderOpen : Folder) : entry.type === 'link' ? Link2 : File;
                return (
                    <li key={entry.path}>
                        <button
                            type="button"
                            aria-expanded={isDir ? expanded : undefined}
                            aria-current={selected === entry.path ? 'true' : undefined}
                            onClick={() => (isDir ? onToggle(entry.path) : onSelect(entry))}
                            style={indent}
                            className={cn(
                                'flex w-full items-center gap-1.5 py-1 pr-2 text-left font-mono text-[12px] transition-colors hover:bg-foreground/[0.04]',
                                selected === entry.path ? 'bg-foreground/[0.06] text-foreground' : 'text-foreground/85'
                            )}
                        >
                            <ChevronRight aria-hidden className={cn('h-3 w-3 shrink-0 text-muted-foreground transition-transform', expanded && 'rotate-90', !isDir && 'invisible')} />
                            <Icon aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            <span className="truncate">{baseName(entry.path)}</span>
                            {entry.type === 'link' && <span className="ml-auto shrink-0 font-sans text-[11px] text-muted-foreground">link</span>}
                        </button>
                        {expanded && (
                            <ul className="m-0 list-none p-0">
                                <Directory {...tree} prefix={`${entry.path}/`} depth={depth + 1} />
                            </ul>
                        )}
                    </li>
                );
            })}
        </>
    );
}

function Note({ children }: { children: string }) {
    return <p className="m-0 px-3 py-6 text-center text-[13px] text-muted-foreground">{children}</p>;
}

function Viewer({ repo, branch, path, picked }: { repo: Repo; branch: string; path: string; picked: number | null }) {
    // A file linked to (not picked from the tree) takes its size from its directory's listing.
    const listing = useListing(repo, branch, picked === null ? parentDir(path) : null);
    const size = picked ?? listing.data?.find((e) => e.path === path)?.size ?? null;
    const sized = picked !== null || listing.data !== undefined;
    const tooBig = size !== null && size > MAX_SHOWN_BYTES ? size : null;
    const binaryByName = isBinaryPath(path);
    const file = useV1(sized && tooBig === null && !binaryByName ? `repos/${repo.id}/file?${branch}:${path}` : null, async () =>
        decodeText(await repo.read(path, { ref: refFor(branch, repo.defaultBranch) }))
    );
    const failed = listing.error ?? file.error;
    return (
        <section aria-label={path} className={cn('flex min-w-0 flex-col rounded-lg border', HAIRLINE)}>
            <header className={cn('flex h-9 items-center gap-2 border-b px-3', HAIRLINE)}>
                <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-foreground">{path}</span>
                {size != null && <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">{fmtBytes(size)}</span>}
                <CopyButton value={path} label="Copy the path" />
            </header>
            {failed !== undefined ? (
                <ErrorPanel error={failed} onRetry={() => void (listing.error !== undefined ? listing.refresh() : file.refresh())} className="m-3" />
            ) : binaryByName || file.data === null ? (
                <Note>A binary file, not shown. Clone the repo to open it.</Note>
            ) : tooBig !== null ? (
                <Note>{`Too big to show here (${fmtBytes(tooBig)}). Clone the repo to open it.`}</Note>
            ) : file.data === undefined ? (
                <div aria-busy className="m-3 h-40 animate-pulse rounded bg-foreground/[0.04]" />
            ) : (
                <pre className="m-0 max-h-[28rem] overflow-auto px-3 py-2 font-mono text-[12px] leading-5 text-foreground">{file.data || '(empty file)'}</pre>
            )}
        </section>
    );
}

export function RepoFiles({ repo, branch }: { repo: Repo; branch: string }) {
    const [open, setOpen] = useState<Set<string>>(() => new Set());
    const [file, setFile] = useSearchParam('file');
    const [picked, setPicked] = useState<{ path: string; size: number | null } | null>(null);
    const toggle = (path: string) =>
        setOpen((prev) => {
            const next = new Set(prev);
            if (next.has(path)) next.delete(path);
            else next.add(path);
            return next;
        });
    return (
        <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
            <nav aria-label="Files" className={cn('max-h-[28rem] min-w-0 overflow-auto rounded-lg border py-1', HAIRLINE)}>
                <ul className="m-0 list-none p-0">
                    <Directory
                        repo={repo}
                        branch={branch}
                        prefix=""
                        depth={0}
                        open={open}
                        onToggle={toggle}
                        selected={file}
                        onSelect={(entry) => {
                            setPicked({ path: entry.path, size: entry.size });
                            setFile(entry.path);
                        }}
                    />
                </ul>
            </nav>
            {file ? (
                <Viewer key={`${branch}:${file}`} repo={repo} branch={branch} path={file} picked={picked?.path === file ? picked.size : null} />
            ) : (
                <p className={cn('m-0 flex min-h-[8rem] items-center justify-center rounded-lg border border-dashed px-4 text-center text-[13px] text-muted-foreground', HAIRLINE)}>
                    Pick a file to read it. The tree shows {branch}.
                </p>
            )}
        </div>
    );
}
