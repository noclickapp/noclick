// Cards about the account's connections and NoClick itself: an app to connect, connected right on the card over the
// request the coordinator made (connect_credential), a call held for your OK before an account makes it, something it
// will remember (with the way to take it back), its own email address, and where a message to you went, or a way to
// reach you on your phone when there isn't one yet.
import { lazy, Suspense, useCallback, useState } from 'react';
import { Copy } from 'lucide-react';
import { toast } from 'sonner';
import { CredentialArguments } from '~/components/credential/CredentialArguments';
import { NodeMark } from '~/components/dashboard/primitives';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { QrPlaceholder } from '~/components/shared/QrCode';
import { CREDENTIALS_CHANGED_EVENT } from '~/components/shared/popups/CreateCredentialDialog';
import { describeAccount } from '~/components/shell/connections/accountNames';
import { inboxLink } from '~/components/shell/mailApp';
import { useCatalogServices } from '~/components/shell/connections/accounts';
import { EmailReceipt, RepliedOn, type EmailFailure, type EmailReceiptState } from '~/components/coordinator/inline/channels';
import { MemoryLine, PhoneHandoffCard } from '~/components/coordinator/inline/keeping';
import { PILL_PRIMARY, PILL_QUIET, Receipt, Status } from '~/components/coordinator/inline/primitives';
import { ConnectAccountCard, ConnectedReceipt } from '~/components/coordinator/inline/setup';
import { ApprovalCard } from '~/components/coordinator/inline/work';
import { useCredentialList } from '~/hooks/useCachedCredentialList';
import { useCredentialApprovalReview } from '~/hooks/useCredentialApprovalReview';
import { useSocketEvent } from '~/hooks/useSocketEvent';
import { useTextNoClick } from '~/hooks/useTextNoClick';
import { failed, obj, str, type CoordinatorToolCall } from '~/lib/coordinatorToolCalls';
import { formatPhoneForDisplay } from '~/lib/phoneFormat';
import { socketCall } from '~/lib/socketCall';
import { cn } from '~/lib/utils';
import type { CredentialTestConnectionResponse } from '~/types/socket-events.generated';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

const ConnectRequest = lazy(() => import('./ConnectRequest'));

// A connection made just before the call (clock skew between here and the server) still answers it.
const SKEW_MS = 60_000;

const reloadCredentials = () => window.dispatchEvent(new Event(CREDENTIALS_CHANGED_EVENT));

// ── An app to connect ────────────────────────────────────────────────────────

