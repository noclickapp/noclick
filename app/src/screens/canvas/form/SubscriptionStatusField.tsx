// Status field of app-event triggers (Slack / HubSpot / Discord). Registration
// mirrors a plain sentence while the provider will deliver, and a "⚠ …"
// verdict when it will not (the Slack app is not in the picked channel).
// When the backend can fix the verdict itself it mirrors `trigger_action`
// ({field, label}) and the field offers it as a button: the click runs that
// load_value field, whose response re-registers and re-judges the status.

import { useState } from 'react';
import { AlertTriangle, Loader2 } from 'lucide-react';

export interface SubscriptionAction {
    /** The load_value field that performs the fix (e.g. `join_channel`). */
    field: string;
    /** Button text, minted by the backend ("Join #support"). */
    label: string;
}

interface SubscriptionStatusFieldProps {
    value: string;
    isLoading?: boolean;
    action?: SubscriptionAction | null;
    onAction?: (field: string) => void | Promise<void>;
}

const WARNING_PREFIX = /^⚠\s*/;

export function SubscriptionStatusField({ value, isLoading = false, action, onAction }: SubscriptionStatusFieldProps) {
    const [busy, setBusy] = useState(false);
    const text = value || '';
    const warning = WARNING_PREFIX.test(text);
    const showLoading = isLoading && !text;

    const runAction = async () => {
        if (!action || !onAction || busy) return;
        setBusy(true);
        try {
            await onAction(action.field);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="space-y-2">
            <div
                role="status"
                data-testid="subscription-status"
                data-warning={warning || undefined}
                className={`w-full px-3 py-2 rounded-lg border text-sm flex items-start gap-2 bg-card dark:bg-foreground/[0.03] ${
                    warning
                        ? 'border-amber-500/40 text-amber-700 dark:text-amber-300'
                        : `border-border dark:border-white/[0.08] ${text ? 'text-foreground' : 'text-muted-foreground/70 italic'}`
                }`}
            >
                {showLoading ? (
                    <Loader2 className="w-4 h-4 mt-0.5 shrink-0 animate-spin text-muted-foreground" />
                ) : warning ? (
                    <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                ) : null}
                <span className="min-w-0 whitespace-pre-wrap break-words">
                    {showLoading
                        ? 'Registering…'
                        : text
                          ? text.replace(WARNING_PREFIX, '')
                          : 'Registers once a credential is attached'}
                </span>
            </div>
            {warning && action && (
                <button
                    type="button"
                    onClick={runAction}
                    disabled={busy || isLoading}
                    data-testid="subscription-action"
                    className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-xs font-medium hover:opacity-90 disabled:opacity-60"
                >
                    {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    {action.label}
                </button>
            )}
        </div>
    );
}
