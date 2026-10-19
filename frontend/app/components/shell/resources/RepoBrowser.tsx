// A repository, browsable through a reader: the branch you're on, the folder
// you are in, a file in full (highlighted, or rendered when it is markdown; one
// too big to show is named with its size, read from its folder's listing), the
// folder's README under its listing, and beside it all what the repo is, the
// apps that deploy it and its latest commits. A level down, the branch's
// history, page by page, and one commit with each file it changed as a diff.
// Where you are rides the URL: `?ref=` the branch (its default when absent),
// `?path=` the folder (ending in /) or file, `?view=history` the history and
// `?view=commit&sha=` one commit, so Back walks out and anything can be linked.
// A new reader (the repo read again, as when a push moves it) reads it all again.
import { Link, useSearchParams } from 'react-router';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ChevronRight, Ellipsis, File, FileText, Folder, GitBranch, GitCommitHorizontal, History } from 'lucide-react';
import { dateLabel, fmtBytes, relTime } from '~/components/dashboard/primitives';
import { CopyButton } from '~/components/ui/CopyButton';
import { Skeleton } from '~/components/ui/skeleton';
import { useLoaded, type Loaded } from '~/hooks/useLoaded';
import { MAX_SHOWN_BYTES, isBinaryPath, parentDir } from '~/lib/repoText';
import { cn } from '~/lib/utils';
import { useInPhoneShell } from '../AppShell';
import { BUTTON_SECONDARY } from '../buttons';
import { CodeView, MarkdownDoc, languageFor } from './CodeView';
import { DiffView } from './DiffView';
import { basename } from './fileParts';
import { PillSelect, ResourceInnerBack, Surface, Trail, useResourceLink } from './ui';

export interface RepoEntry {
    /** From the repo root: "app/routes/checkout.tsx". */
    path: string;
    dir: boolean;
    size: number | null;
}

export interface RepoCommit {
    sha: string;
    message: string;
    author: string | null;
    /** ISO time. */
    at: string | null;
}

/** A page of a branch's history, newest first; `next` reads the page after it, null on the last. */
export interface RepoHistoryPage {
    commits: RepoCommit[];
    next: string | null;
}

export interface RepoFileChange {
    path: string;
    /** Where a renamed or copied file came from. */
    oldPath: string | null;
    /** added, modified, deleted, renamed, copied or type_changed. */
    status: string;
    additions: number | null;
    deletions: number | null;
    size: number | null;
    /** Its unified diff in git's format; null for a file that isn't shown (not text, or too large). */
    patch: string | null;
}

/** One commit with what it changed against its first parent. */
export interface RepoCommitChanges extends RepoCommit {
    parents: string[];
    additions: number;
    deletions: number;
    files: RepoFileChange[];
}

/** How the browser reads a repo: the hosted platform's repos API, or a test's fake. */
export interface RepoReader {
    /** Its branches' names, the default first. */
    branches(): Promise<string[]>;
    /** A folder's entries at `ref`: `dir` is '' for the root, else ends in '/'. */
    list(dir: string, ref: string): Promise<RepoEntry[]>;
    /** A file's text at `ref`, or null when it isn't text. */
    read(path: string, ref: string): Promise<string | null>;
    /** A page of `ref`'s history from `cursor` (null: its newest commit). */
    history(ref: string, cursor: string | null, limit: number): Promise<RepoHistoryPage>;
    /** The commit `sha` and what it changed. */
    commit(sha: string): Promise<RepoCommitChanges>;
}

/**
 * The first page of a branch's history the page reads: its newest commits beside the files, and where it is the
 * whole history, the count of it. The store keeps no count, so a longer history reads as "100+" until its
 * history is paged to the end.
 */
const FIRST_PAGE = 100;
/** Each further page the history reads. */
const NEXT_PAGE = 100;
/** A file's diff this long (in lines) opens folded, a click away. */
const OPEN_LINES = 400;

function countLabel(count: number, more: boolean): string {
    return `${count.toLocaleString()}${more ? '+' : ''} ${count === 1 && !more ? 'commit' : 'commits'}`;
}

/**
 * A commit message's first line, and the rest with git's hard wrapping undone (a line joined to the one before it
 * unless a blank line, a list item or indented code starts it), so it wraps to the page instead.
 */
