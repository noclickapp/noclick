// Connecting an app: a switch between its ways in (a sign-in before a key), a key as two steps (get it from the
// provider, then paste it here), the accounts already connected, and asking someone who has the account instead.
// Every word comes from the credential schema through ~/utils/credentialCopy, so it reads the same for every provider.
// It is presentational: a host draws each way in with the real connect form over its own engine (`renderMethod`), the
// in-app socket (AppConnect) or a provide link (CredentialProvideFlow), and hears when one lands. /connect-design-lab
// shows it against the dialog it replaced.
import { Fragment, useEffect, useRef, useState, type ReactNode } from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { ArrowUpRight, ChevronRight } from 'lucide-react';
import { ConnectionVerdict } from '~/components/credential/ConnectionVerdict';
import type { ProvideCredentialMethod } from '~/components/credential/CredentialMethodConnect';
import { BUTTON_PRIMARY, BUTTON_SECONDARY } from '~/components/shell/buttons';
import { AskSomeoneForm, INLINE_ACTION, type AskTransport } from '~/components/workflow/CredentialRequestActions';
import { kindFromBackendMethod, type CredentialMethodKind } from '~/lib/credentialMethodKind';
import { cn } from '~/lib/utils';
import { copyMethodOf, keyNoun, methodCopy, sourceLink, withArticle, type MethodCopy } from '~/utils/credentialCopy';
import type { ConnectResult, ConnectStage } from './connectHeader';
import { FinalStep, Step } from './steps';

export { connectDialogHeader, type ConnectResult, type ConnectStage } from './connectHeader';

/** An account already connected, as a row: who it is, and what kind or whose. */
export interface ConnectAccountRow {
    id: string;
    title: string;
    meta?: string;
    problem?: string;
}

export interface ConnectMethodContext {
    /** Tell the dialog the account landed. */
    onConnected: (result: Omit<ConnectResult, 'kind'>) => void;
    /** Show where each value comes from at its field (false where the first step already links it). */
    showSources: boolean;
    /** The steps to get the value, shown above the form (for the form's `instructions`). */
    howTo: string | null;
    /** The line under a sign-in's button (for OAuthConnectForm's `note`): where it goes, and that NoClick never sees
     *  the password. */
    note: string | null;
}

export interface ConnectAppProps {
    /** The app, as the catalog names it: "Notion". */
    app: string;
    methods: ProvideCredentialMethod[];
    /** Who a sign-in goes through, when not the app itself (Gmail signs in with Google). */
    providerName?: (method: ProvideCredentialMethod) => string;
    /** Draws a way in: the real connect form (OAuthConnectForm, CredentialCreatePanel, a QR code). */
    renderMethod: (method: ProvideCredentialMethod, ctx: ConnectMethodContext) => ReactNode;
    accounts?: ConnectAccountRow[];
    onOpenAccount?: (id: string) => void;
    /** A broken account's way back, as its Connections tile offers it. */
    onReconnectAccount?: (id: string) => void;
    /** Asking someone else; omitted, nothing offers it (the provide page is someone else already). */
    ask?: { credentialType: string; send?: AskTransport; email?: string };
    /** Hears an account land. */
    onConnected?: (result: ConnectResult) => void;
    /** False where the host shows what landed itself (the node panel's picker, the provide page's own last step). */
    showResult?: boolean;
    /** The dialog's header follows the stage (`connectDialogHeader`). */
    onStage?: (stage: ConnectStage, result?: ConnectResult) => void;
    onDone?: () => void;
    /** Where to open: a way in (reconnecting one kind of account), or a stage for the lab's states. */
    initial?: { method?: string; stage?: ConnectStage; result?: ConnectResult };
}

interface Way {
    method: ProvideCredentialMethod;
    kind: CredentialMethodKind;
    copy: MethodCopy;
}

const isSignIn = (kind: CredentialMethodKind) => kind === 'oauth' || kind === 'agent_oauth';

/** A way in as a tab: "Sign in" (a plan's name when there are several), the key's own noun, "QR code". */
function tabLabel(way: Way, ways: Way[], app: string): string {
    if (isSignIn(way.kind)) {
        if (ways.filter((w) => isSignIn(w.kind)).length < 2) return 'Sign in';
        // "Instagram with Facebook Login" is the Facebook sign-in: the app's own name is the dialog's already.
        const through = way.method.label.replace(new RegExp(`^${app.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s+with\\s+`, 'i'), '');
        return through.charAt(0).toUpperCase() + through.slice(1);
    }
    if (way.kind === 'qr_scan') return 'QR code';
    if (way.kind === 'purchase') return 'Buy a number';
    return keyNoun(copyMethodOf(way.method), app);
}

