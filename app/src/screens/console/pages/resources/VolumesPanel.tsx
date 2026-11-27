// Volumes: persistent filesystems that sandboxes and agents mount. The drawer
// (`?volume=`, the folder in `&path=`) says what it holds beside its name, browses the
// files a folder at a time and downloads one, lists who mounts it, exports, folds the code
// that mounts it in a sandbox and an agent last, and deletes (type the name).
import { useEffect } from 'react';
import { useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { Volume, type VolumeMount } from 'noclick';
import { NEW_SNIPPETS, snippetTabs, type Snippet } from '@/screens/console/lib/snippets';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { NewInCode } from '../../NewInCode';
import { CodeSnippet } from '../../ui/CodeSnippet';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { Folded, HeaderNote } from '../../ui/DrawerParts';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { TimeCell } from '../../ui/TimeCell';
import { Field, PanelToolbar, Section, type PanelProps } from './shared';
import { DeleteByName, ExportSection, formatExact, formatSize } from './StorageShared';
import { VolumeFiles } from './VolumesFiles';
import { UsesList, UsesSummary, type ResourceUse } from './VolumesSecretsShared';

/** The code that mounts `name` at `path` in a sandbox and in an agent's shell, acting for its user. */
export function volumeMountSnippet(name: string, path: string, userId: string | null): Snippet {
    const lit = (s: string) => JSON.stringify(s);
    const pyUser = userId ? `, user=${lit(userId)}` : '';
    const tsUser = userId ? `, user: ${lit(userId)}` : '';
    return {
        python: [
            'import noclick',
            '',
            `vol = noclick.Volume.from_name(${lit(name)}${pyUser})`,
            '',
            `# A sandbox: what it writes under ${path} is saved when it ends.`,
            `with noclick.Sandbox.create(volumes={${lit(path)}: vol}${pyUser}) as sb:`,
            `    print(sb.exec(${lit(`ls ${path}`)}).stdout)`,
            '',
            "# An agent's shell, in every conversation.",
            'agent = noclick.Agent.from_name(',
            '    "analyst",',
            '    create_if_missing=True,',
            `    instructions=${lit(`Your files are in ${path}.`)},`,
            `    volumes={${lit(path)}: vol},`,
            ...(userId ? [`    user=${lit(userId)},`] : []),
            ')',
        ].join('\n'),
        typescript: [
            'import { Agent, Sandbox, Volume } from "noclick";',
            '',
            `const vol = Volume.fromName(${lit(name)}${userId ? `, { user: ${lit(userId)} }` : ''});`,
            '',
            `// A sandbox: what it writes under ${path} is saved when it ends.`,
            `const sb = await Sandbox.create({ volumes: { ${lit(path)}: vol }${tsUser} });`,
            `console.log((await sb.exec(${lit(`ls ${path}`)})).stdout);`,
            'await sb.terminate();',
            '',
            "// An agent's shell, in every conversation.",
            'const agent = Agent.fromName("analyst", {',
            '    createIfMissing: true,',
            `    instructions: ${lit(`Your files are in ${path}.`)},`,
            `    volumes: { ${lit(path)}: vol },`,
            ...(userId ? [`    user: ${lit(userId)},`] : []),
            '});',
            'await agent.hydrate();',
        ].join('\n'),
    };
}

export function mountUses(mounts: readonly VolumeMount[]): ResourceUse[] {
    return mounts.map((m) => ({ kind: m.kind, id: m.id, name: m.name, detail: m.path }));
}

function VolumeDrawer({ volumeId, row, onClose }: { volumeId: string | null; row?: Volume; onClose: () => void }) {
    const { client } = useConsole();
    const [path, setPath] = useSearchParam('path');
    const fetched = useV1(volumeId && !row ? `volumes/${volumeId}` : null, () => Volume.get(volumeId!, { client }));
    const volume = row ?? fetched.data;
    useEffect(() => {
        if (volume) recordRecent({ type: 'volume', id: volume.id, label: volume.name, path: 'resources/volumes', params: { volume: volume.id } });
    }, [volume?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    const uses = volume ? mountUses(volume.mountedBy) : [];
    const agentsMounting = uses.filter((u) => u.kind === 'agent');
    return (
        <Drawer
            open={volumeId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="Volume"
            title={volume?.name}
            id={volumeId ?? undefined}
            status={
                volume ? (
                    <HeaderNote>
                        {formatSize(volume.sizeBytes)} in {volume.fileCount === 1 ? '1 file' : `${formatExact(volume.fileCount)} files`}
                    </HeaderNote>
                ) : undefined
            }
            footer={
                volume ? (
                    <DeleteByName
                        label="Delete volume"
                        name={volume.name}
                        description={
                            agentsMounting.length
                                ? `${agentsMounting.map((u) => u.name).join(', ')} ${agentsMounting.length === 1 ? 'mounts' : 'mount'} it, so the delete is refused until ${agentsMounting.length === 1 ? "it's" : "they're"} changed not to.`
                                : uses.length
                                  ? 'A running sandbox mounts it, so the delete is refused until the sandbox ends.'
                                  : `Its ${formatExact(volume.fileCount)} files (${formatSize(volume.sizeBytes)}) are deleted with it. This can't be undone.`
                        }
                        onConfirm={async () => {
                            await volume.delete();
                            invalidateV1('volumes');
                            invalidateV1('account');
                            toast(`Deleted ${volume.name}`);
                            onClose();
                        }}
                    />
                ) : undefined
            }
        >
            {!volume && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!volume && fetched.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {volume && (
                <div key={volume.id} className="flex flex-col gap-6">
                    <VolumeFiles volume={volume} path={path || '/'} onPath={(p) => setPath(p === '/' ? null : p)} />
                    <Section title="Mounted by">
                        <UsesList uses={uses} label={`Mounts of ${volume.name}`} empty="Nothing mounts it right now. Agents that list it, and sandboxes while they run, show here." />
                    </Section>
                    <ExportSection what="Every file in its folders, with an index of their sizes and times, at a link valid 7 days." start={() => volume.export()} />
                    <Folded title="Details: its user, the code that mounts it">
                        <dl className="m-0">
                            <Field label="User">{userLabel(volume.userId)}</Field>
                            <Field label="Created">
                                <TimeCell value={volume.createdAt} tier="absolute" />
                            </Field>
                        </dl>
                        <Section title="Mount it">
                            <p className="m-0 mb-2 text-[12px] text-muted-foreground">Read-write at the path you choose. What a sandbox or an agent&apos;s turn writes is saved when it ends.</p>
                            <CodeSnippet tabs={snippetTabs(volumeMountSnippet(volume.name, volume.mountedBy[0]?.path ?? '/data', volume.userId))} />
                        </Section>
                    </Folded>
                </div>
            )}
        </Drawer>
    );
}

export function VolumesPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const [volumeId, setVolume] = useSearchParam('volume');
    const [, setParams] = useSearchParams();
    const paged = usePaged(`volumes?${user}`, (cursor) => Volume.listPage({ client, userFilter: user, cursor, limit: 50 }), (v) => v.id);
    const columns: Column<Volume>[] = [
        { id: 'name', header: 'Name', cell: (v) => <span className="truncate font-medium text-foreground">{v.name}</span> },
        { id: 'size', header: 'Size', width: '6rem', cell: (v) => <span className="tabular-nums">{formatSize(v.sizeBytes)}</span> },
        { id: 'files', header: 'Files', width: '6rem', priority: 2, cell: (v) => <span className="tabular-nums">{formatExact(v.fileCount)}</span> },
        { id: 'mounted', header: 'Used by', priority: 2, cell: (v) => <UsesSummary uses={mountUses(v.mountedBy)} /> },
        {
            id: 'user',
            header: 'User',
            width: '8rem',
            priority: 2,
            cell: (v) => <span className={v.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(v.userId)}</span>,
        },
        { id: 'created', header: 'Created', width: '6.5rem', priority: 3, cell: (v) => <TimeCell value={v.createdAt} /> },
    ];
    return (
        <>
            <PanelToolbar user={user} setUser={setUser} action={<NewInCode kind="volume" place={{ user: defaultWriteUser(user) }} />} />
            <DataTable
                rowMenu="volume"
                label="Volumes"
                columns={columns}
                rows={paged.rows}
                getRowId={(v) => v.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(v) => setVolume(v.id, { push: true })}
                selectedId={volumeId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={<EmptyCode title="No volumes yet." hint="Persistent folders for datasets, caches and build output, mounted into sandboxes and agents." snippet={NEW_SNIPPETS.volume({ user: defaultWriteUser(user) })} />}
            />
            <VolumeDrawer
                volumeId={volumeId}
                row={paged.rows.find((v) => v.id === volumeId)}
                onClose={() =>
                    setParams(
                        (prev) => {
                            const out = new URLSearchParams(prev);
                            out.delete('volume');
                            out.delete('path');
                            return out;
                        },
                        { replace: true, preventScrollReset: true }
                    )
                }
            />
        </>
    );
}
