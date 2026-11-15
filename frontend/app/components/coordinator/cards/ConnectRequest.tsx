// The accounts the coordinator asked to connect, each run on its own credential request. A row's button connects it over
// the request's token: a sign-in straight from the row, through the request's own OAuth exchange; anything that needs
// more (a key, a QR code, a sign-in that asks for something first) in the Connections dialog, drawn over the same
// request. So a key is judged by the same connect seam, and the fulfilled request wakes the coordinator exactly as its
// link does. Loaded on demand: it carries every provider's sign-in.
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { PILL_PRIMARY, PILL_QUIET, PILL_SECONDARY, Row } from '~/components/coordinator/inline/primitives';
import { ConnectAccountsCard, ConnectedRow, ConnectedSummary, connectRowId, retriesRead, unavailableLine, type ConnectedAccount } from '~/components/coordinator/inline/setup';
import type { ConnectAsk } from '~/components/coordinator/toolCardRegistry';
import { ConnectApp, connectDialogHeader, type ConnectResult, type ConnectStage } from '~/components/credential/connect/ConnectApp';
import { CredentialMethodConnect, type ProvideCredentialMethod } from '~/components/credential/CredentialMethodConnect';
import { signsInOnlyInApp, useCredentialRequest } from '~/components/credential/CredentialProvideFlow';
import { wayInRank } from '~/components/credential/credentialMethods';
import { oauthCredentialName, signsInInOneTap } from '~/components/credential/OAuthConnectForm';
import { ProvideLinkOAuth } from '~/components/credential/RedirectOAuthProvideMethod';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { ShellDialog } from '~/components/shell/ShellDialog';
import { INLINE_ACTION, type AskTransport } from '~/components/workflow/CredentialRequestActions';
import { useInstanceOAuthApp } from '~/hooks/useInstanceOAuthApp';
import { kindFromBackendMethod, type CredentialMethodKind } from '~/lib/credentialMethodKind';
import { isLocalEdition } from '~/lib/edition';
import { apiBaseUrl } from '~/lib/hostedDefaults';
import { navigateToSettings, navigateToTab } from '~/lib/navigation';
import { sendEventAsync } from '~/lib/socket-sender';
import { cn } from '~/lib/utils';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { copyMethodOf, methodName } from '~/utils/credentialCopy';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { getProviderConfig, getProviderConfigByCredentialType } from '~/utils/oauthProviders';

// Where accounts are connected: the shell's Connections page, or Settings → Credentials in the open edition's tabs.
const CONNECTIONS = isLocalEdition()
    ? { place: 'Settings → Credentials', open: () => navigateToSettings({ section: 'credentials' }) }
    : { place: 'Connections', open: () => navigateToTab('connections') };

/** An account a turn asked to connect, as the card draws it. */
export interface RequestedAccount {
    ask: ConnectAsk;
    token: string;
    name: string;
    mark: ReactNode;
    /** In already: here, elsewhere, or before a reload. */
    done?: ConnectedAccount;
}

/** What the dialog opens on: an account, the ways in its request offers, and the one shown first. */
interface Opened {
    account: RequestedAccount;
    methods: ProvideCredentialMethod[];
    method: string;
}

interface RowProps {
    account: RequestedAccount;
    onOpen: (opened: Opened) => void;
    onProvided: (id: string, verification?: CredentialTestConnectionResponse | null) => void;
    /** The request was already fulfilled (here before a reload, through another way in, or by a re-scan that repaired
     *  an existing account): the credential it made. */
    onFulfilled: (id: string, credentialId?: string) => void;
    /** Read the request again: after a failed read, or when a save finds it gone, ended or out of tries. */
    onRetry: (id: string) => void;
    /** Where its plan sign-ins are offered instead (PlanConnectCard). */
    onPlan?: () => void;
}

// What a row's button says for a way in that opens the dialog.
const OPENS: Record<CredentialMethodKind, string> = {
    api_key: 'Add key',
    qr_scan: 'Show QR code',
    oauth: 'Sign in',
    agent_oauth: 'Sign in',
    mcp: 'Sign in',
    purchase: 'Choose a number',
};

