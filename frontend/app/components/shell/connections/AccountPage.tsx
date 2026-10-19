// One connected account, in full: proof it works in the provider's own words
// (your channels, your repositories), the automations that depend on it, who
// else can use it, and which of its actions wait for your approval. Rename,
// reconnect and delete live here too, so nothing about an account is two
// clicks away.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { ChevronRight, Loader2, LogOut, MoreHorizontal, Pencil, RotateCw, ShieldCheck, Trash2, UserPlus } from 'lucide-react';
import { CredentialDeleteDialog } from '~/components/credential/CredentialDeleteDialog';
import { verdictState } from '~/components/credential/ConnectionVerdict';
import type { WorkflowRef } from '~/components/dashboard/types';
import { CREDENTIALS_CHANGED_EVENT } from '~/components/shared/popups/CreateCredentialDialog';
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '~/components/ui/dropdown-menu';
import { Skeleton } from '~/components/ui/skeleton';
import { useConnectionProbe, type ConnectionProbe } from '~/hooks/useConnectionProbe';
import { leaveSharedCredential } from '~/lib/credentialAccess';
import { socketCall } from '~/lib/socketCall';
import { cn } from '~/lib/utils';
import type { ShareInfo } from '~/types/socket-events.generated';
import { PhoneBarBack, useInPhoneShell } from '../AppShell';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '../buttons';
import { ConfirmAction, Section, Surface, WorkflowChip } from '../resources/ui';
import { addedLabel } from './accountNames';
import type { ConnectedAccount } from './accounts';
import { AccountMark, reconnect, sourceLine } from './ConnectedList';
import { PAGE_TITLE } from '~/components/shell/titles';

const MENU_ITEM = 'gap-2.5 rounded-lg px-2.5 py-2 text-[14px]';

function Dot({ tone }: { tone: 'ok' | 'bad' | 'quiet' }) {
    return (
        <span
            aria-hidden
            className={cn('h-2 w-2 shrink-0 rounded-full', tone === 'ok' ? 'bg-emerald-500' : tone === 'bad' ? 'bg-red-500' : 'bg-muted-foreground/50')}
        />
    );
}

function ProofShell({ tone, title, children, className }: { tone: 'ok' | 'bad' | 'quiet'; title: string; children?: ReactNode; className?: string }) {
    return (
        <Surface className={cn('px-4 py-4 sm:px-5', className)}>
            <p className="flex items-center gap-2.5 text-[14px] font-medium text-foreground">
                <Dot tone={tone} />
                {title}
            </p>
            {children}
        </Surface>
    );
}

/** What the provider said when asked about this account. */
function Proof({ account, probe, canCheck, onReconnect }: { account: ConnectedAccount; probe?: ConnectionProbe; canCheck: boolean; onReconnect?: () => void }) {
    const provider = account.app;
    if (!canCheck) {
        return <p className="text-[14px] leading-relaxed text-muted-foreground">NoClick can’t ask {provider} about this account on its own. Each run that uses it checks it.</p>;
    }
    if (!probe || probe.status === 'checking') {
        return (
            <Surface className="flex items-center gap-2.5 px-4 py-4 text-[14px] text-muted-foreground sm:px-5">
                <Loader2 className="h-4 w-4 animate-spin" />
                Asking {provider}…
            </Surface>
        );
    }
    if (probe.status === 'failed') {
        return (
            <ProofShell tone="quiet" title="Couldn’t check just now">
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">The check itself didn’t go through, so this says nothing about the account. Try again in a minute.</p>
            </ProofShell>
        );
    }
    const result = probe.result;
    const state = verdictState(result);
    if (state === 'rejected') {
        return (
            <ProofShell tone="bad" title={`${provider} turned it down`} className="border-red-500/25 dark:border-red-500/25">
                {result.hint ? (
                    <>
                        <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">{result.hint}</p>
                        {result.error && (
                            <details className="group mt-2.5">
                                <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[12.5px] text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
                                    <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
                                    {provider}’s reply
                                </summary>
                                <p className="mt-2 break-words font-mono text-[12px] leading-relaxed text-red-600 dark:text-red-400">{result.error}</p>
                            </details>
                        )}
                    </>
                ) : (
                    result.error && <p className="mt-2 break-words font-mono text-[12px] leading-relaxed text-red-600 dark:text-red-400">{result.error}</p>
                )}
                {onReconnect && (
                    <button type="button" onClick={onReconnect} className={cn(BUTTON_PRIMARY, 'mt-4')}>
                        Reconnect
                    </button>
                )}
            </ProofShell>
        );
    }
    if (state === 'unverified') {
        return (
            <ProofShell tone="quiet" title="No clear answer">
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">{provider} didn’t confirm or refuse it just now. Automations still use it, and the next run will tell.</p>
            </ProofShell>
        );
    }
    const samples = result.samples ?? [];
    const more = result.total && result.total > samples.length ? result.total - samples.length : 0;
    return (
        <ProofShell tone="ok" title="Working">
            {samples.length > 0 ? (
                <>
                    <p className="mt-3 text-[12.5px] text-muted-foreground">Your {result.noun ?? 'items'}, as {provider} sees them</p>
                    <div className="mt-2 flex flex-wrap gap-1.5" data-testid="connection-evidence">
                        {samples.map((sample) => (
                            <span key={sample.value ?? sample.label} className="inline-flex h-7 max-w-full items-center truncate rounded-full bg-secondary px-3 text-[13px] text-foreground dark:bg-foreground/[0.07]">
                                {sample.label}
                            </span>
                        ))}
                        {more > 0 && <span className="inline-flex h-7 items-center px-1.5 text-[13px] text-muted-foreground">+{more} more</span>}
                    </div>
                    {result.account_label && <p className="mt-3 text-[12.5px] text-muted-foreground">Signed in as {result.account_label}</p>}
                </>
            ) : (
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">
                    {result.proves === 'reachability'
                        ? `${provider} accepted it. It has nothing account-specific to show.`
                        : result.account_label
                          ? `Signed in as ${result.account_label}.`
                          : `${provider} answered.`}
                </p>
            )}
        </ProofShell>
    );
}

