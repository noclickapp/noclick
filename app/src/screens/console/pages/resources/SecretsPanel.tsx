// Secrets: named environment values for sandboxes, agents' shells and (designed) apps, made in code from the program's
// own environment. The table and drawer (`?secret=`) show key names,
// never values; the drawer sets values (merge or replace) through a masked dialog, removes
// a key, lists who reads the secret, shows the code that uses it, and deletes it.
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router';
import { toast } from 'sonner';
import { HAIRLINE } from '@/ui/primitives';
import { cn } from '@/ui/utils';
import { Secret, type UsedBy } from 'noclick';
import { NEW_SNIPPETS, snippetTabs, type Snippet } from '@/screens/console/lib/snippets';
import { defaultWriteUser, userLabel } from '@/screens/console/lib/userFilter';
import { useConsole } from '@/screens/console/hooks/useConsole';
import { usePaged } from '@/sdk/usePaged';
import { useSearchParam } from '@/screens/console/hooks/useQueryState';
import { recordRecent } from '@/screens/console/hooks/useRecent';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import { NewInCode } from '../../NewInCode';
import { ConsoleButton } from '../../ui/Button';
import { CodeSnippet } from '../../ui/CodeSnippet';
import { DataTable, type Column } from '../../ui/DataTable';
import { Drawer } from '../../ui/Drawer';
import { EmptyCode } from '../../ui/EmptyCode';
import { ErrorPanel } from '../../ui/ErrorPanel';
import { TimeCell } from '../../ui/TimeCell';
import { ConfirmAction, Field, PanelToolbar, Section, type PanelProps } from './shared';
import { SetValuesDialog } from './SecretsValues';
import { UsesList, UsesSummary, type ResourceUse } from './VolumesSecretsShared';

/** The code that puts `name`'s keys in a sandbox's environment and an agent's shell, acting for its user. */
export function secretUseSnippet(name: string, key: string, userId: string | null): Snippet {
    const lit = (s: string) => JSON.stringify(s);
    return {
        python: [
            'import noclick',
            '',
            `secret = noclick.Secret.from_name(${lit(name)}${userId ? `, user=${lit(userId)}` : ''})`,
            '',
            `# A sandbox: every command sees $${key}.`,
            `with noclick.Sandbox.create(secrets=[secret]${userId ? `, user=${lit(userId)}` : ''}) as sb:`,
            '    sb.exec("python job.py")',
            '',
            "# An agent's shell, in every turn.",
            'agent = noclick.Agent.from_name(',
            '    "analyst",',
            '    create_if_missing=True,',
            `    instructions=${lit(`Call the API with $${key}.`)},`,
            '    secrets=[secret],',
            ...(userId ? [`    user=${lit(userId)},`] : []),
            ')',
        ].join('\n'),
        typescript: [
            'import { Agent, Sandbox, Secret } from "noclick";',
            '',
            `const secret = Secret.fromName(${lit(name)}${userId ? `, { user: ${lit(userId)} }` : ''});`,
            '',
            `// A sandbox: every command sees $${key}.`,
            `const sb = await Sandbox.create({ secrets: [secret]${userId ? `, user: ${lit(userId)}` : ''} });`,
            'await sb.exec("node job.js");',
            'await sb.terminate();',
            '',
            "// An agent's shell, in every turn.",
            'const agent = Agent.fromName("analyst", {',
            '    createIfMissing: true,',
            `    instructions: ${lit(`Call the API with $${key}.`)},`,
            '    secrets: [secret],',
            ...(userId ? [`    user: ${lit(userId)},`] : []),
            '});',
            'await agent.hydrate();',
        ].join('\n'),
    };
}

export function secretUses(usedBy: readonly UsedBy[]): ResourceUse[] {
    return usedBy.map((u) => ({ kind: u.kind, id: u.id, name: u.name || null, detail: u.binding }));
}

