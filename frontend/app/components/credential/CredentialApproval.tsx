// Review an immutable credential call on its own page or inside the dashboard.
// The human approves one attempt; read-only arguments prevent the review from
// silently authorizing a different message, recipient, or operation.
import { Link } from 'react-router';
import { ArrowLeft, Check, ShieldCheck, X } from 'lucide-react';
import { Button } from '~/components/ui/button';
import { CredentialArguments } from './CredentialArguments';

export interface ReviewState {
    id: string;
    credential_id: string;
    credential_name: string;
    operation: string;
    node_type: string;
    arguments: Record<string, unknown>;
    status: string;
    actionable: boolean;
    consumed: boolean;
    coordinator: boolean;
    workflow?: boolean;
    detail?: string;
}

export function CredentialApproval({
    state,
    saving,
    error,
    onDecide,
    embedded = false,
}: {
    state: ReviewState;
    saving?: boolean;
    error?: string;
    onDecide: (decision: string) => void;
    embedded?: boolean;
}) {
    const approved = state.status === 'approved';
    const rejected = state.status === 'rejected';
    const Container = embedded ? 'section' : 'main';
    return (
        <Container
            className={
                embedded
                    ? 'min-w-0 text-foreground'
                    : 'min-h-screen bg-background px-5 py-10 text-foreground sm:py-16'
            }
            aria-label={embedded ? 'Review credential action' : undefined}
        >
            <div className={embedded ? 'max-w-3xl' : 'mx-auto max-w-2xl'}>
                {!embedded && (
                    <>
                        <Link
                            to="/dashboard?tab=dashboard"
                            className="mb-9 inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
                        >
                            <ArrowLeft className="h-4 w-4" />
                            Dashboard
                        </Link>
                        <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-2xl bg-foreground/[0.05]">
                            {approved ? (
                                <Check className="h-5 w-5" />
                            ) : rejected ? (
                                <X className="h-5 w-5" />
                            ) : (
                                <ShieldCheck className="h-5 w-5" />
                            )}
                        </div>
                        <p className="text-sm text-muted-foreground">
                            {state.credential_name || 'Connection'}
                        </p>
                        <h1 className="mt-2 text-3xl font-semibold tracking-tight">
                            {approved
                                ? 'Approved once'
                                : rejected
                                  ? 'Action declined'
                                  : 'Review this action'}
                        </h1>
                    </>
                )}
                {embedded && (approved || rejected) && (
                    <p className="text-sm font-medium" role="status">
                        {approved ? 'Approved once' : 'Action declined'}
                    </p>
                )}
                {state.detail ? (
                    <p role="alert" className="mt-6 text-sm text-destructive">
                        {state.detail}
                    </p>
                ) : (
                    <>
                        <p
                            className={`${embedded ? 'mt-1' : 'mt-3'} text-sm leading-6 text-muted-foreground`}
                        >
                            {approved
                                ? state.consumed
                                    ? 'This approval has been used. Another attempt will need a new approval.'
                                    : state.workflow
                                      ? 'Your workflow will continue once the pending actions in this step are approved.'
                                      : state.coordinator
                                        ? 'Your coordinator will continue from here. The approval applies only to this call.'
                                        : 'The calling tool can now retry this exact action once.'
                                : rejected
                                  ? 'This call is blocked. Your connection’s approval rules are unchanged.'
                                  : 'Nothing has run yet. Review the details before allowing this connection to act.'}
                        </p>
                        <div
                            className={`${embedded ? 'mt-4' : 'mt-9'} rounded-2xl bg-foreground/[0.04] p-5 sm:p-6`}
                        >
                            <p className="text-xs text-muted-foreground">
                                {state.node_type
                                    ?.replace(/^automation-/, '')
                                    .replaceAll('-', ' ')}
                            </p>
                            <h2 className="mt-1.5 text-lg font-medium capitalize">
                                {state.operation?.replaceAll('_', ' ')}
                            </h2>
                            <CredentialArguments arguments={state.arguments} />
                        </div>
                        {state.actionable && (
                            <div
                                className={`${embedded ? 'mt-4' : 'mt-7'} flex items-center justify-end gap-3`}
                            >
                                <Button
                                    variant="ghost"
                                    disabled={saving}
                                    onClick={() => onDecide('rejected')}
                                >
                                    Decline
                                </Button>
                                <Button
                                    disabled={saving}
                                    onClick={() => onDecide('approved')}
                                >
                                    Approve once
                                </Button>
                            </div>
                        )}
                        {!state.actionable && !approved && !rejected && (
                            <p className="mt-6 text-sm text-muted-foreground">
                                This request expired or its connection rules
                                changed. Ask the caller to request approval
                                again.
                            </p>
                        )}
                        {error && (
                            <p
                                role="alert"
                                className="mt-4 text-sm text-destructive"
                            >
                                {error}
                            </p>
                        )}
                        <p
                            className={`${embedded ? 'mt-4' : 'mt-8'} text-xs leading-5 text-muted-foreground`}
                        >
                            One call, valid for 30 minutes after approval.
                            Future calls still need permission.{' '}
                            <Link
                                to={`/credential/permissions/${state.credential_id}`}
                                className="underline underline-offset-4 hover:text-foreground"
                            >
                                Manage rules
                            </Link>
                        </p>
                    </>
                )}
            </div>
        </Container>
    );
}