/** Who a sign-in goes through ("Gmail" signs in with Google). */
const providerOf = (method: ProvideCredentialMethod, app: string) => getProviderConfig(method.oauth_provider ?? undefined)?.name ?? app;
/** The name a request's forms carry, as the provide page's do. */
const serviceOf = ({ ask, name }: RequestedAccount) => getProviderConfigByCredentialType(ask.credentialType)?.name ?? name;

/** Another way on, inside a row's line. */
function Also({ onClick, children }: { onClick: () => void; children: ReactNode }) {
    return (
        <>
            {' · '}
            <button type="button" onClick={onClick} className={cn(INLINE_ACTION, 'text-[12.5px]')}>
                {children}
            </button>
        </>
    );
}

export default function ConnectRequests({
    accounts,
    meta,
    onProvided,
    onFulfilled,
    onPlan,
}: {
    accounts: RequestedAccount[];
    meta?: ReactNode;
    onProvided: RowProps['onProvided'];
    onFulfilled: RowProps['onFulfilled'];
    onPlan?: () => void;
}) {
    const [attempts, setAttempts] = useState<Record<string, number>>({});
    const [opened, setOpened] = useState<Opened | null>(null);
    const close = useCallback(() => setOpened(null), []);
    const reread = useCallback((id: string) => setAttempts((prev) => ({ ...prev, [id]: (prev[id] ?? 0) + 1 })), []);
    const done = accounts.flatMap((a) => (a.done ? [a.done] : []));
    return (
        <>
            {done.length === accounts.length ? (
                <ConnectedSummary accounts={done} />
            ) : (
                <ConnectAccountsCard total={accounts.length} done={done.length} meta={meta}>
                    {accounts.map((account) =>
                        account.done ? (
                            <ConnectedRow key={account.ask.id} mark={account.mark} connected={account.done} />
                        ) : (
                            <RequestRow
                                key={`${account.ask.id}:${attempts[account.ask.id] ?? 0}`}
                                account={account}
                                onOpen={setOpened}
                                onProvided={onProvided}
                                onFulfilled={onFulfilled}
                                onRetry={reread}
                                onPlan={onPlan}
                            />
                        )
                    )}
                </ConnectAccountsCard>
            )}
            {/* Apart from the rows, so it stays on what landed after its row (or the whole card) folds. */}
            {opened && (
                <RequestDialog
                    key={opened.account.ask.id}
                    {...opened}
                    landed={!!accounts.find((a) => a.ask.id === opened.account.ask.id)?.done}
                    onProvided={onProvided}
                    onRequestEnded={reread}
                    onClose={close}
                />
            )}
        </>
    );
}