/** Key names as chips; past `max`, the rest as a count. */
function KeyChips({ keys, max = 3 }: { keys: readonly string[]; max?: number }) {
    if (!keys.length) return <span className="text-muted-foreground">No keys</span>;
    const shown = keys.slice(0, max);
    return (
        <span className="flex min-w-0 flex-wrap items-center gap-1">
            {shown.map((k) => (
                <span key={k} className={cn('max-w-full truncate rounded border bg-foreground/[0.03] px-1.5 py-px font-mono text-[12px] text-foreground', HAIRLINE)}>
                    {k}
                </span>
            ))}
            {keys.length > max && <span className="text-[12px] text-muted-foreground">+{keys.length - max}</span>}
        </span>
    );
}

function KeysSection({ secret, onChanged }: { secret: Secret; onChanged: (secret: Secret) => void }) {
    const [editing, setEditing] = useState<{ key: string | null } | null>(null);
    return (
        <Section
            title={
                <span className="flex items-center justify-between gap-2">
                    <span>Keys</span>
                    <ConsoleButton size="sm" onClick={() => setEditing({ key: null })}>
                        Set values
                    </ConsoleButton>
                </span>
            }
        >
            <p className="m-0 mb-2 text-[12px] text-muted-foreground">Each key is an environment variable wherever the secret is used. Only names show here; a value never comes back.</p>
            {secret.keys.length ? (
                <ul aria-label="Keys" className={'m-0 list-none p-0'}>
                    {secret.keys.map((key) => (
                        <li key={key} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                            <span className="min-w-0 flex-1 truncate font-mono text-[13px] font-medium text-foreground">{key}</span>
                            <span aria-hidden className="hidden font-mono text-[12px] tracking-widest text-muted-foreground sm:inline">
                                ••••••••
                            </span>
                            <ConsoleButton size="sm" variant="ghost" onClick={() => setEditing({ key })}>
                                Replace
                            </ConsoleButton>
                            <ConfirmAction
                                label="Remove"
                                title={`Remove ${key}?`}
                                description={`${key} leaves ${secret.name}: new sandboxes don't get it, agents lose it from their next turn, apps at their next deploy. The value can't be recovered.`}
                                confirmLabel="Remove key"
                                onConfirm={async () => {
                                    onChanged(await secret.update({ [key]: null }));
                                    invalidateV1('secrets');
                                    toast(`Removed ${key} from ${secret.name}`);
                                }}
                            />
                        </li>
                    ))}
                </ul>
            ) : (
                <p className="m-0 text-[13px] text-muted-foreground">No keys yet. Set the values your code needs; they reach it as environment variables.</p>
            )}
            <SetValuesDialog secret={secret} open={editing !== null} initialKey={editing?.key ?? null} onOpenChange={(o) => !o && setEditing(null)} onSaved={onChanged} />
        </Section>
    );
}

