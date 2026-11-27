// Code repos: Git repositories your code and agents commit to. The table shows each repo's
// last commit and the apps that deploy it, and New repo shows the code that makes one; the drawer
// (`?repo=`, its tab in `?tab=`, the branch it reads in `?branch=`) browses files, commits
// and branches, with Clone, Export to GitHub and Delete.
import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { GitBranch, Upload } from 'lucide-react';
import { toast } from 'sonner';
import { fmtBytes, HAIRLINE } from '@/ui/primitives';
import { authorName, refFor } from '@/lib/repoText';
import { cn } from '@/ui/utils';
import { FieldSelect } from '@/ui/FieldSelect';
import { NeedsConnection, Repo, type Commit } from 'noclick';
import { NEW_SNIPPETS } from '@/screens/console/lib/snippets';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole, useConsoleHref } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { connectionLook, useScopeConnections } from '../../connections';
import { NewInCode } from '../../NewInCode';
import { ConsoleButton, consoleButtonClass } from '../../ui/Button';
import { ConsoleDialog } from '../../ui/ConsoleDialog';
import { CopyButton } from '../../ui/CopyButton';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { PillSwitch } from '../../ui/PillTabs';
import { Segmented } from '../../ui/Segmented';
import { SwitchRow } from '../../ui/SwitchRow';
import { TimeCell } from '../../ui/TimeCell';
import { withParams } from './AppsFormat';
import { BranchName, Tag } from './AppsParts';
import { RepoFiles } from './ReposFiles';
import { ConfirmAction, Field, INPUT, LabeledInput, PanelToolbar, Section, type PanelProps } from './shared';

const TABS = [
    { id: 'files', label: 'Files' },
    { id: 'commits', label: 'Commits' },
    { id: 'branches', label: 'Branches' },
] as const;

type TabId = (typeof TABS)[number]['id'];

/** How long a clone URL minted here works. */
const CLONE_TTL_S = 3600;
/** GitHub's rules for an account login and a repository name, as the export checks them. */
const GITHUB_OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/;
const GITHUB_NAME = /^[A-Za-z0-9._-]{1,100}$/;

/** Who made a commit, and how many files it touched where the API says (a listed commit's count isn't kept). */
function commitLine(c: Pick<Commit, 'author' | 'filesChanged'>) {
    const files = c.filesChanged === null ? null : `${c.filesChanged} ${c.filesChanged === 1 ? 'file' : 'files'}`;
    return [c.author ? authorName(c.author) : 'Unknown', files].filter(Boolean).join(' · ');
}

function UsedBy({ repo }: { repo: Repo }) {
    const href = useConsoleHref();
    if (!repo.usedBy.length) return <span className="text-muted-foreground">No app</span>;
    return (
        <span className="inline-flex min-w-0 flex-wrap gap-x-2">
            {repo.usedBy.map((u) => (
                <Link key={u.id} to={href('resources/apps', { app: u.id })} onClick={(e) => e.stopPropagation()} className="truncate text-foreground hover:underline">
                    {u.name}
                </Link>
            ))}
        </span>
    );
}

function CommitList({ commits, label }: { commits: readonly Commit[]; label: string }) {
    return (
        <ul aria-label={label} className={'m-0 list-none p-0'}>
            {commits.map((c) => (
                <li key={c.sha} className="flex items-start gap-3 py-2.5">
                    <span className="group/sha inline-flex shrink-0 items-center gap-0.5 pt-px font-mono text-[12px] text-foreground/80">
                        {c.sha.slice(0, 7)}
                        <CopyButton value={c.sha} label="Copy the sha" className="opacity-100 md:opacity-0 md:group-hover/sha:opacity-100" />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="text-[13px] text-foreground">{c.message}</span>
                        <span className="text-[12px] text-muted-foreground">
                            {commitLine(c)} · <TimeCell value={c.createdAt} />
                        </span>
                    </span>
                </li>
            ))}
        </ul>
    );
}