/** An account still to connect: its request read, then the way in it leads with as the row's one button. */
function RequestRow({ account, onOpen, onProvided, onFulfilled, onRetry, onPlan }: RowProps) {
    const { ask, token, name, mark } = account;
    const apiBase = apiBaseUrl();
    const request = useCredentialRequest(token, apiBase);
    const provided = useCallback((verification?: CredentialTestConnectionResponse | null) => onProvided(ask.id, verification), [onProvided, ask.id]);
    const retry = useCallback(() => onRetry(ask.id), [onRetry, ask.id]);
    const fulfilled = request.status === 'unavailable' && request.problem === 'fulfilled';
    const credentialId = request.status === 'unavailable' ? request.credentialId : undefined;
    useEffect(() => {
        if (fulfilled) onFulfilled(ask.id, credentialId);
    }, [fulfilled, credentialId, onFulfilled, ask.id]);
    const row = (detail: ReactNode, aside?: ReactNode) => <Row testId={connectRowId(name)} lead={mark} title={name} detail={detail} aside={aside} />;

    if (request.status === 'loading' || fulfilled) return row('Getting it ready');
    if (request.status === 'unavailable') {
        return row(
            <span className="whitespace-normal">{unavailableLine(name, request.problem, request.note)}</span>,
            retriesRead(request.problem, request.note) && (
                <button type="button" className={cn(PILL_QUIET, 'h-7')} onClick={retry}>
                    Try again
                </button>
            )
        );
    }
    // A plan's sign-in has a card of its own to go back to; a sign-in only Connections can finish is offered there. The
    // rest, in the order Connections offers them, the way asked for leading.
    const offersPlan = !!onPlan && request.methods.some((m) => kindFromBackendMethod(m) === 'agent_oauth');
    const offered = offersPlan ? request.methods.filter((m) => kindFromBackendMethod(m) !== 'agent_oauth') : request.methods;
    const ways = offered.filter((m) => !signsInOnlyInApp(m)).sort((a, b) => wayInRank(a) - wayInRank(b));
    const elsewhere = ways.length < offered.length;
    const switches = (
        <>
            {offersPlan && <Also onClick={() => onPlan?.()}>Sign in with your plan instead</Also>}
            {elsewhere && ways.length > 0 && <Also onClick={CONNECTIONS.open}>Sign in from {CONNECTIONS.place}</Also>}
        </>
    );
    if (!ways.length) {
        return row(
            <span className="whitespace-normal">
                Connect it in {CONNECTIONS.place}, then tell NoClick
                {switches}
            </span>,
            <button type="button" className={PILL_SECONDARY} onClick={CONNECTIONS.open}>
                Open {CONNECTIONS.place}
            </button>
        );
    }
    const method = ways.find((m) => m.credential_type === ask.credentialType) ?? ways[0];
    const kind = kindFromBackendMethod(method);
    const open = (shown: ProvideCredentialMethod) => onOpen({ account, methods: ways, method: shown.credential_type });
    const how = methodName(copyMethodOf(method), name, providerOf(method, name));
    if (kind === 'oauth') return <SignInRow account={account} method={method} ways={ways} how={how} switches={switches} open={open} onProvided={provided} onRequestEnded={retry} />;
    return row(
        <>
            {how}
            {switches}
        </>,
        <button
            type="button"
            className={kind === 'api_key' ? PILL_SECONDARY : PILL_PRIMARY}
            onClick={() => open(method)}
            data-testid={kind === 'qr_scan' ? 'coordinator-connect-qr' : undefined}
        >
            {OPENS[kind]}
        </button>
    );
}

/** A sign-in: straight from the row, its provider's own window over the request's exchange. One that asks for something
 *  first (a store, a site, an OAuth app of the person's own, or this instance's when none is set up) opens its form in
 *  the dialog instead. */
function SignInRow({
    account,
    method,
    ways,
    how,
    switches,
    open,
    onProvided,
    onRequestEnded,
}: {
    account: RequestedAccount;
    method: ProvideCredentialMethod;
    ways: ProvideCredentialMethod[];
    how: string;
    switches: ReactNode;
    open: (shown: ProvideCredentialMethod) => void;
    onProvided: (verification?: CredentialTestConnectionResponse | null) => void;
    onRequestEnded: () => void;
}) {
    // signsInOnlyInApp keeps a sign-in with no provider off the card.
    const provider = method.oauth_provider!;
    // Hosted: configured, without a request.
    const instanceApp = useInstanceOAuthApp(provider);
    const providerName = providerOf(method, account.name);
    const others = ways.filter((m) => m !== method);
    const line = (
        <>
            {how}
            {(others.length > 0 || method.supports_custom_client) && <Also onClick={() => open(others[0] ?? method)}>Other ways</Also>}
            {switches}
        </>
    );
    const row = (detail: ReactNode, aside: ReactNode) => <Row testId={connectRowId(account.name)} lead={account.mark} title={account.name} detail={detail} aside={aside} />;
    if (!signsInInOneTap(provider, method.credential_type, method.requires_custom_client) || !instanceApp.configured) {
        return row(
            line,
            <button type="button" className={PILL_PRIMARY} disabled={instanceApp.loading} onClick={() => open(method)}>
                Sign in
            </button>
        );
    }
    return (
        <ProvideLinkOAuth
            apiBase={apiBaseUrl()}
            token={account.token}
            credentialType={method.credential_type}
            oauthApp={method.oauth_app}
            onProvided={onProvided}
            onRequestEnded={onRequestEnded}
        >
            {(engine) => {
                if (engine.connectingProvider === provider) {
                    return row(
                        <>
                            Finish in the {providerName} window
                            <Also onClick={engine.cancelConnect}>Cancel</Also>
                        </>,
                        <Loader2 className="mx-2 h-4 w-4 animate-spin text-muted-foreground" aria-label={`Waiting for ${providerName}`} />
                    );
                }
                const error = engine.error || engine.planLimitError;
                return row(
                    error ? (
                        <span role="alert" className="whitespace-normal text-red-600 dark:text-red-400">
                            {error}
                        </span>
                    ) : (
                        line
                    ),
                    <button
                        type="button"
                        className={PILL_PRIMARY}
                        onClick={() => {
                            engine.clearError();
                            const userScopes = method.oauth_user_scopes ?? [];
                            engine.connect(provider, oauthCredentialName(method.credential_type, serviceOf(account)), method.oauth_scopes ?? [], undefined, undefined, userScopes.length ? userScopes : undefined);
                        }}
                    >
                        {error ? 'Try again' : 'Sign in'}
                    </button>
                );
            }}
        </ProvideLinkOAuth>
    );
}

