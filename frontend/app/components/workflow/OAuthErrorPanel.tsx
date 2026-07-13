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
        // Soft full-border notice (no left accent rule) with a subtle red wash.
        // Dismiss X is absolutely positioned top-right so it stays anchored
        // regardless of how many lines the body wraps to.
        <div
            role="alert"
            className="relative mb-2 rounded-md border border-red-500/25 bg-red-500/[0.07] py-2.5 pl-3 pr-8"
        >
            <button
                type="button"
                onClick={onDismiss}
                aria-label="Dismiss"
                className="absolute right-1.5 top-1.5 rounded p-1 text-red-600/60 dark:text-red-400/60 transition-colors hover:bg-red-500/10 hover:text-red-700 dark:hover:text-red-200"
            >
                <X className="h-3.5 w-3.5" aria-hidden />
            </button>
            <div className="flex items-center gap-2">
                <AlertCircle
                    className="h-4 w-4 shrink-0 text-red-600 dark:text-red-400"
                    aria-hidden
                />
                <div className="text-sm font-medium text-red-800 dark:text-red-200">
                    {heading}
                </div>
            </div>
            <p className="mt-1.5 text-xs leading-[1.55] text-red-900/85 dark:text-red-100/85">
                {message}
            </p>
            {/* Tinted (not saturated) CTA so Reconnect reads as the obvious next
                step without screaming over the rest of the sidebar. */}
            <button
                type="button"
                onClick={onReconnect}
                disabled={isReconnecting}
                className="mt-2.5 inline-flex items-center gap-1.5 rounded-md border border-red-500/30 bg-red-500/15 px-3 py-1.5 text-xs font-medium text-red-900 dark:text-red-100 transition-colors hover:border-red-500/50 hover:bg-red-500/25 disabled:cursor-not-allowed disabled:opacity-60"
            >
                {isReconnecting ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                )}
                {isReconnecting ? 'Reconnecting…' : 'Reconnect'}
            </button>
        </div>
    );
}