function RepoCommits({ repo, branch }: { repo: Repo; branch: string }) {
    const commits = useV1(`repos/${repo.id}/commits?${branch}`, () => repo.commits({ branch: refFor(branch, repo.defaultBranch), limit: 30 }));
    return (
        <Section title="Recent commits">
            {commits.error !== undefined ? (
                <ErrorPanel error={commits.error} onRetry={() => void commits.refresh()} />
            ) : commits.loading ? (
                <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : commits.data?.length ? (
                <CommitList commits={commits.data} label="Commits" />
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">No commits on {branch} yet.</p>
            )}
        </Section>
    );
}

/** The repo's branches, one read for the drawer's switch and its Branches tab. */
function useBranches(repo: Repo) {
    return useV1(`repos/${repo.id}/branches`, () => repo.branches());
}

function RepoBranches({ repo }: { repo: Repo }) {
    const branches = useBranches(repo);
    return (
        <Section title="Branches">
            {branches.error !== undefined ? (
                <ErrorPanel error={branches.error} onRetry={() => void branches.refresh()} />
            ) : branches.loading ? (
                <div aria-busy className="h-24 animate-pulse rounded-lg bg-foreground/[0.04]" />
            ) : branches.data?.length ? (
                <ul aria-label="Branches" className={'m-0 list-none p-0'}>
                    {branches.data.map((b) => (
                        <li key={b.name} className="flex items-center gap-3 py-2.5">
                            <span className="flex min-w-0 flex-1 items-center gap-2">
                                <BranchName name={b.name} />
                                {b.name === repo.defaultBranch && <Tag>Default</Tag>}
                            </span>
                            <span className="shrink-0 font-mono text-[12px] text-muted-foreground">{b.head?.slice(0, 7)}</span>
                            <TimeCell value={b.updatedAt} className="w-20 shrink-0 text-right text-[12px] text-muted-foreground" />
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">No branches yet: the first commit makes {repo.defaultBranch}.</p>
            )}
        </Section>
    );
}

function CloneDialog({ repo, open, onOpenChange }: { repo: Repo; open: boolean; onOpenChange: (open: boolean) => void }) {
    const [write, setWrite] = useState(false);
    const [url, setUrl] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    useEffect(() => {
        if (open) return;
        setUrl(null);
        setWrite(false);
        setError(undefined);
    }, [open]);
    const mint = async () => {
        setBusy(true);
        setError(undefined);
        try {
            setUrl(await repo.cloneUrl({ write, ttlS: CLONE_TTL_S }));
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    const command = url ? `git clone ${url} ${repo.name}` : '';
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            mark={<GitBranch aria-hidden className="h-5 w-5" />}
            title={`Clone ${repo.name}`}
            description="Plain git over HTTPS. The URL carries a token that stops working after an hour, so keep it to yourself until then."
            footer={
                url ? (
                    <ConsoleButton variant="primary" onClick={() => onOpenChange(false)}>
                        Done
                    </ConsoleButton>
                ) : (
                    <ConsoleButton variant="primary" disabled={busy} onClick={() => void mint()}>
                        {busy ? 'Creating…' : 'Create clone URL'}
                    </ConsoleButton>
                )
            }
        >
            <div className="flex flex-col gap-3">
                <SwitchRow label="Allow push" description="Anyone with the URL can push, not only read." checked={write} disabled={!!url} onCheckedChange={setWrite} />
                {url && (
                    <div className="flex flex-col gap-1.5">
                        <div className={cn('flex items-start gap-2 rounded-lg border bg-foreground/[0.03] px-3 py-2', HAIRLINE)}>
                            <code aria-label="Clone command" className="min-w-0 flex-1 break-all font-mono text-[12px] text-foreground">
                                {command}
                            </code>
                            <CopyButton value={command} label="Copy the command" />
                        </div>
                        <p className="m-0 text-[12px] text-muted-foreground">{write ? 'Anyone with it can read and push' : 'Anyone with it can read the repo'} for the next hour.</p>
                    </div>
                )}
                {error !== undefined && <ErrorPanel error={error} />}
            </div>
        </ConsoleDialog>
    );
}

function ExportDialog({ repo, open, onOpenChange }: { repo: Repo; open: boolean; onOpenChange: (open: boolean) => void }) {
    const [connectionId, setConnectionId] = useState('');
    const [owner, setOwner] = useState('');
    const [name, setName] = useState(repo.name);
    const [isPrivate, setPrivate] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<unknown>(undefined);
    // A GitHub connection of the repo's user, or of the account.
    const own = useScopeConnections(repo.userId);
    const account = useScopeConnections(null);
    const github = [...(own.data ?? []), ...(repo.userId ? (account.data ?? []) : [])].filter((c) => c.integration === 'github');
    const listed = own.data !== undefined && (!repo.userId || account.data !== undefined);
    const connection = github.find((c) => c.id === connectionId) ?? null;
    const href = useConsoleHref();
    useEffect(() => {
        if (!open) return;
        setConnectionId('');
        setOwner('');
        setName(repo.name);
        setPrivate(true);
        setError(undefined);
    }, [open, repo.name]);
    const connectUrl = error instanceof NeedsConnection ? (error.connectUrl ?? null) : null;
    const valid = !!connection && GITHUB_OWNER.test(owner.trim()) && GITHUB_NAME.test(name.trim()) && !['.', '..'].includes(name.trim());
    const start = async () => {
        if (!connection) return;
        setBusy(true);
        setError(undefined);
        try {
            await repo.exportToGithub({ connection, owner: owner.trim(), name: name.trim(), private: isPrivate });
            toast(`Pushing ${repo.name} to github.com/${owner.trim()}/${name.trim()}. It shows in Logs when it’s done.`);
            onOpenChange(false);
        } catch (e) {
            setError(e);
        } finally {
            setBusy(false);
        }
    };
    return (
        <ConsoleDialog
            open={open}
            onOpenChange={onOpenChange}
            mark={<Upload aria-hidden className="h-5 w-5" />}
            title="Export to GitHub"
            description="Pushes every branch and its history to a new GitHub repository. This repo, and the apps that deploy it, stay as they are."
            footer={
                <ConsoleButton variant="primary" disabled={busy || !valid} onClick={() => void start()}>
                    {busy ? 'Starting…' : 'Export'}
                </ConsoleButton>
            }
        >
            <form
                className="flex flex-col gap-3"
                onSubmit={(e) => {
                    e.preventDefault();
                    if (valid) void start();
                }}
            >
                <LabeledInput label="GitHub connection" id="github-connection">
                    <FieldSelect
                        id="github-connection"
                        value={connectionId}
                        onValueChange={setConnectionId}
                        placeholder={github.length || !listed ? 'Choose a connection' : 'No GitHub connection yet'}
                        options={github.map((c) => ({
                            value: c.id,
                            label: `${c.name}${c.userId ? '' : ' · account'}${c.account ? ` · ${c.account}` : ''}${c.status !== 'connected' ? ` · ${connectionLook(c).label.toLowerCase()}` : ''}`,
                        }))}
                    />
                </LabeledInput>
                {listed && !github.length && (
                    <p className="m-0 -mt-1 text-[12px] text-muted-foreground">
                        It pushes through a GitHub account you connect.{' '}
                        <Link to={href('resources/connections')} className="text-foreground underline underline-offset-2">
                            Connect a GitHub account
                        </Link>
                    </p>
                )}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <LabeledInput label="GitHub owner" id="github-owner">
                        <input id="github-owner" className={INPUT} value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="acme" autoComplete="off" />
                    </LabeledInput>
                    <LabeledInput label="Repository" id="github-name">
                        <input id="github-name" className={cn(INPUT, 'font-mono')} value={name} onChange={(e) => setName(e.target.value)} autoComplete="off" />
                    </LabeledInput>
                </div>
                <SwitchRow label="Private repository" description="Only people you let in on GitHub see it." checked={isPrivate} onCheckedChange={setPrivate} />
                {error !== undefined && (
                    <div className="flex flex-col gap-2">
                        <ErrorPanel error={error} />
                        {connectUrl && (
                            <a href={connectUrl} target="_blank" rel="noreferrer" className={consoleButtonClass('soft', 'sm', 'self-start')}>
                                Connect GitHub
                            </a>
                        )}
                    </div>
                )}
            </form>
        </ConsoleDialog>
    );
}

function RepoFooter({ repo, onDeleted }: { repo: Repo; onDeleted: () => void }) {
    const [dialog, setDialog] = useState<'clone' | 'export' | null>(null);
    const apps = repo.usedBy.map((u) => u.name).join(', ');
    return (
        <>
            <ConsoleButton variant="primary" onClick={() => setDialog('clone')}>
                Clone
            </ConsoleButton>
            <ConsoleButton onClick={() => setDialog('export')}>Export to GitHub</ConsoleButton>
            <span className="flex-1" />
            <ConfirmAction
                label="Delete repo"
                title={`Delete ${repo.name}?`}
                description={apps ? `${apps} deploys from it, so it can’t be deleted until that app is.` : 'Its files and history are deleted. Export it first if you want to keep a copy.'}
                confirmLabel="Delete repo"
                onConfirm={async () => {
                    await repo.delete();
                    invalidateV1('repos');
                    invalidateV1('account');
                    toast(`Deleted ${repo.name}`);
                    onDeleted();
                }}
            />
            <CloneDialog repo={repo} open={dialog === 'clone'} onOpenChange={(open) => setDialog(open ? 'clone' : null)} />
            <ExportDialog repo={repo} open={dialog === 'export'} onOpenChange={(open) => setDialog(open ? 'export' : null)} />
        </>
    );
}

function RepoDrawer({ repoId, row, onClose }: { repoId: string | null; row?: Repo; onClose: () => void }) {
    const { client } = useConsole();
    const [params, setParams] = useSearchParams();
    const fetched = useV1(repoId && !row ? `repos/${repoId}` : null, () => Repo.get(repoId!, { client }));
    const repo = row ?? fetched.data;
    const tab = params.get('tab');
    const active: TabId = TABS.some((t) => t.id === tab) ? (tab as TabId) : 'files';
    const setTab = (id: string) => setParams((prev) => withParams(prev, { tab: id === 'files' ? null : id, file: null }), { replace: true, preventScrollReset: true });
    useEffect(() => {
        if (repo) recordRecent({ type: 'repo', id: repo.id, label: repo.name, path: 'resources/repos', params: { repo: repo.id } });
    }, [repo?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    const last = repo?.lastCommit;
    return (
        <Drawer
            open={repoId !== null}
            onOpenChange={(open) => !open && onClose()}
            kind="repo"
            title={repo?.name}
            id={repoId ?? undefined}
            footer={repo ? <RepoFooter repo={repo} onDeleted={onClose} /> : undefined}
        >
            {!repo && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!repo && fetched.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {repo && (
                <div className="flex flex-col gap-5">
                    <dl className="m-0">
                        <Field label="Default branch">
                            <BranchName name={repo.defaultBranch} />
                        </Field>
                        <Field label="Last commit">
                            {last ? (
                                <span className="text-[13px]">
                                    {last.message}{' '}
                                    <span className="text-muted-foreground">
                                        · {commitLine(last)} · <TimeCell value={last.createdAt} />
                                    </span>
                                </span>
                            ) : (
                                <span className="text-muted-foreground">None yet</span>
                            )}
                        </Field>
                        <Field label="Size">{repo.sizeBytes != null ? fmtBytes(repo.sizeBytes) : '—'}</Field>
                        <Field label="Used by">
                            <UsedBy repo={repo} />
                        </Field>
                        <Field label="User">
                            <span className={repo.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(repo.userId)}</span>
                        </Field>
                    </dl>
                    <RepoTabs repo={repo} active={active} setTab={setTab} />
                </div>
            )}
        </Drawer>
    );
}

/** The drawer's tabs, Files and Commits on the branch `?branch=` names (the default one when absent). */
function RepoTabs({ repo, active, setTab }: { repo: Repo; active: TabId; setTab: (id: string) => void }) {
    const [params, setParams] = useSearchParams();
    const branches = useBranches(repo);
    const names = (branches.data ?? []).map((b) => b.name);
    const branch = params.get('branch') || repo.defaultBranch;
    const setBranch = (next: string) =>
        setParams((prev) => withParams(prev, { branch: next === repo.defaultBranch ? null : next, file: null }), { replace: true, preventScrollReset: true });
    return (
        <>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <PillSwitch label="Repo" tabs={TABS} value={active} onChange={setTab} />
                {active !== 'branches' && names.length > 1 && (
                    <Segmented label="Branch" value={branch} onChange={setBranch} className="max-w-full overflow-x-auto" options={names.map((n) => ({ value: n, label: n }))} />
                )}
            </div>
            {active === 'files' && <RepoFiles repo={repo} branch={branch} />}
            {active === 'commits' && <RepoCommits repo={repo} branch={branch} />}
            {active === 'branches' && <RepoBranches repo={repo} />}
        </>
    );
}

export function ReposPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const [repoId, setRepo] = useSearchParam('repo');
    const [, setParams] = useSearchParams();
    const paged = usePaged(`repos?${user}`, (cursor) => Repo.listPage({ client, userFilter: user, cursor, limit: 50 }), (r) => r.id);
    const columns: Column<Repo>[] = [
        {
            id: 'name',
            header: 'Repo',
            width: '10rem',
            cell: (r) => <span className="truncate font-medium text-foreground">{r.name}</span>,
        },
        {
            id: 'commit',
            header: 'Last commit',
            priority: 2,
            cell: (r) => (r.lastCommit ? <span className="block truncate text-foreground/90">{r.lastCommit.message}</span> : <span className="text-muted-foreground">Empty</span>),
        },
        {
            id: 'updated',
            header: 'Updated',
            width: '6.5rem',
            cell: (r) => <TimeCell value={r.lastCommit?.createdAt ?? r.createdAt} />,
        },
        {
            id: 'branch',
            header: 'Default branch',
            priority: 3,
            width: '8rem',
            cell: (r) => <span className="text-muted-foreground">{r.defaultBranch}</span>,
        },
        {
            id: 'size',
            header: 'Size',
            priority: 3,
            width: '5.5rem',
            align: 'right',
            cell: (r) => <span className="tabular-nums text-muted-foreground">{r.sizeBytes != null ? fmtBytes(r.sizeBytes) : '—'}</span>,
        },
        {
            id: 'used',
            header: 'Used by',
            priority: 3,
            width: '8rem',
            cell: (r) => <UsedBy repo={r} />,
        },
        {
            id: 'user',
            header: 'User',
            priority: 2,
            width: '7rem',
            cell: (r) => <span className={r.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(r.userId)}</span>,
        },
    ];
    const close = () => setParams((prev) => withParams(prev, { repo: null, tab: null, file: null, branch: null }), { replace: true, preventScrollReset: true });
    return (
        <>
            <PanelToolbar
                user={user}
                setUser={setUser}
                action={<NewInCode kind="repo" place={{ user: defaultWriteUser(user) }} />}
            />
            <DataTable
                rowMenu="repo"
                label="Repos"
                columns={columns}
                rows={paged.rows}
                getRowId={(r) => r.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(r) => setRepo(r.id, { push: true })}
                selectedId={repoId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={<EmptyCode title="No repos yet." hint="A repo is plain git: your code and agents commit to it, and any git client can clone it." snippet={NEW_SNIPPETS.repo({ user: defaultWriteUser(user) })} />}
            />
            <RepoDrawer repoId={repoId} row={paged.rows.find((r) => r.id === repoId)} onClose={close} />
        </>
    );
}