/** Asking someone else hands them this request itself, so whoever connects it wakes NoClick just as the owner
 *  connecting it would (a new link-only request would replace this one's link); an email asks through a request of
 *  its own. */
function askWithRequest(url: string): AskTransport {
    return (event) => (event?.event_name === 'credential:request:create' && !event.target_email ? Promise.resolve({ success: true, provide_url: url }) : sendEventAsync(event));
}

/** The Connections dialog over the request: ConnectApp's ways in, a key as its steps, asking someone who can, then what
 *  landing proved and Done. Every way in is the provide page's own, run on the request's token. */
function RequestDialog({
    account,
    methods,
    method,
    landed,
    onProvided,
    onRequestEnded,
    onClose,
}: Opened & {
    /** The account is in: landed here (the dialog shows what it proved), or another way (it closes). */
    landed: boolean;
    onProvided: RowProps['onProvided'];
    onRequestEnded: (id: string) => void;
    onClose: () => void;
}) {
    const { ask, token, name } = account;
    const apiBase = apiBaseUrl();
    const [stage, setStage] = useState<ConnectStage>('connect');
    const [result, setResult] = useState<ConnectResult>();
    const header = connectDialogHeader(name, stage, result);
    const { Icon, iconColor } = getCredentialIcon(ask.credentialType);
    const askSomeone = useMemo(() => ({ credentialType: ask.credentialType, send: askWithRequest(ask.url) }), [ask.credentialType, ask.url]);
    const ended = useCallback(() => onRequestEnded(ask.id), [onRequestEnded, ask.id]);
    useEffect(() => {
        if (landed && stage !== 'done') onClose();
    }, [landed, stage, onClose]);
    return (
        <ShellDialog
            open
            onOpenChange={(next) => !next && onClose()}
            title={header.title}
            description={header.description}
            mark={<BrandIcon Icon={Icon} iconColor={iconColor} className="h-[22px] w-[22px]" />}
            testId="coordinator-connect-dialog"
        >
            <ConnectApp
                app={name}
                methods={methods}
                initial={{ method }}
                providerName={(m) => providerOf(m, name)}
                renderMethod={(m, ctx) => (
                    <CredentialMethodConnect
                        method={m}
                        apiBase={apiBase}
                        token={token}
                        serviceName={serviceOf(account)}
                        howTo={ctx.howTo}
                        showSources={ctx.showSources}
                        note={ctx.note}
                        onProvided={(verification) => ctx.onConnected({ verification })}
                        onRequestEnded={ended}
                    />
                )}
                ask={askSomeone}
                onConnected={(landed) => onProvided(ask.id, landed.verification)}
                onStage={(next, landed) => {
                    setStage(next);
                    if (landed) setResult(landed);
                }}
                onDone={onClose}
            />
        </ShellDialog>
    );
}