function sharingLine(shares: ShareInfo[]): string {
    if (!shares.length) return 'Only you can use it.';
    const names = shares.map((s) =>
        s.target_type === 'organization' ? `everyone in ${s.target_org_name || 'your organization'}` : s.target_display_name || s.target_email || 'someone'
    );
    const listed = names.length > 3 ? [...names.slice(0, 2), `${names.length - 2} others`] : names;
    return `Shared with ${new Intl.ListFormat('en', { type: 'conjunction' }).format(listed)}.`;
}

function Access({ account, onLeft }: { account: ConnectedAccount; onLeft: () => void }) {
    const { credential } = account;
    const [shares, setShares] = useState<ShareInfo[] | 'failed' | null>(null);
    const [sharing, setSharing] = useState(false);
    const owner = account.source === 'connected';

    const load = () => {
        socketCall('share:list', { resource_type: 'credential', resource_id: credential.id })
            .then((data) => setShares((data.shares as ShareInfo[] | undefined) ?? []))
            .catch(() => setShares('failed'));
    };
    useEffect(() => {
        if (owner) load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [owner, credential.id]);

    if (!owner) {
        const sharer = credential.shared_by_name || credential.shared_by_email;
        return (
            <Section title="Access">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-[14px] leading-relaxed text-muted-foreground">
                        {account.source === 'organization'
                            ? 'It belongs to your organization, and its owner looks after it.'
                            : `${sharer ?? 'A teammate'} shared it with you${credential.shared_by_email && credential.shared_by_name ? ` (${credential.shared_by_email})` : ''}. They look after it.`}
                    </p>
                    {account.source === 'shared' && (
                        <ConfirmAction
                            label="Remove from my list"
                            confirm="Remove it"
                            icon={LogOut}
                            onConfirm={async () => {
                                try {
                                    await leaveSharedCredential(credential.id);
                                    toast.success(`Removed ${credential.name}`);
                                    onLeft();
                                } catch (err) {
                                    toast.error(err instanceof Error ? err.message : String(err));
                                }
                            }}
                        />
                    )}
                </div>
            </Section>
        );
    }
    return (
        <Section
            title="Access"
            action={
                <button type="button" onClick={() => setSharing(true)} className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                    <UserPlus className="h-3.5 w-3.5" />
                    Share
                </button>
            }
        >
            {shares === null ? (
                <Skeleton className="h-4 w-56" />
            ) : (
                <p className="text-[14px] leading-relaxed text-muted-foreground">{shares === 'failed' ? 'Couldn’t load who else can use it.' : sharingLine(shares)}</p>
            )}
            <ShareDialog
                isOpen={sharing}
                onOpenChange={(open) => {
                    if (open) return;
                    setSharing(false);
                    load();
                }}
                resource={{ id: credential.id, name: credential.name }}
                resourceType="credential"
            />
        </Section>
    );
}

function Title({ name, renaming, onRename, onDone }: { name: string; renaming: boolean; onRename: (next: string) => Promise<boolean>; onDone: () => void }) {
    const input = useRef<HTMLInputElement>(null);
    const [draft, setDraft] = useState(name);
    // Shown until the renamed account comes back from the list.
    const [pending, setPending] = useState<string | null>(null);
    const settled = useRef(false);
    useEffect(() => setPending(null), [name]);
    useEffect(() => {
        if (!renaming) return;
        settled.current = false;
        setDraft(name);
        requestAnimationFrame(() => {
            input.current?.focus();
            input.current?.select();
        });
    }, [renaming, name]);
    const title = cn('min-w-0', PAGE_TITLE);
    if (!renaming) return <h1 className={cn(title, 'break-words sm:truncate')}>{pending ?? name}</h1>;
    // Enter and the blur that follows it must save once.
    const finish = (save: boolean) => {
        if (settled.current) return;
        settled.current = true;
        const next = draft.trim();
        onDone();
        if (!save || !next || next === name) return;
        setPending(next);
        void onRename(next).then((ok) => !ok && setPending(null));
    };
    return (
        <input
            ref={input}
            value={draft}
            aria-label="Account name"
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => finish(true)}
            onKeyDown={(e) => {
                if (e.key === 'Enter') finish(true);
                if (e.key === 'Escape') finish(false);
            }}
            className={cn(title, '-mx-2 w-full rounded-lg bg-transparent px-2 outline-none ring-1 ring-inset ring-border focus:ring-foreground/30 sm:w-[min(100%,28rem)]')}
        />
    );
}