function splitMessage(message: string): [string, string] {
    const [title, ...rest] = message.trim().split('\n');
    const body = rest.join('\n').trim().replace(/([^\n])\n(?!\n|[-*•]\s|\d+[.)]\s)(?=\S)/g, '$1 ');
    return [title ?? '', body];
}

const STATUS: Record<string, string> = {
    added: 'Added',
    modified: 'Modified',
    deleted: 'Deleted',
    renamed: 'Renamed',
    copied: 'Copied',
    type_changed: 'Type changed',
};

export interface RepoSummary {
    defaultBranch: string;
    sizeBytes: number | null;
    /** The apps that deploy it. */
    usedBy: { id: string; name: string }[];
    createdAt: string | null;
}

const README = /^readme(\.mdx?)?$/i;

const message = (error: unknown) => (error instanceof Error ? error.message : String(error));

/** Files look alike in a repo, as on GitHub; documents read as text. */
function FileIcon({ name }: { name: string }) {
    const Icon = /\.(mdx?|txt)$/i.test(name) ? FileText : File;
    return <Icon className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />;
}

function Failed({ error, onRetry, inline = false }: { error: unknown; onRetry: () => void; inline?: boolean }) {
    return (
        <p role="alert" className={cn('text-[13.5px] text-muted-foreground', !inline && 'px-4 py-6')}>
            {message(error)}{' '}
            <button type="button" onClick={onRetry} className="font-medium text-foreground underline underline-offset-4">
                Try again
            </button>
        </p>
    );
}

function Rows({ count = 4 }: { count?: number }) {
    return (
        <div aria-busy>
            {Array.from({ length: count }, (_, i) => (
                <div key={i} className="flex items-center gap-2.5 border-b border-border px-4 py-3 last:border-0 dark:border-foreground/[0.06]">
                    <Skeleton className="h-4 w-4 rounded" />
                    <Skeleton className={cn('h-3.5', i % 2 ? 'w-1/4' : 'w-1/3')} />
                </div>
            ))}
        </div>
    );
}

function Monogram({ name }: { name: string }) {
    return (
        <span aria-hidden className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-foreground/[0.09] text-[10px] font-semibold text-foreground/80">
            {name.charAt(0).toUpperCase()}
        </span>
    );
}

function CommitBar({ page, now, onOpen, onHistory }: { page: RepoHistoryPage | undefined; now: string; onOpen: (sha: string) => void; onHistory: () => void }) {
    const commit = page?.commits[0];
    if (!page || !commit) return null;
    return (
        <div className="flex items-center gap-2.5 border-b border-border bg-foreground/[0.015] px-4 py-2 text-[13px] dark:border-foreground/[0.06]">
            {commit.author && <Monogram name={commit.author} />}
            {commit.author && <span className="max-w-[30%] shrink-0 truncate font-medium text-foreground">{commit.author}</span>}
            <button type="button" onClick={() => onOpen(commit.sha)} className="min-w-0 flex-1 truncate text-left text-muted-foreground transition-colors hover:text-foreground hover:underline hover:underline-offset-[3px]">
                {splitMessage(commit.message)[0]}
            </button>
            <span className="hidden shrink-0 font-mono text-[12px] text-muted-foreground sm:inline">{commit.sha.slice(0, 7)}</span>
            {commit.at && <span className="hidden shrink-0 tabular-nums text-muted-foreground sm:inline">{relTime(commit.at, now)}</span>}
            <button
                type="button"
                onClick={onHistory}
                className="-mr-1.5 inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full px-2.5 font-medium text-foreground/85 transition-colors hover:bg-foreground/[0.06] hover:text-foreground"
            >
                <History className="h-3.5 w-3.5 text-muted-foreground" strokeWidth={1.75} />
                <span className="tabular-nums">{countLabel(page.commits.length, page.next !== null)}</span>
            </button>
        </div>
    );
}