/** The request's token, from the provide link the tool answered with. */
function provideToken(url: string): string | undefined {
    return /\/credential\/provide\/([^/?#]+)/.exec(url)?.[1];
}

interface Connected {
    credentialId?: string;
    /** What the connect-time check proved, when a key was just saved here. */
    verification?: CredentialTestConnectionResponse | null;
}

export function ConnectCard({ call }: { call: CoordinatorToolCall }) {
    const type = str(call.args, 'credential_type');
    const url = str(call.result, 'url');
    if (!type || !url || failed(call.result)) return null;
    return <ConnectAccount type={type} url={url} requestId={str(call.result, 'request_id')} message={str(call.args, 'message')} startedAt={call.startedAt} />;
}

/** An account to connect, connected on the card over the request behind a provide link (`url`): the coordinator's
 *  own (connect_credential) or one a platform agent's connect link made. `requestId` hears it fulfilled elsewhere. */
export function ConnectAccount({ type, url, requestId, message, startedAt }: { type: string; url: string; requestId?: string; message?: string; startedAt: number }) {
    const token = provideToken(url);
    const services = useCatalogServices();
    const { credentials, loaded } = useCredentialList();
    const [connected, setConnected] = useState<Connected | null>(null);
    const [attempt, setAttempt] = useState(0);
    const reread = useCallback(() => setAttempt((n) => n + 1), []);
    // The request was provided: here, in another tab, or on another device from the same link.
    useSocketEvent(
        'credential_request:fulfilled',
        (frame) => {
            if (!requestId || frame.request_id !== requestId) return;
            setConnected((prev) => ({ ...prev, credentialId: frame.credential_id }));
            reloadCredentials();
        },
        [requestId]
    );
    const provided = useCallback((verification?: CredentialTestConnectionResponse | null) => {
        setConnected((prev) => ({ ...prev, verification }));
        reloadCredentials();
    }, []);
    const alreadyFulfilled = useCallback((credentialId?: string) => {
        setConnected((prev) => ({ ...prev, credentialId: credentialId ?? prev?.credentialId }));
    }, []);
    if (!token) return null;
    const service = services.find((s) => s.acceptedCredentialTypes.includes(type));
    const label = service?.label ?? humanizeCredentialLabel(type.replace(/_(oauth|api_key|token)$/, '').replace(/_/g, ' '));
    const { Icon, iconColor } = getCredentialIcon(type);
    const mark = service ? (
        <NodeMark type={service.value} size="md" />
    ) : (
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-foreground/[0.05]">
            <BrandIcon Icon={Icon} iconColor={iconColor} className="h-4 w-4" />
        </span>
    );
    // Any of the app's ways in answers the call (a WhatsApp access token for a QR request).
    const accepted = service?.acceptedCredentialTypes ?? [type];
    const made = connected?.credentialId
        ? credentials.find((c) => c.id === connected.credentialId)
        : credentials.find((c) => accepted.includes(c.credential_type) && Date.parse(c.created_at) >= startedAt - SKEW_MS);
    if (made || connected) return <ConnectedReceipt name={label} account={made && describeAccount(made, label).line} verification={connected?.verification} />;
    // An account already in shows as its receipt without reading the request (or loading the forms) first.
    if (!loaded) return null;
    const meta = message || 'NoClick picks up where it left off as soon as it’s connected.';
    return (
        <Suspense fallback={<ConnectAccountCard mark={mark} name={label} meta={meta} requested={type} renderMethod={() => null} />}>
            <ConnectRequest
                key={attempt}
                token={token}
                requested={type}
                name={label}
                mark={mark}
                meta={meta}
                onProvided={provided}
                onFulfilled={alreadyFulfilled}
                onRetry={reread}
            />
        </Suspense>
    );
}

// ── A call held for your OK ──────────────────────────────────────────────────

/** The approval a credential call is waiting on, when it's waiting on one. */
export function approvalOf(call: CoordinatorToolCall): string | undefined {
    return call.result?.status === 'pending_approval' ? str(call.result, 'approval_id') : undefined;
}

export function CredentialApprovalCard({ approvalId }: { approvalId: string }) {
    const review = useCredentialApprovalReview(approvalId);
    const state = review.state;
    if (!state) return <Status state="working">Loading what it wants to do</Status>;
    const action = state.operation ? state.operation.replaceAll('_', ' ').replace(/^\w/, (c) => c.toUpperCase()) : 'An action';
    if (state.status === 'approved') return <Receipt>Approved once: {action.toLowerCase()} on {state.credential_name || 'your account'}</Receipt>;
    if (state.status === 'rejected') return <Receipt tone="info">Declined: {action.toLowerCase()} on {state.credential_name || 'your account'}</Receipt>;
    return (
        <ApprovalCard
            lead={<NodeMark type={state.node_type} size="md" className="mt-0.5" />}
            title={action}
            meta={state.actionable ? `${state.credential_name || 'Your account'} · waiting for your OK` : 'This request expired or its rules changed'}
            actions={
                state.actionable && (
                    <>
                        <button type="button" className={PILL_PRIMARY} disabled={review.saving} onClick={() => review.decide('approved')}>
                            Approve once
                        </button>
                        <button type="button" className={PILL_QUIET} disabled={review.saving} onClick={() => review.decide('rejected')}>
                            Decline
                        </button>
                    </>
                )
            }
        >
            <div className="[&>dl]:mt-0">
                <CredentialArguments arguments={state.arguments} />
            </div>
            {review.error && <p className="mt-2 text-[13px] text-red-600 dark:text-red-400">{review.error}</p>}
        </ApprovalCard>
    );
}

// ── Something to remember ────────────────────────────────────────────────────

const FACT_CHARS = 140;

function firstLine(markdown: string | undefined): string | undefined {
    const line = markdown?.split('\n').map((l) => l.replace(/^\s*(#+|[-*]|\d+\.)\s+/, '').trim()).find(Boolean);
    return line && line.length <= FACT_CHARS ? line : undefined;
}

export function MemoryCard({ call }: { call: CoordinatorToolCall }) {
    const [forgotten, setForgotten] = useState(false);
    const [busy, setBusy] = useState(false);
    const memory = obj(call.result, 'memory');
    const id = str(memory, 'id');
    const version = memory?.version;
    // What it remembers, in its own first line; the description is written for finding it again, not for reading.
    const fact = firstLine(str(call.args, 'content')) || str(memory, 'description') || str(memory, 'name');
    if (failed(call.result) || !id || !fact) return null;
    return (
        <MemoryLine
            fact={fact}
            forgotten={forgotten}
            action={
                !forgotten && typeof version === 'number' ? (
                    <button
                        type="button"
                        className={cn(PILL_QUIET, 'h-7')}
                        disabled={busy}
                        onClick={() => {
                            setBusy(true);
                            socketCall('coordinator:memories:delete', { memory_id: id, expected_version: version })
                                .then(() => setForgotten(true))
                                .catch((e: unknown) => toast.error(e instanceof Error ? e.message : 'Could not forget it'))
                                .finally(() => setBusy(false));
                        }}
                    >
                        Undo
                    </button>
                ) : undefined
            }
        />
    );
}

// ── Its own address ──────────────────────────────────────────────────────────

export function EmailAddressLine({ call }: { call: CoordinatorToolCall }) {
    const address = str(call.result, 'address');
    if (!address) return null;
    return (
        <Receipt
            action={
                <button
                    type="button"
                    className={cn(PILL_QUIET, 'h-7')}
                    aria-label="Copy the address"
                    onClick={() => void navigator.clipboard?.writeText(address).then(() => toast.success('Copied'))}
                >
                    <Copy className="h-3.5 w-3.5" />
                </button>
            }
        >
            Email NoClick at {address}
        </Receipt>
    );
}

// ── Where a message to you went ──────────────────────────────────────────────

const NO_PHONE = /no linked phone/i;
// What the send API's answer said about the owner's address (utils/email_sending.send_email).
const SENT_STATES: Record<string, EmailReceiptState> = { delivered: 'delivered', bounced: 'bounced', queued: 'sent', accepted: 'sent' };

/** An email message_owner sent: where it went and what the mail service answered, or why it never went. */
function EmailedYou({ result }: { result: CoordinatorToolCall['result'] }) {
    const reason = str(result, 'reason') as EmailFailure | undefined;
    // A send cut off once it was out may still have gone: never call that a failure.
    if (result?.unconfirmed === true) return <EmailReceipt state="unknown" to={str(result, 'sent_to')} />;
    if (failed(result)) return reason ? <EmailReceipt state="failed" reason={reason} error={str(result, 'error')} /> : null;
    const to = str(result, 'sent_to');
    if (!to) return <RepliedOn app="email" label="Emailed you" />;
    return (
        <EmailReceipt
            state={SENT_STATES[str(result, 'delivery_status') ?? ''] ?? 'sent'}
            to={to}
            subject={str(result, 'subject')}
            open={inboxLink(to, str(result, 'message_id')?.replace(/^<|>$/g, ''))}
        />
    );
}

function PhoneHandoff() {
    const text = useTextNoClick(true);
    if (!text.ready) return null;
    return (
        <PhoneHandoffCard
            app={text.app}
            number={formatPhoneForDisplay(text.number)}
            href={text.href}
            placeholder={<QrPlaceholder label="Getting a fresh code" className="w-[132px] shrink-0 rounded-xl" />}
        />
    );
}

export function ReachLine({ call }: { call: CoordinatorToolCall }) {
    const channel = str(call.result, 'channel');
    if (channel === 'email') return <EmailedYou result={call.result} />;
    if (failed(call.result)) return NO_PHONE.test(str(call.result, 'error') ?? '') ? <PhoneHandoff /> : null;
    if (channel === 'whatsapp') return <RepliedOn app="whatsapp" label="Sent to your WhatsApp" />;
    if (channel === 'imessage') return <RepliedOn app="imessage" label="Sent to your iMessage" />;
    return null;
}
