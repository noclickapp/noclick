// Connecting an AI company, in a dialog opened from its Connections tile (or wherever a pick needs an AI account, as
// Work's model picker does), through the same connect flow every app uses (AiConnect over ConnectApp): a switch between
// its subscription sign-ins and its API key, the key as two steps (open the company's console, then paste it), the
// accounts you already have with it, and asking someone who can. The agent node's credential panel runs the same
// flow, so an account added here is the one an agent picks up.
import { useCallback, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { CREDENTIALS_CHANGED_EVENT } from '~/components/shared/popups/CreateCredentialDialog';
import { connectDialogHeader, type ConnectAccountRow } from '~/components/credential/connect/ConnectApp';
import type { AskSignIn } from '~/components/workflow/CredentialRequestActions';
import { signInForKey } from '~/lib/agentCredentialModel';
import { invalidateCredentialsCache } from '~/utils/credentialAutoSelect';
import { ShellDialog } from '../ShellDialog';
import { companyAccountRow } from './accountNames';
import type { ConnectedAccount } from './accounts';
import { AiConnect, companyMethods } from './AiConnect';
import { AiMark, type AiCompany } from './aiAccounts';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { cn } from '~/lib/utils';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { sourceLine } from './ConnectedList';

// A sign-in here attaches to no node: the account is just added, and the map it reports holds only what landed.
const NO_CREDENTIALS: Record<string, string> = {};

/** Another way to run what the dialog connects for ("Or run it on"): its name, the credential type its mark is, and
 *  what picking it does (the host shows that way instead). */
export interface OtherWay {
    key: string;
    label: string;
    credentialType: string;
    onPick: () => void;
}

const OTHER_WAY =
    'inline-flex h-11 items-center gap-2.5 rounded-full bg-foreground/[0.05] pl-1.5 pr-4 text-[14px] font-medium text-foreground/90 ring-1 ring-inset ring-foreground/[0.07] transition-colors hover:bg-foreground/[0.09] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';

/** A credential type's mark, coloured where its brand is, else in the ink around it. */
function TypeMark({ type, className }: { type: string; className: string }) {
    const icon = getCredentialIcon(type);
    return <BrandIcon Icon={icon.Icon} iconColor={icon.iconColor || 'text-current'} className={cn('shrink-0', className)} />;
}

/** Asking someone for the company's key: its link offers the company's plan beside the key where the plan holds the
 *  same account. */
function askFor(company: AiCompany, credentialType: string): { credentialType: string; signIn?: AskSignIn } {
    const plan = signInForKey(credentialType);
    return { credentialType, signIn: plan && company.signIns.includes(plan) ? { agentOAuthType: plan } : undefined };
}

/** An account in the company's list: what it is (its email, login or the name you gave it; else its plan or "API
 *  key") and, under it, what's wrong, whose it is, or when it was added. */
function accountRow(account: ConnectedAccount): ConnectAccountRow {
    const { title, meta: kind } = companyAccountRow(account.credential, account.line);
    return { id: account.credential.id, title, meta: [kind, sourceLine(account)].filter(Boolean).join(' · '), problem: account.problem };
}

export function AiProviderDialog({
    company,
    accounts = [],
    only,
    title,
    description,
    others = [],
    onOpenChange,
    onOpenAccount,
    onConnected,
}: {
    /** The company to connect; null closes the dialog. */
    company: AiCompany | null;
    /** Every account you can use; the dialog lists the company's. Left out where the host lists them itself. */
    accounts?: ConnectedAccount[];
    /** The one way in to show (a sign-in's or a key's credential type), where the host knows which it's for; the
     *  company's every one, as tabs, when left out. Its mark leads the title. */
    only?: string;
    /** In place of the company's name and what it runs, where the host says what it's for ("Connect Claude"). */
    title?: string;
    description?: string;
    /** The other ways that run what it's for, as "Or run it on" pills under it. */
    others?: OtherWay[];
    onOpenChange: (open: boolean) => void;
    onOpenAccount?: (credentialId: string) => void;
    /** The account that landed, by its credential's id: a sign-in's or a saved key's. */
    onConnected?: (credentialId: string) => void;
}) {
    // The last company stays on screen while the dialog animates closed.
    const [shown, setShown] = useState(company);
    if (company && company !== shown) setShown(company);
    const [asking, setAsking] = useState(false);
    // An AI key has no account to show for itself, so the dialog closes on a landed one, as it always has.
    const connected = useCallback(async () => {
        if (!shown) return;
        invalidateCredentialsCache();
        window.dispatchEvent(new CustomEvent(CREDENTIALS_CHANGED_EVENT));
        toast.success(`${shown.title} connected`);
        onOpenChange(false);
    }, [shown, onOpenChange]);
    const methods = useMemo(() => (shown ? companyMethods(shown, only) : []), [shown, only]);
    const own = shown ? accounts.filter((a) => shown.credentialTypes.includes(a.credential.credential_type)) : [];
    // Asking someone reads as every connect dialog's ask does; otherwise what the host says it's for, or the company's
    // own name and what it runs.
    const header = shown && (asking ? connectDialogHeader(shown.title, 'ask') : { title: title ?? shown.title, description: title ? description : shown.uses });

    return (
        <ShellDialog
            open={!!company}
            onOpenChange={(open) => {
                onOpenChange(open);
                if (!open) setAsking(false);
            }}
            title={header?.title}
            description={header?.description}
            mark={shown && (only ? <TypeMark type={only} className="h-[22px] w-[22px]" /> : <AiMark provider={shown.members[0]} size="lg" />)}
            markTile={!!only}
            size="sm"
            testId="ai-provider-dialog"
        >
            {shown && methods.length > 0 && (
                <AiConnect
                    key={shown.id}
                    app={shown.title}
                    methods={methods}
                    credentialIds={NO_CREDENTIALS}
                    onCredentialIdsChange={(ids) => {
                        const landed = Object.values(ids)[0];
                        if (landed) onConnected?.(landed);
                    }}
                    onSignedIn={connected}
                    onKeySaved={async (credential) => {
                        onConnected?.(credential.id);
                        await connected();
                    }}
                    accounts={own.map(accountRow)}
                    onOpenAccount={onOpenAccount}
                    ask={askFor(shown, methods[methods.length - 1].credential_type)}
                    onStage={(stage) => setAsking(stage === 'ask')}
                />
            )}
            {others.length > 0 && !asking && (
                <div role="group" aria-label="Or run it on" className="border-t border-border pb-6 pt-5 dark:border-foreground/[0.08]">
                    <p className="text-center text-[13px] text-muted-foreground">Or run it on</p>
                    <div className="mt-3 flex flex-wrap justify-center gap-2">
                        {others.map((way) => (
                            <button key={way.key} type="button" onClick={way.onPick} className={OTHER_WAY}>
                                <span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-background ring-1 ring-inset ring-foreground/[0.08] dark:bg-foreground/[0.08]">
                                    <TypeMark type={way.credentialType} className="h-4 w-4" />
                                </span>
                                {way.label}
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </ShellDialog>
    );
}