function Crumbs({ repoName, path, onGo }: { repoName: string; path: string; onGo: (path: string) => void }) {
    const parts = path.replace(/\/$/, '').split('/');
    return (
        <nav aria-label="Path" className="flex min-w-0 flex-wrap items-center gap-0.5 text-[14px]">
            <button type="button" onClick={() => onGo('')} className="rounded px-1 font-medium text-foreground/80 transition-colors hover:text-foreground hover:underline">
                {repoName}
            </button>
            {parts.map((part, i) => {
                const last = i === parts.length - 1;
                return (
                    <span key={i} className="flex min-w-0 items-center gap-0.5">
                        <span className="text-muted-foreground/60">/</span>
                        {last ? (
                            <span className="truncate px-1 font-semibold text-foreground">{part}</span>
                        ) : (
                            <button type="button" onClick={() => onGo(`${parts.slice(0, i + 1).join('/')}/`)} className="rounded px-1 text-foreground/80 transition-colors hover:text-foreground hover:underline">
                                {part}
                            </button>
                        )}
                    </span>
                );
            })}
        </nav>
    );
}

function Listing({ entries, onOpen }: { entries: RepoEntry[]; onOpen: (path: string) => void }) {
    return (
        <ul aria-label="Files">
            {entries.map((entry) => {
                const name = basename(entry.path);
                return (
                    <li key={entry.path} className="border-b border-border last:border-0 dark:border-foreground/[0.06]">
                        <button
                            type="button"
                            onClick={() => onOpen(entry.dir ? `${entry.path}/` : entry.path)}
                            className="group flex w-full items-center gap-2.5 px-4 py-2.5 text-left transition-colors hover:bg-foreground/[0.025] focus-visible:bg-foreground/[0.04] focus-visible:outline-none"
                        >
                            {entry.dir ? <Folder className="h-4 w-4 shrink-0 fill-sky-500/25 text-sky-600 dark:fill-sky-400/20 dark:text-sky-400" strokeWidth={1.75} /> : <FileIcon name={name} />}
                            <span className="min-w-0 flex-1 truncate text-[14px] text-foreground group-hover:underline group-hover:decoration-foreground/40 group-hover:underline-offset-[3px]">{name}</span>
                            {!entry.dir && entry.size != null && <span className="shrink-0 text-[13px] tabular-nums text-muted-foreground">{fmtBytes(entry.size)}</span>}
                        </button>
                    </li>
                );
            })}
        </ul>
    );
}

function Unshown({ children }: { children: string }) {
    return <p className="px-4 py-10 text-center text-[13.5px] text-muted-foreground">{children}</p>;
}

function FileView({ path, text }: { path: string; text: string | null }) {
    const markdown = /\.mdx?$/i.test(path);
    const [mode, setMode] = useState<'preview' | 'code'>(markdown ? 'preview' : 'code');
    if (text === null) return <Unshown>A binary file, not shown. Clone the repo to open it.</Unshown>;
    const lines = text.replace(/\n$/, '').split('\n').length;
    const bytes = new Blob([text]).size;
    return (
        <div>
            <div className="flex items-center gap-3 border-b border-border px-3 py-2 dark:border-foreground/[0.06]">
                {markdown && (
                    <div className="flex rounded-lg bg-foreground/[0.05] p-0.5" role="tablist" aria-label="View">
                        {(['preview', 'code'] as const).map((m) => (
                            <button
                                key={m}
                                type="button"
                                role="tab"
                                aria-selected={mode === m}
                                onClick={() => setMode(m)}
                                className={cn(
                                    'h-7 rounded-md px-2.5 text-[12.5px] font-medium capitalize transition-colors',
                                    mode === m ? 'bg-background text-foreground shadow-sm dark:bg-foreground/[0.1]' : 'text-muted-foreground hover:text-foreground'
                                )}
                            >
                                {m}
                            </button>
                        ))}
                    </div>
                )}
                <span className="px-1 text-[12.5px] tabular-nums text-muted-foreground">
                    {lines} {lines === 1 ? 'line' : 'lines'} · {fmtBytes(bytes)}
                </span>
                <span className="ml-auto" title="Copy file">
                    <CopyButton value={text} />
                </span>
            </div>
            {mode === 'preview' ? <MarkdownDoc source={text} className="px-6 py-5 sm:px-8" /> : <CodeView code={text} language={languageFor(path)} />}
        </div>
    );
}

