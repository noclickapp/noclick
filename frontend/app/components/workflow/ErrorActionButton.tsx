// The fix for a failed node, as a button, when the backend could name one.
//
// Provider auth/billing failures are the case that motivated it: knowing the
// key was rejected is only half an answer when the credential lives three
// clicks away. The backend decides whether there IS an action (see
// provider_errors._action_for) — failures nobody can act on, like a rate limit
// or a provider outage, carry none, because a button there would be the Run
// button in disguise.
//
// Shared by every surface that shows a node error (the config panel's banner,
// the run-results popup) so the same failure offers the same fix wherever the
// user happens to be looking.
import { ExternalLink, KeyRound } from 'lucide-react';

/** Mirrors WorkflowNodeStateEvent.error_action. */
export interface ErrorAction {
    type: string;
    label: string;
    url?: string;
}

/** Open a node's Credentials tab — the same hand-off the Run popup's Connect
 *  button uses, so it lands at 70% with the node still visible and the
 *  credential controls pulsing. */
export const OPEN_CREDENTIALS_EVENT = 'noclick:node:open-credentials';

export function ErrorActionButton({
    action,
    nodeId,
    className = '',
}: {
    action: ErrorAction | undefined;
    nodeId: string;
    className?: string;
}) {
    if (!action) return null;

    const base =
        'inline-flex items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/15 px-3 py-1.5 text-xs font-semibold text-red-800 transition-colors hover:border-red-500/50 hover:bg-red-500/25 dark:text-red-200';
    const classes = `${base} ${className}`.trim();

    if (action.type === 'open_url' && action.url) {
        return (
            <a
                href={action.url}
                target="_blank"
                rel="noopener noreferrer"
                className={classes}
            >
                <ExternalLink className="h-3.5 w-3.5" />
                {action.label}
            </a>
        );
    }
    if (action.type !== 'open_credentials') return null;
    return (
        <button
            type="button"
            onClick={() =>
                document.dispatchEvent(
                    new CustomEvent(OPEN_CREDENTIALS_EVENT, { detail: { nodeId } })
                )
            }
            className={classes}
        >
            <KeyRound className="h-3.5 w-3.5" />
            {action.label}
        </button>
    );
}
