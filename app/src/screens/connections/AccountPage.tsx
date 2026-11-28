// One connected account, in full: proof it works in the provider's own words (your channels, your repositories), what a
// host adds after it (a WhatsApp number's agent), a website login's own mail (LoginMail.tsx), the automations that
// depend on it, who else can use it, and which of
// its actions wait for your approval. Rename, reconnect and delete live here too, so nothing about an account is two
// clicks away. One an agent's move from a computer brought over says so, with a Remove that takes its access away
// everywhere. What the page can do with an account comes with it (model.ts): an account the platform API lists is
// checked, renamed and deleted through its connection.
import { useContext, useRef, useState, type ComponentProps } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { ChevronRight, MoreHorizontal, Pencil, RotateCw, ShieldCheck, Trash2 } from 'lucide-react';
import { useSlot } from '@/slots';
import { checkVerdict } from '@/lib/connectionCheck';
import { openTabForLater } from '@/lib/oauthPopup';
import { addedLabel } from '@/lib/formatters';
import { movedFrom, movedLine } from '@/lib/movedFrom';
import { ConsoleContext } from '@/screens/console/hooks/useConsole';
import { accountApprovalsUrl, NOCLICK_SITE, workflowUrl } from '@/screens/console/lib/site';
import { useOwnerOnly } from '@/screens/console/ownerOnly';
import { Section, WorkflowChip } from '@/screens/resources/ui';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '@/ui/buttons';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/ui/dropdown-menu';
import { PhoneBarBack, useInPhoneShell } from '@/ui/phoneBar';
import { Skeleton } from '@/ui/skeleton';
import { cn } from '@/ui/utils';
import { AccountTitle, Moved } from './AccountParts';
import { AccountMark, sourceLine } from './ConnectedList';
import { useConnectionsContext } from './context';
import { ConnectionDeleteDialog } from './DeleteDialog';
import { LoginMail, WEBSITE_LOGIN } from './LoginMail';
import type { ConnectedAccount } from './model';
import { useConnectionProbe } from './probe';
import { Proof } from './Proof';
import { ACCOUNT_ACCESS, ACCOUNT_MORE } from './slots';

const MENU_ITEM = 'gap-2.5 rounded-lg px-2.5 py-2 text-[14px]';

/** Where the account's approvals are chosen: in this app for its signed-in owner, on NoClick's own page (a new tab) for
 *  a key, which can't lift one. Whatever else it's given (a menu item's own props and ref) goes on the link. */
function ApprovalsLink({ accountId, ...link }: { accountId: string } & Omit<ComponentProps<'a'>, 'href'>) {
    const site = useContext(ConsoleContext)?.site ?? NOCLICK_SITE;
    const href = accountApprovalsUrl(site, accountId);
    const inApp = useOwnerOnly()('connectionApprovals');
    return inApp ? <Link to={href} {...link} /> : <a href={href} target="_blank" rel="noopener noreferrer" {...link} />;
}