/** The folder's README, under its listing. */
function Readme({ reader, repo, path, refName, onOpen }: { reader: RepoReader; repo: string; path: string; refName: string; onOpen: () => void }) {
    const file = useLoaded(`${repo}:file:${refName}:${path}`, () => reader.read(path, refName));
    useRereadOn(reader, [file]);
    if (typeof file.data !== 'string') return null;
    return (
        <Surface>
            <button
                type="button"
                onClick={onOpen}
                className="flex w-full items-center gap-2 border-b border-border px-4 py-2.5 text-left text-[13px] font-medium text-foreground/85 transition-colors hover:text-foreground dark:border-foreground/[0.06]"
            >
                <FileIcon name={path} />
                {basename(path)}
                <ChevronRight className="ml-auto h-4 w-4 text-muted-foreground" />
            </button>
            <MarkdownDoc source={file.data} className="px-6 py-6 sm:px-8" />
        </Surface>
    );
}

function BranchPicker({ branches, value, onChange }: { branches: string[]; value: string; onChange: (branch: string) => void }) {
    const options = (branches.includes(value) ? branches : [value, ...branches]).map((b) => ({ value: b, label: b }));
    return <PillSelect label="Branch" icon={GitBranch} value={value} options={options} onChange={onChange} />;
}

function Aside({
    name,
    summary,
    commits,
    now,
    onOpen,
    onHistory,
}: {
    name: string;
    summary: RepoSummary;
    commits: Loaded<RepoHistoryPage>;
    now: string;
    onOpen: (sha: string) => void;
    onHistory: () => void;
}) {
    // An app that deploys it opens on its own page, as a step Back undoes.
    const resourceLink = useResourceLink();
    return (
        <aside className="space-y-8 lg:pt-1">
            <section>
                <h3 className="text-[14px] font-semibold text-foreground">About</h3>
                <dl className="mt-2 space-y-1.5 text-[13.5px]">
                    {(
                        [
                            ['Default branch', summary.defaultBranch],
                            ['Size', summary.sizeBytes != null ? fmtBytes(summary.sizeBytes) : null],
                            ['Created', summary.createdAt ? dateLabel(summary.createdAt) : null],
                        ] as const
                    ).map(([label, value]) =>
                        value ? (
                            <div key={label} className="flex gap-2">
                                <dt className="w-28 shrink-0 text-muted-foreground">{label}</dt>
                                <dd className="min-w-0 truncate text-foreground/85">{value}</dd>
                            </div>
                        ) : null
                    )}
                </dl>
                <p className="mt-3 flex items-center gap-1 text-[12.5px] text-muted-foreground">
                    <span className="truncate font-mono">{name}</span>
                    <CopyButton value={name} className="-my-1 [&_svg]:h-3.5 [&_svg]:w-3.5" />
                </p>
            </section>
            <section>
                <h3 className="text-[14px] font-semibold text-foreground">Deployed by</h3>
                {summary.usedBy.length ? (
                    <ul className="mt-3 space-y-2.5">
                        {summary.usedBy.map((app) => (
                            <li key={app.id}>
                                <Link to={{ search: resourceLink('apps', app.id) }} className="flex items-center gap-2.5 text-[13.5px] text-foreground/85 hover:text-foreground hover:underline">
                                    <Monogram name={app.name} />
                                    {app.name}
                                </Link>
                            </li>
                        ))}
                    </ul>
                ) : (
                    <p className="mt-2 text-[13.5px] text-muted-foreground">No app deploys it yet.</p>
                )}
            </section>
            <section>
                <h3 className="text-[14px] font-semibold text-foreground">Recent commits</h3>
                {commits.error !== undefined ? (
                    <div className="mt-2">
                        <Failed error={commits.error} onRetry={commits.reload} inline />
                    </div>
                ) : commits.data?.commits.length ? (
                    <>
                        <ol className="mt-3 space-y-3">
                            {commits.data.commits.slice(0, 4).map((c) => (
                                <li key={c.sha}>
                                    <button type="button" onClick={() => onOpen(c.sha)} className="group flex w-full gap-2.5 text-left">
                                        <GitCommitHorizontal className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
                                        <span className="min-w-0">
                                            <span className="block text-[13px] leading-snug text-foreground/85 group-hover:text-foreground group-hover:underline group-hover:underline-offset-[3px]">
                                                {splitMessage(c.message)[0]}
                                            </span>
                                            <span className="mt-0.5 block text-[12px] text-muted-foreground">{[c.author, c.at ? relTime(c.at, now) : null].filter(Boolean).join(' · ')}</span>
                                        </span>
                                    </button>
                                </li>
                            ))}
                        </ol>
                        <button type="button" onClick={onHistory} className="mt-3 inline-flex items-center gap-1 text-[13px] font-medium text-foreground/85 underline-offset-[3px] hover:text-foreground hover:underline">
                            All commits
                            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                        </button>
                    </>
                ) : (
                    <p className="mt-2 text-[13.5px] text-muted-foreground">{commits.data ? 'Nothing committed yet.' : '…'}</p>
                )}
            </section>
        </aside>
    );
}

