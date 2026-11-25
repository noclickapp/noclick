// What an agent works with beyond its tools: its own git remote, the commands its sandbox runs as it starts, and what a
// move from a laptop carried (its model key, its secrets, its tool servers' sign-ins), each saying where it came from
// and where it lives, with Remove, which revokes it everywhere (an agent that reads a secret is told first). A tool
// server the laptop signed in to in a browser can't move its sign-in: the person signs in here (Connect).
import { useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import { FileText, GitBranch, KeyRound, Lock, Plug, Terminal } from 'lucide-react';
import { Agent, previewDelete, type Connection, type NoClick, type Secret } from 'noclick';
import { invalidateV1 } from '@/sdk/useV1';
import { DeleteConfirmPopup } from '@/ui/DeleteConfirmPopup';
import { BUTTON_PRIMARY, BUTTON_GHOST } from '@/ui/buttons';
import { cn } from '@/ui/utils';
import { useWorkClient } from '../client';
import { AGENTS_KEY, nameOf } from '../agents/reads';
import { rereadAccounts, useConnections, useModelAccounts } from '../newAgent/catalog';
import { rereadAgent, SECRETS_KEY, useMove, useSecrets } from './reads';
import { browserSignInsOf, ConnectSignIn, useBrowserSignIn, type BrowserSignIn } from '../moves/signIns';
import { movedFrom, movedLine, type MovedFrom, type MovedTo } from '@/lib/movedFrom';

/** Where a move carried it from, and where it went in the copy (`moved_from` on a connection or a secret). */
const movedOf = (o: { raw: object } | undefined): MovedFrom | null => movedFrom((o?.raw as { moved_from?: unknown } | undefined)?.moved_from);

/** A git remote of its own (`{url, branch, ...}`), as a move from a laptop sets one. */
interface Remote {
    url: string;
    branch: string | null;
    secret: string | null;
}

const remotesOf = (agent: Agent): Remote[] =>
    agent.repos.flatMap((r) => (typeof r.url === 'string' ? [{ url: r.url, branch: typeof r.branch === 'string' ? r.branch : null, secret: typeof r.secret === 'string' ? r.secret : null }] : []));

const shortUrl = (url: string) => url.replace(/^https?:\/\//, '').replace(/\.git$/, '');

const HEADING = 'text-xs font-medium text-muted-foreground';
const ROW_ICON = 'mt-[3px] h-3.5 w-3.5 shrink-0 text-muted-foreground';
const REMOVE = 'shrink-0 rounded-full px-2 py-0.5 text-[12.5px] text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 dark:hover:text-red-400';

function Row({ icon, title, detail, onRemove, busy, action }: { icon: ReactNode; title: ReactNode; detail?: ReactNode; onRemove?: () => void; busy?: boolean; action?: ReactNode }) {
    return (
        <li className="flex items-start gap-2.5 py-1 text-sm">
            {icon}
            <span className="min-w-0 flex-1">
                <span className="block truncate">{title}</span>
                {detail && <span className="block break-words text-[12.5px] leading-snug text-muted-foreground">{detail}</span>}
            </span>
            {action}
            {onRemove && (
                <button type="button" disabled={busy} onClick={onRemove} className={REMOVE}>
                    Remove
                </button>
            )}
        </li>
    );
}

export function AgentCarried({ agent }: { agent: Agent }) {
    return (
        <>
            <Remotes agent={agent} />
            <Setup agent={agent} />
            <Moved agent={agent} />
        </>
    );
}

/** Its own git remotes: where its code is, the branch it works on, and the secret it signs in with. */
function Remotes({ agent }: { agent: Agent }) {
    const secrets = useSecrets();
    const remotes = remotesOf(agent);
    if (!remotes.length) return null;
    return (
        <section className="mt-6" data-testid="agent-remotes">
            <h3 className={HEADING}>Its code</h3>
            <ul className="mt-1.5 space-y-0.5">
                {remotes.map((r) => {
                    const signIn = r.secret ? (secrets.data?.find((s) => s.id === r.secret)?.name ?? null) : null;
                    return (
                        <Row
                            key={`${r.url}#${r.branch}`}
                            icon={<GitBranch className={ROW_ICON} strokeWidth={1.75} />}
                            title={shortUrl(r.url)}
                            detail={[r.branch, signIn && `signs in with ${signIn}`].filter(Boolean).join(' · ') || undefined}
                        />
                    );
                })}
            </ul>
        </section>
    );
}

/** The commands its sandbox runs as it starts, edited in place (one a line; none clears them). */
function Setup({ agent }: { agent: Agent }) {
    const client = useWorkClient();
    const [draft, setDraft] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    if (!agent.setup.length && draft === null) return null;
    const save = async () => {
        const setup = (draft ?? '')
            .split('\n')
            .map((l) => l.trim())
            .filter(Boolean);
        setSaving(true);
        try {
            await Agent.fromId(agent.id, { client }).update({ setup });
            rereadAgent(agent.id);
            setDraft(null);
        } catch (error) {
            toast('Couldn’t change what it runs as it starts', { description: error instanceof Error ? error.message : String(error) });
        } finally {
            setSaving(false);
        }
    };
    return (
        <section className="mt-6" data-testid="agent-setup">
            <h3 className={cn(HEADING, 'flex items-center')}>
                As its sandbox starts
                {draft === null && (
                    <button type="button" onClick={() => setDraft(agent.setup.join('\n'))} className="-my-0.5 ml-auto rounded-full px-1.5 py-0.5 font-normal transition-colors hover:bg-foreground/[0.06] hover:text-foreground">
                        Edit
                    </button>
                )}
            </h3>
            {draft === null ? (
                <ul className="mt-1.5 space-y-1">
                    {agent.setup.map((line, i) => (
                        <li key={i} className="flex items-start gap-2.5 text-sm">
                            <Terminal className={ROW_ICON} strokeWidth={1.75} />
                            <code className="min-w-0 flex-1 break-all font-mono text-[12px] leading-relaxed text-foreground/85">{line}</code>
                        </li>
                    ))}
                </ul>
            ) : (
                <div className="mt-1.5">
                    <textarea
                        aria-label="Commands it runs as its sandbox starts"
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        rows={Math.min(8, Math.max(3, draft.split('\n').length + 1))}
                        className="block w-full resize-y rounded-[18px] bg-foreground/[0.04] px-3.5 py-2.5 font-mono text-[12px] leading-relaxed text-foreground outline-none ring-1 ring-inset ring-border focus:ring-foreground/30 dark:ring-foreground/[0.09]"
                    />
                    <p className="mt-1 text-[12px] text-muted-foreground">One command a line, run in order after its code is checked out, with its secrets in the environment.</p>
                    <div className="mt-2 flex justify-end gap-2">
                        <button type="button" onClick={() => setDraft(null)} className={cn(BUTTON_GHOST, 'h-8 px-3.5 text-[13px]')}>
                            Cancel
                        </button>
                        <button type="button" disabled={saving} onClick={() => void save()} className={cn(BUTTON_PRIMARY, 'h-8 px-3.5 text-[13px]')}>
                            Save
                        </button>
                    </div>
                </div>
            )}
        </section>
    );
}

/** One thing a removal asks about: its name, what goes with it, and what it does. */
interface Removing {
    title: string;
    message: string;
    run: () => Promise<void>;
}

/** A secret's place in the copy, in a person's words. */
function placeOf(to: MovedTo | null | undefined, secret: Secret): string {
    if (to?.env) return `$${to.env} in its shell`;
    if (to?.file) return `A file at ${to.file}`;
    if (to && !to.model && !to.toolServer) return 'For a tool server’s sign-in or its code';
    return secret.keys.join(', ');
}

/** What a move from a laptop carried: its model key, its secrets and the sign-ins they make, each removable. */
function Moved({ agent }: { agent: Agent }) {
    const client = useWorkClient();
    const connections = useConnections();
    const secrets = useSecrets();
    const { labels } = useModelAccounts();
    const [removing, setRemoving] = useState<Removing | null>(null);
    const [busy, setBusy] = useState(false);
    const name = nameOf(agent);
    const modelKey = connections.data?.find((c) => c.name === agent.modelConnection && movedOf(c));
    const moved = (secrets.data ?? []).filter((s) => agent.secretIds.includes(s.id) && movedOf(s));
    // Where it moved from: the agent's own stamp first (a move that carried only browser sign-ins has no other), else
    // its model key's or a secret's (an agent a user reads, whose stamp the API leaves out).
    const own = agent.movedFrom;
    const from: MovedFrom | null = own ? { moveId: own.moveId, host: own.host, folder: own.folder, at: own.at?.toISOString() ?? null, to: null } : (movedOf(modelKey) ?? movedOf(moved[0]));
    const move = useMove(from?.moveId ?? null);
    const carried = move.data?.arrived.carried ?? [];
    if (!from) return null;
    // A sign-in goes with the secrets it was made of, so one whose secrets are all gone is gone too.
    const logins = carried.filter(
        (c) => typeof (c.to as { tool_server?: unknown } | undefined)?.tool_server === 'string' && Array.isArray(c.secrets) && (secrets.data ?? []).some((s) => (c.secrets as string[]).includes(s.id))
    );
    // Tool servers the laptop signed in to in a browser: each needs signing in again here, then reads as signed in.
    const browserSignIns = move.data ? browserSignInsOf(move.data) : [];
    // A moved file secret is written by a setup line reading its key ("$NC_FILE_NPMRC"), with or without the move.
    if (!modelKey && !moved.length && !logins.length && !browserSignIns.length) return null;
    const setupOf = (secret: Secret) => (movedOf(secret)?.to?.file ? agent.setup.filter((line) => secret.keys.some((key) => line.includes(`"$${key}"`))) : []);

    const act = async (what: string, run: () => Promise<void>) => {
        setBusy(true);
        try {
            await run();
        } catch (error) {
            toast(`Couldn’t remove ${what}`, { description: error instanceof Error ? error.message : String(error) });
        } finally {
            setBusy(false);
            rereadAgent(agent.id);
            invalidateV1(AGENTS_KEY);
            invalidateV1(SECRETS_KEY);
        }
    };
    /** Takes the secrets out of its shell (and the setup lines that write them), then deletes them everywhere. */
    const dropSecrets = async (gone: Secret[]) => {
        const ids = new Set(gone.map((s) => s.id));
        const lines = new Set(gone.flatMap(setupOf));
        await Agent.fromId(agent.id, { client }).update({ secrets: agent.secretIds.filter((id) => !ids.has(id)), ...(lines.size ? { setup: agent.setup.filter((l) => !lines.has(l)) } : {}) });
        for (const s of gone) await s.delete();
    };
    const askSecrets = async (title: string, gone: Secret[], what: string) => {
        let others: string[];
        try {
            others = await alsoUsing(client, gone, agent.name);
        } catch (error) {
            toast(`Couldn’t check what else uses ${title}`, { description: error instanceof Error ? error.message : String(error) });
            return;
        }
        setRemoving({
            title,
            message: [`${what} is deleted from your account for good, and ${name} stops getting it from its next turn.`, ...others].join(' '),
            run: () => act(title, () => dropSecrets(gone)),
        });
    };
    const removeKey = (c: Connection) => {
        const provider = movedOf(c)?.to?.model;
        setRemoving({
            title: `its ${labels.get(provider ?? '') ?? provider ?? 'model'} key`,
            message: `The key is deleted from your account wherever it’s used. ${name} needs another model connection before its next turn.`,
            run: () =>
                act('its model key', async () => {
                    await c.delete();
                    rereadAccounts();
                }),
        });
    };

    return (
        <section className="mt-6" data-testid="agent-moved">
            <h3 className={HEADING}>
                {movedLine(from)}
            </h3>
            <ul className="mt-1.5 space-y-0.5">
                {modelKey && (
                    <Row
                        icon={<KeyRound className={ROW_ICON} strokeWidth={1.75} />}
                        title={`${labels.get(movedOf(modelKey)?.to?.model ?? '') ?? movedOf(modelKey)?.to?.model ?? 'Model'} key`}
                        detail={`Runs its model · ${modelKey.name}`}
                        busy={busy}
                        onRemove={() => removeKey(modelKey)}
                    />
                )}
                {moved.map((s) => (
                    <Row
                        key={s.id}
                        icon={movedOf(s)?.to?.file ? <FileText className={ROW_ICON} strokeWidth={1.75} /> : <Lock className={ROW_ICON} strokeWidth={1.75} />}
                        title={s.name}
                        detail={placeOf(movedOf(s)?.to, s)}
                        busy={busy}
                        onRemove={() => void askSecrets(s.name, [s], `The secret ${s.name}`)}
                    />
                ))}
                {browserSignIns.map((b) => (
                    <BrowserSignInRow key={`browser:${b.name}`} signIn={b} />
                ))}
                {logins.map((l) => {
                    const made = (secrets.data ?? []).filter((s) => (l.secrets as string[]).includes(s.id));
                    const server = String((l.to as { tool_server: string }).tool_server);
                    return (
                        <Row
                            key={`login:${server}`}
                            icon={<Plug className={ROW_ICON} strokeWidth={1.75} />}
                            title={`Signed in to ${server}`}
                            detail={made.length ? `With ${made.map((s) => s.name).join(', ')}` : undefined}
                            busy={busy}
                            onRemove={made.length ? () => void askSecrets(`its sign-in to ${server}`, made, `Its sign-in to ${server}`) : undefined}
                        />
                    );
                })}
            </ul>
            <DeleteConfirmPopup
                isOpen={!!removing}
                onOpenChange={(open) => !open && setRemoving(null)}
                itemType="item"
                title={removing ? `Remove ${removing.title}?` : undefined}
                customMessage={removing?.message}
                confirmLabel="Remove"
                onConfirmDelete={() => void removing?.run()}
            />
        </section>
    );
}

/** A tool server the laptop signed in to in a browser: signed in to here with Connect (`moves/signIns`). */
function BrowserSignInRow({ signIn }: { signIn: BrowserSignIn }) {
    const state = useBrowserSignIn(signIn);
    if (!signIn.needsSignIn) return <Row icon={<Plug className={ROW_ICON} strokeWidth={1.75} />} title={`Signed in to ${signIn.name}`} detail="Signed in here, in a browser" />;
    return (
        <Row
            icon={<Plug className={ROW_ICON} strokeWidth={1.75} />}
            title={signIn.name}
            detail={
                <>
                    Needs sign-in
                    {state.problem && <span className="block text-red-600 dark:text-red-400">{state.problem}</span>}
                </>
            }
            action={<ConnectSignIn state={state} />}
        />
    );
}

/** What else loses these secrets, in the platform's words from its delete preview, leaving out this agent itself
 *  (the preview names it as `The agent '<name>'`). */
async function alsoUsing(client: NoClick, gone: Secret[], self: string): Promise<string[]> {
    const lines = new Set<string>();
    for (const s of gone) {
        const { impact } = await previewDelete('DELETE', `/v1/secrets/${s.id}`, { client });
        for (const d of impact.dependsOnIt) if (!d.includes(`'${self}'`)) lines.add(d);
    }
    return [...lines];
}