export function AccountPage({
    account,
    usedBy,
    backLabel,
    onBack,
    onGone,
}: {
    account: ConnectedAccount;
    usedBy?: WorkflowRef[];
    /** The list it was opened from. */
    backLabel: string;
    onBack: () => void;
    onGone: () => void;
}) {
    const { credential, app, problem } = account;
    const inPhone = useInPhoneShell();
    const owner = account.source === 'connected';
    const revoked = !!credential.revoked_at;
    // A revoked account can't be loaded at run time, so there's nothing to ask the provider.
    const { probe, check, canCheck } = useConnectionProbe(credential.id, revoked ? undefined : account.service?.value);
    const [renaming, setRenaming] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const rejected = probe?.status === 'done' && verdictState(probe.result) === 'rejected';

    const rename = async (name: string) => {
        try {
            await socketCall('credential:update', { credential_id: credential.id, name });
            window.dispatchEvent(new CustomEvent(CREDENTIALS_CHANGED_EVENT));
            return true;
        } catch (err) {
            toast.error(`Couldn’t rename: ${err instanceof Error ? err.message : String(err)}`);
            return false;
        }
    };
    // Choosing Rename closes the menu, which would hand focus back to its trigger and blur the new input.
    const renameChosen = useRef(false);

    const subtitle = [app, sourceLine(account), addedLabel(credential.created_at)].filter(Boolean).join(' · ');

    return (
        <div className="h-full overflow-y-auto scrollbar-subtle" data-testid="account-page">
            <div className="mx-auto w-full max-w-[860px] px-5 pb-24 pt-4 sm:px-8 sm:pt-8">
                {inPhone ? (
                    <PhoneBarBack label={backLabel} onBack={onBack} />
                ) : (
                    <nav aria-label="Breadcrumb" className="mb-6 flex items-center gap-1 text-[13px] text-muted-foreground">
                        <button type="button" onClick={onBack} className="rounded-md px-1 py-0.5 transition-colors hover:text-foreground">
                            Connections
                        </button>
                        <ChevronRight className="h-3.5 w-3.5 opacity-60" />
                        <button type="button" onClick={onBack} className="rounded-md px-1 py-0.5 transition-colors hover:text-foreground">
                            {backLabel}
                        </button>
                    </nav>
                )}

                <header className="flex flex-wrap items-start gap-4">
                    <AccountMark credential={credential} size="lg" />
                    <div className="min-w-0 flex-1">
                        <Title name={credential.name} renaming={renaming} onRename={rename} onDone={() => setRenaming(false)} />
                        <p className="mt-1 text-[14px] leading-snug text-muted-foreground sm:truncate">{subtitle}</p>
                    </div>
                    <div className="flex items-center gap-2">
                        {owner && !problem && !rejected && (
                            <button type="button" onClick={() => reconnect(credential)} className={BUTTON_SECONDARY}>
                                Reconnect
                            </button>
                        )}
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <button
                                    type="button"
                                    aria-label={`More for ${credential.name}`}
                                    className="grid h-9 w-9 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-foreground data-[state=open]:bg-foreground/[0.06] data-[state=open]:text-foreground"
                                >
                                    <MoreHorizontal className="h-[18px] w-[18px]" />
                                </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                                align="end"
                                sideOffset={6}
                                className="min-w-[210px] rounded-xl p-1"
                                onCloseAutoFocus={(event) => {
                                    if (!renameChosen.current) return;
                                    renameChosen.current = false;
                                    event.preventDefault();
                                }}
                            >
                                {owner && (
                                    <DropdownMenuItem
                                        onSelect={() => {
                                            renameChosen.current = true;
                                            setRenaming(true);
                                        }}
                                        className={MENU_ITEM}
                                    >
                                        <Pencil className="h-4 w-4 text-muted-foreground" />
                                        Rename
                                    </DropdownMenuItem>
                                )}
                                <DropdownMenuItem asChild className={MENU_ITEM}>
                                    <Link to={`/credential/permissions/${credential.id}`}>
                                        <ShieldCheck className="h-4 w-4 text-muted-foreground" />
                                        Approvals
                                    </Link>
                                </DropdownMenuItem>
                                {owner && (
                                    <>
                                        <DropdownMenuSeparator />
                                        <DropdownMenuItem
                                            onSelect={() => setDeleting(true)}
                                            className={cn(MENU_ITEM, 'text-red-600 focus:bg-red-500/10 focus:text-red-600 dark:text-red-400 dark:focus:text-red-400')}
                                        >
                                            <Trash2 className="h-4 w-4" />
                                            Delete account
                                        </DropdownMenuItem>
                                    </>
                                )}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                </header>

                {problem && (
                    <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-3 rounded-2xl border border-red-500/20 bg-red-500/[0.04] px-4 py-3.5 sm:px-5">
                        <div className="min-w-0 flex-1">
                            <p className="text-[14px] font-medium text-foreground">{problem}</p>
                            <p className="mt-0.5 text-[13.5px] text-muted-foreground">
                                {owner ? 'Automations that use it stop at this step until it’s reconnected.' : 'Its owner has to reconnect it.'}
                            </p>
                        </div>
                        {owner && (
                            <button type="button" onClick={() => reconnect(credential)} className={BUTTON_PRIMARY}>
                                Reconnect
                            </button>
                        )}
                    </div>
                )}

                {!revoked && (
                    <Section
                        title="Connection"
                        action={
                            canCheck && probe && probe.status !== 'checking' ? (
                                <button type="button" onClick={check} className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                                    <RotateCw className="h-3.5 w-3.5" />
                                    Check again
                                </button>
                            ) : undefined
                        }
                    >
                        <Proof account={account} probe={probe} canCheck={canCheck} onReconnect={owner && rejected && !problem ? () => reconnect(credential) : undefined} />
                    </Section>
                )}

                <Section title="Used by" meta={usedBy?.length || undefined}>
                    {!usedBy ? (
                        <div className="flex gap-2">
                            <Skeleton className="h-9 w-40 rounded-full" />
                            <Skeleton className="h-9 w-32 rounded-full" />
                        </div>
                    ) : usedBy.length ? (
                        <div className="flex flex-wrap gap-2">
                            {usedBy.map((workflow) => (
                                <WorkflowChip key={workflow.id} workflow={workflow} />
                            ))}
                        </div>
                    ) : (
                        <p className="text-[14px] text-muted-foreground">No automation uses it yet.</p>
                    )}
                </Section>

                <Access account={account} onLeft={onGone} />

                <Section title="Approvals">
                    <Link
                        to={`/credential/permissions/${credential.id}`}
                        className="group flex items-center gap-3.5 rounded-2xl border border-border px-4 py-3.5 transition-colors hover:bg-foreground/[0.025] dark:border-foreground/[0.08] sm:px-5"
                    >
                        <ShieldCheck className="h-[18px] w-[18px] shrink-0 text-muted-foreground" strokeWidth={1.75} />
                        <span className="min-w-0 flex-1 text-[14px] leading-snug text-foreground/90">Choose which of its actions wait for your OK before an agent takes them.</span>
                        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-colors group-hover:text-foreground" />
                    </Link>
                </Section>
            </div>

            <CredentialDeleteDialog credential={deleting ? { id: credential.id, name: credential.name } : null} onClose={() => setDeleting(false)} onDeleted={onGone} />
        </div>
    );
}