/** Where you are a level down: each step but the last goes back to it. */
/** The day a commit was made, heading that day's commits. */
function dayOf(iso: string | null): string {
    return iso ? new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : 'Undated';
}

function ShortSha({ sha, onOpen }: { sha: string; onOpen?: () => void }) {
    const short = sha.slice(0, 7);
    return (
        <span className="flex shrink-0 items-center">
            {onOpen ? (
                <button type="button" onClick={onOpen} aria-label={`Open commit ${short}`} className="rounded-md px-1.5 py-0.5 font-mono text-[12.5px] text-foreground/75 transition-colors hover:bg-foreground/[0.06] hover:text-foreground">
                    {short}
                </button>
            ) : (
                <span className="px-1.5 font-mono text-[12.5px] text-foreground/75">{short}</span>
            )}
            <CopyButton value={sha} className="[&_svg]:h-3.5 [&_svg]:w-3.5" />
        </span>
    );
}

function HistoryRow({ commit, now, onOpen }: { commit: RepoCommit; now: string; onOpen: (sha: string) => void }) {
    const [title, body] = splitMessage(commit.message);
    const [open, setOpen] = useState(false);
    return (
        <li className="border-b border-border last:border-0 dark:border-foreground/[0.06]">
            <div className="flex items-start gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-start gap-1.5">
                        <button
                            type="button"
                            onClick={() => onOpen(commit.sha)}
                            className="line-clamp-2 min-w-0 text-left text-[14px] font-medium text-foreground underline-offset-[3px] [overflow-wrap:anywhere] hover:underline sm:line-clamp-1"
                        >
                            {title}
                        </button>
                        {body && (
                            <button
                                type="button"
                                aria-expanded={open}
                                aria-label={open ? 'Hide the full message' : 'Show the full message'}
                                onClick={() => setOpen((o) => !o)}
                                className={cn(
                                    'grid h-5 w-6 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/[0.1] hover:text-foreground',
                                    open ? 'bg-foreground/[0.1] text-foreground' : 'bg-foreground/[0.06]'
                                )}
                            >
                                <Ellipsis className="h-3.5 w-3.5" />
                            </button>
                        )}
                    </div>
                    <p className="mt-1 flex min-w-0 items-center gap-1.5 text-[12.5px] text-muted-foreground">
                        {commit.author && <Monogram name={commit.author} />}
                        {commit.author && <span className="truncate font-medium text-foreground/80">{commit.author}</span>}
                        {commit.at && (
                            <span className="shrink-0" title={dateLabel(commit.at)}>
                                {commit.author ? '· ' : ''}
                                {relTime(commit.at, now)}
                            </span>
                        )}
                    </p>
                    {open && <p className="mt-2.5 max-w-[72ch] whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/75">{body}</p>}
                </div>
                <ShortSha sha={commit.sha} onOpen={() => onOpen(commit.sha)} />
            </div>
        </li>
    );
}