// "Internal integration token" → "internal integration token"; "API key" and brands stay.
const lowerName = (name: string) => (/^[A-Z][a-z]/.test(name) && !/^[A-Z][a-z]+[A-Z]/.test(name) ? name.charAt(0).toLowerCase() + name.slice(1) : name);

export function ConnectApp({
    app,
    methods,
    providerName,
    renderMethod,
    accounts = [],
    onOpenAccount,
    onReconnectAccount,
    ask,
    onConnected,
    showResult = true,
    onStage,
    onDone,
    initial,
}: ConnectAppProps) {
    const ways: Way[] = methods.map((method) => ({
        method,
        kind: kindFromBackendMethod(method),
        copy: methodCopy(copyMethodOf(method), app, providerName?.(method) ?? app),
    }));
    const [chosen, setChosen] = useState(initial?.method ?? ways[0]?.method.credential_type);
    const [stage, setStageState] = useState<ConnectStage>(initial?.stage ?? 'connect');
    const [result, setResult] = useState<ConnectResult | undefined>(initial?.result);
    const way = ways.find((w) => w.method.credential_type === chosen) ?? ways[0];

    // A new stage takes focus to its first control, so it never drops to the dialog behind it.
    const stageRef = useRef<HTMLDivElement>(null);
    const shownStage = useRef(stage);
    useEffect(() => {
        if (shownStage.current === stage) return;
        shownStage.current = stage;
        stageRef.current?.querySelector<HTMLElement>('input, textarea, select, button, [href]')?.focus();
    }, [stage]);

    const setStage = (next: ConnectStage, landed?: ConnectResult) => {
        setStageState(next);
        onStage?.(next, landed);
    };
    const ctx = (w: Way, showSources = true): ConnectMethodContext => ({
        showSources,
        howTo: w.copy.howTo,
        note: w.kind === 'oauth' ? w.copy.line : null,
        onConnected: (r) => {
            const landed = { ...r, kind: w.kind, credentialType: r.credentialType ?? w.method.credential_type };
            setResult(landed);
            onConnected?.(landed);
            if (showResult) setStage('done', landed);
        },
    });

    if (!way) return null;

    if (stage === 'done' && result) {
        return (
            <div ref={stageRef} className="space-y-6 pb-5 pt-1">
                {/* A sign-in proves as little as a pasted key until the connect-time check has asked the provider. */}
                <ConnectionVerdict providerLabel={app} verification={result.verification} accountLine={result.account} />
                <button type="button" onClick={onDone} className={cn(BUTTON_PRIMARY, 'h-10 w-full justify-center')}>
                    Done
                </button>
            </div>
        );
    }

    if (stage === 'ask' && ask) {
        return (
            <div ref={stageRef} className="space-y-5 pb-5 pt-1">
                <AskSomeoneForm credentialType={ask.credentialType} app={app} send={ask.send} initialEmail={ask.email} />
                <button type="button" onClick={() => setStage('connect')} className={INLINE_ACTION}>
                    Connect it yourself instead
                </button>
            </div>
        );
    }

    const body = (
        <Fragment key={way.method.credential_type}>
            {way.kind === 'api_key' ? (
                <KeySteps method={way.method} app={app}>
                    {renderMethod(way.method, ctx(way, false))}
                </KeySteps>
            ) : (
                <div>{renderMethod(way.method, ctx(way))}</div>
            )}
        </Fragment>
    );

    return (
        <div ref={stageRef} className="space-y-6 pb-5 pt-1" data-testid="connect-app">
            {ways.length > 1 ? (
                // Real tabs (arrow keys, one stop in the tab order, a panel per way in). Four or more sit two to a row,
                // and a name too long for a phone wraps rather than being cut off.
                <TabsPrimitive.Root value={way.method.credential_type} onValueChange={setChosen} className="space-y-6">
                    <TabsPrimitive.List
                        aria-label={`How to connect ${app}`}
                        className={cn('bg-secondary p-1 dark:bg-foreground/[0.06]', ways.length > 3 ? 'grid grid-cols-2 gap-1' : 'flex', 'rounded-[20px]')}
                    >
                        {ways.map((w) => (
                            <TabsPrimitive.Trigger
                                key={w.method.credential_type}
                                value={w.method.credential_type}
                                className={cn(
                                    'min-h-8 min-w-0 flex-1 rounded-full px-3 py-1 text-[13px] leading-tight [text-wrap:balance] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                                    'text-muted-foreground hover:text-foreground data-[state=active]:bg-background data-[state=active]:font-medium data-[state=active]:text-foreground data-[state=active]:shadow-sm dark:data-[state=active]:bg-foreground/[0.12]'
                                )}
                            >
                                {tabLabel(w, ways, app)}
                            </TabsPrimitive.Trigger>
                        ))}
                    </TabsPrimitive.List>
                    <TabsPrimitive.Content value={way.method.credential_type} className="focus-visible:outline-none">
                        {body}
                    </TabsPrimitive.Content>
                </TabsPrimitive.Root>
            ) : (
                body
            )}
            {accounts.length > 0 && <AccountList accounts={accounts} onOpen={onOpenAccount} onReconnect={onReconnectAccount} app={app} />}
            {ask && (
                <p className="text-[13px] text-muted-foreground">
                    Not yours to connect?{' '}
                    <button type="button" onClick={() => setStage('ask')} className={INLINE_ACTION}>
                        Ask someone who can
                    </button>
                </p>
            )}
        </div>
    );
}