export function AccountPage({
    account,
    backLabel,
    onBack,
    onGone,
}: {
    account: ConnectedAccount;
    /** The list it was opened from. */
    backLabel: string;
    onBack: () => void;
    onGone: () => void;
}) {
    const { credential, app, problem, usedBy } = account;
    const inPhone = useInPhoneShell();
    const { changed, openWorkflow } = useConnectionsContext();
    const site = useContext(ConsoleContext)?.site ?? NOCLICK_SITE;
    const Access = useSlot(ACCOUNT_ACCESS);
    const More = useSlot(ACCOUNT_MORE);
    const owner = account.source === 'connected';
    const revoked = !!credential.revoked_at;
    // A revoked account can't be loaded at run time, so there's nothing to ask the provider.
    const { probe, check, canCheck } = useConnectionProbe(credential.id, revoked ? undefined : account.check);
    const [renaming, setRenaming] = useState(false);
    // Deleting from the menu, or removing a moved one from its Moved here section.
    const [deleting, setDeleting] = useState<'delete' | 'remove' | null>(null);
    const rejected = probe?.status === 'done' && checkVerdict(probe.result) === 'rejected';
    const moved = movedFrom(credential.metadata?.moved_from);
    const reconnect = owner ? account.reconnect : undefined;
    const { rename: renameIt, deletes } = account;

    const rename = async (name: string) => {
        if (!renameIt) return false;
        try {
            await renameIt(name);
            changed?.({ accountId: credential.id });
            return true;
        } catch (err) {
            toast.error(`Couldn’t rename: ${err instanceof Error ? err.message : String(err)}`);
            return false;
        }
    };
    // Choosing Rename closes the menu, which would hand focus back to its trigger and blur the new input.
    const renameChosen = useRef(false);
    const open = openWorkflow ?? ((workflow: { id: string }) => void openTabForLater({ url: workflowUrl(site, workflow.id) }));

    const subtitle = [app, sourceLine(account), moved ? movedLine(moved) : addedLabel(credential.created_at)].filter(Boolean).join(' · ');

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
                        <AccountTitle name={credential.name} renaming={renaming} onRename={rename} onDone={() => setRenaming(false)} />
                        <p className="mt-1 text-[14px] leading-snug text-muted-foreground sm:truncate">{subtitle}</p>
                    </div>
                    <div className="flex items-center gap-2">
                        {reconnect && !problem && !rejected && (
                            <button type="button" onClick={reconnect} className={BUTTON_SECONDARY}>
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
                                {owner && renameIt && (
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
                                    <ApprovalsLink accountId={credential.id}>
                                        <ShieldCheck className="h-4 w-4 text-muted-foreground" />
                                        Approvals
                                    </ApprovalsLink>
                                </DropdownMenuItem>
                                {owner && deletes && (
                                    <>
                                        <DropdownMenuSeparator />
                                        <DropdownMenuItem
                                            onSelect={() => setDeleting('delete')}
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
                        {reconnect && (
                            <button type="button" onClick={reconnect} className={BUTTON_PRIMARY}>
                                Reconnect
                            </button>
                        )}
                    </div>
                )}

                {moved && <Moved moved={moved} owner={owner && !!deletes} onRemove={() => setDeleting('remove')} />}

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
                        <Proof provider={app} probe={probe} canCheck={canCheck} onReconnect={reconnect && rejected && !problem ? reconnect : undefined} />
                    </Section>
                )}

                <More account={account} />

                {account.connection?.integration === WEBSITE_LOGIN && !revoked && <LoginMail connection={account.connection} />}

                <Section title="Used by" meta={usedBy?.length || undefined}>
                    {!usedBy ? (
                        <div className="flex gap-2">
                            <Skeleton className="h-9 w-40 rounded-full" />
                            <Skeleton className="h-9 w-32 rounded-full" />
                        </div>
                    ) : usedBy.length ? (
                        <div className="flex flex-wrap gap-2">
                            {usedBy.map((workflow) => (
                                <WorkflowChip key={workflow.id} workflow={workflow} onOpen={open} />
                            ))}
                        </div>
                    ) : (
                        <p className="text-[14px] text-muted-foreground">No automation uses it yet.</p>
                    )}
                </Section>

                <Access account={account} onLeft={onGone} />

                <Section title="Approvals">
                    <ApprovalsLink
                        accountId={credential.id}
                        className="group flex items-center gap-3.5 rounded-2xl border border-border px-4 py-3.5 transition-colors hover:bg-foreground/[0.025] dark:border-foreground/[0.08] sm:px-5"
                    >
                        <ShieldCheck className="h-[18px] w-[18px] shrink-0 text-muted-foreground" strokeWidth={1.75} />
                        <span className="min-w-0 flex-1 text-[14px] leading-snug text-foreground/90">Choose which of its actions wait for your OK before an agent takes them.</span>
                        <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-colors group-hover:text-foreground" />
                    </ApprovalsLink>
                </Section>
            </div>

            {deletes && (
                <ConnectionDeleteDialog
                    account={deleting ? { id: credential.id, name: credential.name } : null}
                    through={deletes}
                    removing={deleting === 'remove'}
                    onClose={() => setDeleting(null)}
                    onDeleted={() => {
                        changed?.({ accountId: credential.id, deleted: true });
                        onGone();
                    }}
                />
            )}
        </div>
    );
}