function SecretDrawer({ secretId, row, onClose }: { secretId: string | null; row?: Secret; onClose: () => void }) {
    const { client } = useConsole();
    const fetched = useV1(secretId && !row ? `secrets/${secretId}` : null, () => Secret.get(secretId!, { client }));
    // `update` returns the same object with new keys, so each save is wrapped to re-render.
    const [updated, setUpdated] = useState<{ secret: Secret } | null>(null);
    const secret = (updated && updated.secret.id === secretId ? updated.secret : null) ?? row ?? fetched.data;
    useEffect(() => {
        if (secret) recordRecent({ type: 'secret', id: secret.id, label: secret.name, path: 'resources/secrets', params: { secret: secret.id } });
    }, [secret?.id]); // eslint-disable-line react-hooks/exhaustive-deps
    const uses = secret ? secretUses(secret.usedBy) : [];
    const blocking = uses.filter((u) => u.kind !== 'sandbox');
    return (
        <Drawer
            open={secretId !== null}
            onOpenChange={(o) => !o && onClose()}
            kind="secret"
            title={secret?.name}
            id={secretId ?? undefined}
            footer={
                secret ? (
                    <ConfirmAction
                        label="Delete secret"
                        title={`Delete ${secret.name}?`}
                        description={
                            blocking.length
                                ? `${blocking.map((u) => u.name).join(', ')} ${blocking.length === 1 ? 'uses' : 'use'} it, so the delete is refused until ${blocking.length === 1 ? "it's" : "they're"} changed not to.`
                                : `Its ${secret.keys.length === 1 ? 'value is' : `${secret.keys.length} values are`} deleted and can't be recovered. Sandboxes already running keep theirs until they end.`
                        }
                        confirmLabel="Delete secret"
                        onConfirm={async () => {
                            await secret.delete();
                            invalidateV1('secrets');
                            invalidateV1('account');
                            toast(`Deleted ${secret.name}`);
                            onClose();
                        }}
                    />
                ) : undefined
            }
        >
            {!secret && fetched.error !== undefined && <ErrorPanel error={fetched.error} onRetry={() => void fetched.refresh()} />}
            {!secret && fetched.error === undefined && <div aria-busy className="h-40 animate-pulse rounded-lg bg-foreground/[0.04]" />}
            {secret && (
                <div key={secret.id} className="flex flex-col gap-6">
                    <dl className="m-0">
                        <Field label="User">{userLabel(secret.userId)}</Field>
                        <Field label="Values set">
                            <TimeCell value={secret.updatedAt} tier="absolute" />
                        </Field>
                        <Field label="Created">
                            <TimeCell value={secret.createdAt} tier="absolute" />
                        </Field>
                    </dl>
                    <KeysSection secret={secret} onChanged={(saved) => setUpdated({ secret: saved })} />
                    <Section title="Used by">
                        <UsesList uses={uses} label={`What uses ${secret.name}`} empty="Nothing uses it yet. Agents that list it, apps that bind it and running sandboxes show here." />
                    </Section>
                    <Section title="Use it">
                        <p className="m-0 mb-2 text-[12px] text-muted-foreground">Each key becomes an environment variable. When two secrets hold the same key, the later one in the list wins.</p>
                        <CodeSnippet tabs={snippetTabs(secretUseSnippet(secret.name, secret.keys[0] ?? 'API_KEY', secret.userId))} />
                    </Section>
                </div>
            )}
        </Drawer>
    );
}

export function SecretsPanel({ user, setUser }: PanelProps) {
    const { client } = useConsole();
    const [secretId, setSecret] = useSearchParam('secret');
    const [, setParams] = useSearchParams();
    const paged = usePaged(`secrets?${user}`, (cursor) => Secret.listPage({ client, userFilter: user, cursor, limit: 50 }), (s) => s.id);
    const columns: Column<Secret>[] = [
        { id: 'name', header: 'Name', width: '10rem', cell: (s) => <span className="truncate font-medium text-foreground">{s.name}</span> },
        { id: 'keys', header: 'Keys', cell: (s) => <KeyChips keys={s.keys} /> },
        { id: 'used', header: 'Used by', priority: 2, cell: (s) => <UsesSummary uses={secretUses(s.usedBy)} /> },
        { id: 'updated', header: 'Updated', width: '6.5rem', priority: 3, cell: (s) => <TimeCell value={s.updatedAt} /> },
        {
            id: 'user',
            header: 'User',
            width: '8rem',
            priority: 2,
            cell: (s) => <span className={s.userId ? 'text-foreground/85' : 'text-muted-foreground'}>{userLabel(s.userId)}</span>,
        },
    ];
    return (
        <>
            <PanelToolbar user={user} setUser={setUser} action={<NewInCode kind="secret" place={{ user: defaultWriteUser(user) }} />} />
            <DataTable
                rowMenu="secret"
                label="Secrets"
                columns={columns}
                rows={paged.rows}
                getRowId={(s) => s.id}
                loading={paged.loading}
                error={paged.error}
                onRetry={() => void paged.refresh()}
                onRowClick={(s) => setSecret(s.id, { push: true })}
                selectedId={secretId}
                nextCursor={paged.nextCursor}
                onLoadMore={() => void paged.loadMore()}
                loadingMore={paged.loadingMore}
                empty={<EmptyCode title="No secrets yet." hint="API keys and other values your sandboxes, agents and apps read from their environment." snippet={NEW_SNIPPETS.secret({ user: defaultWriteUser(user) })} />}
            />
            <SecretDrawer
                secretId={secretId}
                row={paged.rows.find((s) => s.id === secretId)}
                onClose={() =>
                    setParams(
                        (prev) => {
                            const out = new URLSearchParams(prev);
                            out.delete('secret');
                            return out;
                        },
                        { replace: true, preventScrollReset: true }
                    )
                }
            />
        </>
    );
}
