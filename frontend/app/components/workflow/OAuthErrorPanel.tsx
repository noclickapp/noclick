// Shared OAuth-failure panel surfaced when an OAuth exchange returns an
// error message — currently driven by the Google handler's scope-rejection
// path but generic over any provider whose exchange response includes a
// user-facing `message` field. Replaces the prior text-xs inline strip used
// in NodeCredentials and GenerationCredentialSelector, which was easy to
// miss for a long actionable message (e.g. "Google didn't grant the Gmail
// permission. Please reconnect…") and offered no direct way to retry.

import { AlertCircle, Loader2, RefreshCw, X } from 'lucide-react';

interface OAuthErrorPanelProps {
    /** Error text returned by the OAuth exchange (already user-facing). */
    message: string;
    /** Re-fires the OAuth connect flow with the same provider/scopes/etc. */
    onReconnect: () => void;
    /** Clears the panel without retrying (e.g., user wants to do something else first). */
    onDismiss: () => void;
    /** True while the next attempt's popup is open / token exchange is pending. */
    isReconnecting?: boolean;
}

// Signature substring from the Google scope-rejection message. Lets us swap
// the heading to a permission-specific one without parsing the full text.
const SCOPE_REJECTION_MARKER = "didn't grant";

export function OAuthErrorPanel({
    message,
    onReconnect,
    onDismiss,
    isReconnecting,
}: OAuthErrorPanelProps) {
    const isScopeIssue = message.includes(SCOPE_REJECTION_MARKER);
    const heading = isScopeIssue ? 'Permissions missing' : 'Connection failed';

    return (
        <div
            role="alert"
            className="mb-2 flex gap-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3"
        >
            <AlertCircle
                className="mt-0.5 h-4 w-4 shrink-0 text-red-400"
                aria-hidden
            />
            <div className="flex-1 space-y-2">
                <div className="text-sm font-medium text-red-300">{heading}</div>
                <div className="text-xs leading-relaxed text-red-200/90">{message}</div>
                <div className="flex items-center gap-2 pt-0.5">
                    <button
                        type="button"
                        onClick={onReconnect}
                        disabled={isReconnecting}
                        className="inline-flex items-center gap-1.5 rounded-md bg-red-500/20 px-2.5 py-1 text-xs font-medium text-red-200 transition-colors hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                        {isReconnecting ? (
                            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                        ) : (
                            <RefreshCw className="h-3 w-3" aria-hidden />
                        )}
                        Reconnect
                    </button>
                </div>
            </div>
            <button
                type="button"
                onClick={onDismiss}
                aria-label="Dismiss"
                className="text-red-400/70 transition-colors hover:text-red-200"
            >
                <X className="h-4 w-4" aria-hidden />
            </button>
        </div>
    );
}