/** A key as steps: get it from the provider (its steps, and a button to its page), paste it here, then Connect, the
 *  form's own button. With nothing to say about getting it, the form stands alone. Every surface that draws a key's form
 *  shows it, the connect flow and the coordinator's connect card alike. */
export function KeySteps({ method, app, children }: { method: ProvideCredentialMethod; app: string; children: ReactNode }) {
    const copy = copyMethodOf(method);
    const { name, howTo } = methodCopy(copy, app);
    const source = sourceLink(copy);
    if (!howTo && !source) return <div>{children}</div>;
    return (
        <ol className="space-y-6">
            <Step n={1} title={`Get ${withArticle(lowerName(name))}`}>
                {howTo && <p className="text-[13.5px] leading-relaxed text-muted-foreground">{howTo}</p>}
                {source && (
                    <a href={source.href} target="_blank" rel="noopener noreferrer" className={cn(BUTTON_SECONDARY, howTo && 'mt-3')}>
                        Open {source.host}
                        <ArrowUpRight className="h-3.5 w-3.5" />
                    </a>
                )}
            </Step>
            <Step n={2} title="Paste it here">
                <FinalStep.Provider value={3}>{children}</FinalStep.Provider>
            </Step>
        </ol>
    );
}

/** The accounts already connected: who each is, and what's wrong with a broken one (in full, never cut off) beside its
 *  way back. */
function AccountList({ accounts, onOpen, onReconnect, app }: { accounts: ConnectAccountRow[]; onOpen?: (id: string) => void; onReconnect?: (id: string) => void; app: string }) {
    return (
        <section aria-label={`Your ${app} accounts`} className="border-t border-border pt-4 dark:border-foreground/[0.08]">
            <h3 className="mb-1 text-[13px] text-muted-foreground">Already connected</h3>
            {accounts.map((account) => {
                const broken = !!account.problem && !!onReconnect;
                const text = (
                    <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] text-foreground">{account.title}</span>
                        {(account.problem || account.meta) && (
                            <span className={cn('mt-0.5 block text-[12.5px] leading-snug', account.problem ? 'line-clamp-2 text-red-600 dark:text-red-400' : 'truncate text-muted-foreground')}>
                                {account.problem ?? account.meta}
                            </span>
                        )}
                    </span>
                );
                return (
                    <div key={account.id} className={cn('-mx-3 flex w-[calc(100%+1.5rem)] items-center gap-2 rounded-xl px-3', onOpen && 'transition-colors hover:bg-foreground/[0.04]')}>
                        {onOpen ? (
                            <button type="button" onClick={() => onOpen(account.id)} className="group flex min-w-0 flex-1 items-center gap-3 rounded-lg py-2.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                                {text}
                                {!broken && <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-colors group-hover:text-foreground" />}
                            </button>
                        ) : (
                            <div className="flex min-w-0 flex-1 py-2.5">{text}</div>
                        )}
                        {broken && (
                            <button type="button" onClick={() => onReconnect?.(account.id)} className={cn(BUTTON_SECONDARY, 'h-8 px-3.5 text-[13px]')}>
                                Reconnect
                            </button>
                        )}
                    </div>
                );
            })}
        </section>
    );
}