/** A branch's history, newest first, a day at a time, read a page further on asking. */
function HistoryView({
    reader,
    refName,
    first,
    picker,
    now,
    onOpen,
}: {
    reader: RepoReader;
    refName: string;
    first: Loaded<RepoHistoryPage>;
    picker: ReactNode;
    now: string;
    onOpen: (sha: string) => void;
}) {
    const [more, setMore] = useState<RepoHistoryPage | null>(null);
    const [reading, setReading] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    // A first page read again (a push moved the branch) starts the history from its head again.
    useEffect(() => {
        setMore(null);
        setError(undefined);
    }, [first.data]);
    const commits = useMemo(() => [...(first.data?.commits ?? []), ...(more?.commits ?? [])], [first.data, more]);
    const next = more ? more.next : (first.data?.next ?? null);
    const days = useMemo(() => {
        const byDay = new Map<string, RepoCommit[]>();
        for (const c of commits) byDay.set(dayOf(c.at), [...(byDay.get(dayOf(c.at)) ?? []), c]);
        return [...byDay];
    }, [commits]);

    const readMore = async () => {
        if (!next || reading) return;
        setReading(true);
        setError(undefined);
        try {
            const page = await reader.history(refName, next, NEXT_PAGE);
            setMore((m) => ({ commits: [...(m?.commits ?? []), ...page.commits], next: page.next }));
        } catch (e) {
            setError(e);
        } finally {
            setReading(false);
        }
    };

    return (
        <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                {picker}
                {first.data && commits.length > 0 && <span className="text-[13px] tabular-nums text-muted-foreground">{countLabel(commits.length, next !== null)}</span>}
            </div>
            {first.error !== undefined ? (
                <Surface>
                    <Failed error={first.error} onRetry={first.reload} />
                </Surface>
            ) : !first.data ? (
                <Surface>
                    <Rows count={6} />
                </Surface>
            ) : !commits.length ? (
                <Surface>
                    <Unshown>Nothing committed yet. The first commit shows up here.</Unshown>
                </Surface>
            ) : (
                days.map(([day, list]) => (
                    <section key={day} aria-label={`Commits on ${day}`}>
                        <h3 className="mb-2.5 flex items-center gap-2 text-[13px] font-medium text-muted-foreground">
                            <GitCommitHorizontal className="h-4 w-4" strokeWidth={1.75} />
                            Commits on {day}
                        </h3>
                        <Surface>
                            <ol>
                                {list.map((c) => (
                                    <HistoryRow key={c.sha} commit={c} now={now} onOpen={onOpen} />
                                ))}
                            </ol>
                        </Surface>
                    </section>
                ))
            )}
            {error !== undefined && <Failed error={error} onRetry={readMore} inline />}
            {next && first.data && (
                <div className="flex justify-center">
                    <button type="button" onClick={readMore} disabled={reading} className={BUTTON_SECONDARY}>
                        {reading ? 'Reading…' : 'Older commits'}
                    </button>
                </div>
            )}
        </div>
    );
}

function LineCounts({ additions, deletions }: { additions: number; deletions: number }) {
    return (
        <span className="flex shrink-0 items-baseline gap-2 tabular-nums">
            <span className="text-emerald-600 dark:text-emerald-400">+{additions.toLocaleString()}</span>
            <span className="text-red-600 dark:text-red-400">−{deletions.toLocaleString()}</span>
        </span>
    );
}

function FileChangeCard({ file }: { file: RepoFileChange }) {
    const lines = file.patch ? file.patch.split('\n').length : 0;
    const [open, setOpen] = useState(lines <= OPEN_LINES);
    const moved = file.oldPath && file.oldPath !== file.path ? file.oldPath : null;
    return (
        <Surface>
            <button
                type="button"
                aria-expanded={open}
                onClick={() => setOpen((o) => !o)}
                className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left transition-colors hover:bg-foreground/[0.025] focus-visible:bg-foreground/[0.04] focus-visible:outline-none"
            >
                <ChevronRight className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150', open && 'rotate-90')} />
                <span className="min-w-0 flex-1 truncate text-[13.5px] text-foreground">
                    {moved && <span className="text-muted-foreground">{moved} → </span>}
                    {file.path}
                </span>
                <span className="hidden shrink-0 text-[12.5px] text-muted-foreground sm:inline">{STATUS[file.status] ?? file.status}</span>
                {file.additions != null && file.deletions != null && (
                    <span className="text-[12.5px]">
                        <LineCounts additions={file.additions} deletions={file.deletions} />
                    </span>
                )}
            </button>
            {open && (
                <div className="border-t border-border dark:border-foreground/[0.06]">
                    {file.patch !== null ? (
                        <DiffView patch={file.patch} path={file.path} />
                    ) : (
                        <Unshown>
                            {isBinaryPath(file.path)
                                ? `A binary file${file.size ? ` (${fmtBytes(file.size)})` : ''}, not shown.`
                                : `Too large to show here${file.size ? ` (${fmtBytes(file.size)})` : ''}. Clone the repo to read it.`}
                        </Unshown>
                    )}
                </div>
            )}
        </Surface>
    );
}

