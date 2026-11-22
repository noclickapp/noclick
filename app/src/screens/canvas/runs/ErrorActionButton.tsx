// The fix for a failed step, as a button, when the API could name one.
//
// A provider refusing a key or running out of balance is the case that motivated it: knowing the key was rejected is
// only half an answer when the account lives three clicks away. The API decides whether there IS an action: failures
// nobody can act on, like a rate limit or a provider outage, carry none, because a button there would be the Run
// button in disguise.
//
// Shared by every surface that shows a step's error (the step's settings, a run's results), so the same failure offers
// the same fix wherever it's read. What each fix does is the host's (`canvas.runs.fixes`): one it can't offer isn't
// drawn.
import { CreditCard, ExternalLink, Gauge, KeyRound, type LucideIcon } from 'lucide-react';
import { useSlot } from '@/slots';
import { RUN_FIXES } from '../slots';

/** A fix as the API names it for a failed step: its kind, its label, and its address where it's a link. */
export interface ErrorAction {
    type: string;
    label: string;
    url?: string;
}

const ICONS: Record<string, LucideIcon> = { open_topup: CreditCard, open_billing: Gauge, open_credentials: KeyRound };

export function ErrorActionButton({
    action,
    nodeId,
    className = '',
}: {
    action: ErrorAction | undefined;
    nodeId: string;
    className?: string;
}) {
    const fix = useSlot(RUN_FIXES).useFix();
    if (!action) return null;

    const base =
        'inline-flex items-center gap-1.5 rounded-lg border border-red-500/30 bg-red-500/15 px-3 py-1.5 text-xs font-semibold text-red-800 transition-colors hover:border-red-500/50 hover:bg-red-500/25 dark:text-red-200';
    const classes = `${base} ${className}`.trim();

    const act = action.type === 'open_url' ? (action.url ? { href: action.url } : null) : ICONS[action.type] ? fix(action, nodeId) : null;
    if (!act) return null;
    const Icon = 'href' in act ? ExternalLink : ICONS[action.type];
    if ('href' in act) {
        return (
            <a
                href={act.href}
                target="_blank"
                rel="noopener noreferrer"
                className={classes}
            >
                <Icon className="h-3.5 w-3.5" />
                {action.label}
            </a>
        );
    }
    return (
        <button type="button" onClick={act.onClick} className={classes}>
            <Icon className="h-3.5 w-3.5" />
            {action.label}
        </button>
    );
}