/** One commit: its message, who made it and when, its parents, and each file it changed with its diff. */
function CommitView({ reader, name, sha, now, onOpen }: { reader: RepoReader; name: string; sha: string; now: string; onOpen: (sha: string) => void }) {
    const changes = useLoaded(`${name}:commit:${sha}`, () => reader.commit(sha));
    useRereadOn(reader, [changes]);
    if (changes.error !== undefined)
        return (
            <Surface>
                <Failed error={changes.error} onRetry={changes.reload} />
            </Surface>
        );
    const commit = changes.data;
    if (!commit)
        return (
            <Surface>
                <Rows count={6} />
            </Surface>
        );
    const [title, body] = splitMessage(commit.message);
    return (
        <article>
            <header>
                <h2 className="text-[20px] font-semibold leading-snug tracking-[-0.015em] text-foreground [overflow-wrap:anywhere]">{title}</h2>
                {body && <p className="mt-2 max-w-[72ch] whitespace-pre-wrap text-[14px] leading-relaxed text-foreground/75">{body}</p>}
                <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-muted-foreground">
                    <span className="flex min-w-0 items-center gap-2">
                        {commit.author && <Monogram name={commit.author} />}
                        {commit.author && <span className="truncate font-medium text-foreground/85">{commit.author}</span>}
                        {commit.at && <span title={dateLabel(commit.at)}>{relTime(commit.at, now)}</span>}
                    </span>
                    <span className="flex items-center gap-1">
                        {commit.parents.length ? (
                            <>
                                {commit.parents.length === 1 ? 'Parent' : 'Parents'}
                                {commit.parents.map((p) => (
                                    <ShortSha key={p} sha={p} onOpen={() => onOpen(p)} />
                                ))}
                            </>
                        ) : (
                            'The first commit'
                        )}
                    </span>
                    <span className="flex items-center gap-1">
                        Commit
                        <ShortSha sha={commit.sha} />
                    </span>
                </div>
            </header>
            <div className="mb-3 mt-8 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[13.5px]">
                <span className="font-medium text-foreground">
                    {commit.files.length.toLocaleString()} {commit.files.length === 1 ? 'file' : 'files'} changed
                </span>
                <LineCounts additions={commit.additions} deletions={commit.deletions} />
            </div>
            {commit.files.length ? (
                <div className="space-y-3">
                    {commit.files.map((f) => (
                        <FileChangeCard key={`${f.oldPath ?? ''}:${f.path}`} file={f} />
                    ))}
                </div>
            ) : (
                <Surface>
                    <Unshown>This commit changed no files.</Unshown>
                </Surface>
            )}
        </article>
    );
}

/** Reads again, in place, when the reader is a new one: the repo was read again, as when a push moved it. */
function useRereadOn(reader: RepoReader, reads: Loaded<unknown>[]) {
    const first = useRef(reader);
    useEffect(() => {
        if (reader !== first.current) for (const read of reads) read.reload();
    }, [reader]); // eslint-disable-line react-hooks/exhaustive-deps
}

export function RepoBrowser({ reader, name, summary, now }: { reader: RepoReader; name: string; summary: RepoSummary; now: string }) {
    const [params, setParams] = useSearchParams();
    const refName = params.get('ref') || summary.defaultBranch;
    const path = (params.get('path') ?? '').replace(/^\/+/, '');
    // A folder ends in '/'; anything else names a file, read once its folder's listing says it isn't too big.
    const dir = path === '' || path.endsWith('/') ? path : null;
    const folder = dir ?? parentDir(path);

    const view = params.get('view');
    const sha = params.get('sha');
    const inCode = view !== 'history' && !(view === 'commit' && sha);
    const inPhone = useInPhoneShell();

    const branches = useLoaded(`${name}:branches`, () => reader.branches());
    const commits = useLoaded(`${name}:history:${refName}`, () => reader.history(refName, null, FIRST_PAGE));
    const listing = useLoaded(inCode ? `${name}:list:${refName}:${folder}` : null, () => reader.list(folder, refName));
    const size = dir === null ? (listing.data?.find((e) => e.path === path)?.size ?? null) : null;
    const tooBig = size !== null && size > MAX_SHOWN_BYTES ? size : null;
    const file = useLoaded(inCode && dir === null && listing.data && tooBig === null ? `${name}:file:${refName}:${path}` : null, () => reader.read(path, refName));
    useRereadOn(reader, [branches, commits, listing, file]);

    const set = (changes: Record<string, string | null>) =>
        setParams((prev) => {
            const next = new URLSearchParams(prev);
            for (const [key, value] of Object.entries(changes)) {
                if (value) next.set(key, value);
                else next.delete(key);
            }
            return next;
        });
    const go = (to: string) => set({ path: to || null });
    const openCommit = (to: string) => set({ view: 'commit', sha: to, path: null });
    const openHistory = () => set({ view: 'history', sha: null, path: null });
    const toCode = () => set({ view: null, sha: null });
    const shortName = name.split('/').pop() ?? name;
    const picker = (
        <BranchPicker branches={branches.data ?? [summary.defaultBranch]} value={refName} onChange={(b) => set({ ref: b === summary.defaultBranch ? null : b, path: null })} />
    );

    if (view === 'commit' && sha) {
        return (
            <div className="mt-8 space-y-6">
                <ResourceInnerBack label="History" onBack={openHistory} />
                {!inPhone && (
                    <Trail
                        steps={[
                            { label: shortName, onGo: toCode },
                            { label: 'History', onGo: openHistory },
                            { label: sha.slice(0, 7), mono: true },
                        ]}
                    />
                )}
                <CommitView reader={reader} name={name} sha={sha} now={now} onOpen={openCommit} />
            </div>
        );
    }
    if (view === 'history') {
        return (
            <div className="mt-8 space-y-4">
                <ResourceInnerBack label={shortName} onBack={toCode} />
                {!inPhone && <Trail steps={[{ label: shortName, onGo: toCode }, { label: 'History' }]} />}
                <HistoryView key={refName} reader={reader} refName={refName} first={commits} picker={picker} now={now} onOpen={openCommit} />
            </div>
        );
    }

    const entries =
        dir !== null && listing.data ? [...listing.data].sort((a, b) => (a.dir === b.dir ? a.path.localeCompare(b.path, undefined, { sensitivity: 'base' }) : a.dir ? -1 : 1)) : undefined;
    const readme = entries?.find((e) => !e.dir && README.test(basename(e.path)) && (e.size ?? 0) <= MAX_SHOWN_BYTES);

    return (
        <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,1fr)_260px]">
            <div className="min-w-0 space-y-4">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    {picker}
                    {branches.error !== undefined ? (
                        <Failed error={branches.error} onRetry={branches.reload} inline />
                    ) : (
                        branches.data && (
                            <span className="text-[13px] tabular-nums text-muted-foreground">
                                {branches.data.length} {branches.data.length === 1 ? 'branch' : 'branches'}
                            </span>
                        )
                    )}
                    {path && (
                        <div className="w-full">
                            <Crumbs repoName={shortName} path={path} onGo={go} />
                        </div>
                    )}
                </div>
                <Surface>
                    <CommitBar page={commits.data} now={now} onOpen={openCommit} onHistory={openHistory} />
                    {listing.error !== undefined ? (
                        <Failed error={listing.error} onRetry={listing.reload} />
                    ) : !listing.data ? (
                        <Rows count={dir === null ? 6 : 4} />
                    ) : entries ? (
                        entries.length ? (
                            <Listing entries={entries} onOpen={go} />
                        ) : (
                            <Unshown>{dir ? 'This folder is empty.' : 'Nothing committed yet. The first commit shows up here.'}</Unshown>
                        )
                    ) : tooBig !== null ? (
                        <Unshown>{`Too big to show here (${fmtBytes(tooBig)}). Clone the repo to open it.`}</Unshown>
                    ) : file.error !== undefined ? (
                        <Failed error={file.error} onRetry={file.reload} />
                    ) : file.data === undefined ? (
                        <Rows count={6} />
                    ) : (
                        <FileView key={path} path={path} text={file.data} />
                    )}
                </Surface>
                {readme && <Readme reader={reader} repo={name} path={readme.path} refName={refName} onOpen={() => go(readme.path)} />}
            </div>
            <Aside name={name} summary={summary} commits={commits} now={now} onOpen={openCommit} onHistory={openHistory} />
        </div>
    );
}
