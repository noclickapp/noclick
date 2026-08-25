/**
 * NextRunWidget - Displays the next scheduled run time with a countdown.
 * Shows the backend-provided next_run time (source of truth) and triggers
 * a refetch via onExpired when the countdown expires.
 */

import { useState, useEffect, useRef } from 'react';
import { Clock, Calendar } from 'lucide-react';

interface NextRunWidgetProps {
    value: string | null;
    onExpired?: () => void;  // Called when countdown expires, parent should refetch
    timezone?: string;  // IANA timezone used by the cron schedule (e.g., "US/Eastern")
}

/**
 * Formats an ISO date string to a human-readable format in the given timezone.
 * E.g., "Monday, Jan 15 at 9:00 AM (US/Eastern)"
 */
function formatReadableDate(isoString: string, timezone?: string): string {
    const date = new Date(isoString);
    const tz = timezone || undefined;

    const dayName = date.toLocaleDateString('en-US', { weekday: 'long', timeZone: tz });
    const month = date.toLocaleDateString('en-US', { month: 'short', timeZone: tz });
    const day = parseInt(date.toLocaleDateString('en-US', { day: 'numeric', timeZone: tz }), 10);
    const time = date.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
        timeZone: tz,
    });

    const label = timezone && timezone !== 'UTC' ? ` (${timezone})` : '';
    return `${dayName}, ${month} ${day} at ${time}${label}`;
}

/**
 * Calculates the countdown between now and the target date.
 * Returns a human-readable string like "2d 5h 30m" or "45m 12s"
 */
function getCountdown(targetDate: Date): { text: string; isPast: boolean } {
    const now = new Date();
    const diffMs = targetDate.getTime() - now.getTime();

    if (diffMs <= 0) {
        return { text: 'Running...', isPast: true };
    }

    const seconds = Math.floor(diffMs / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    const remainingHours = hours % 24;
    const remainingMinutes = minutes % 60;
    const remainingSeconds = seconds % 60;

    const parts: string[] = [];

    if (days > 0) {
        parts.push(`${days}d`);
    }
    if (remainingHours > 0 || days > 0) {
        parts.push(`${remainingHours}h`);
    }
    if (remainingMinutes > 0 || hours > 0) {
        parts.push(`${remainingMinutes}m`);
    }
    // Only show seconds if less than 1 hour remaining
    if (hours === 0 && days === 0) {
        parts.push(`${remainingSeconds}s`);
    }

    return { text: parts.join(' '), isPast: false };
}

export function NextRunWidget({ value, onExpired, timezone }: NextRunWidgetProps) {
    const [countdown, setCountdown] = useState<{ text: string; isPast: boolean }>({ text: '', isPast: false });
    const hasCalledExpired = useRef(false);

    // Update countdown every second
    useEffect(() => {
        if (!value) return;

        const targetDate = new Date(value);
        hasCalledExpired.current = false;

        const updateCountdown = () => {
            const result = getCountdown(targetDate);
            setCountdown(result);

            // When countdown expires, call onExpired once to trigger refetch
            if (result.isPast && !hasCalledExpired.current && onExpired) {
                hasCalledExpired.current = true;
                // Small delay to let the cron actually fire
                setTimeout(() => onExpired(), 2000);
            }
        };

        updateCountdown();
        const interval = setInterval(updateCountdown, 1000);
        return () => clearInterval(interval);
    }, [value, onExpired]);

    if (!value) {
        return (
            <div className="flex items-center gap-2 text-sm text-muted-foreground dark:text-zinc-500">
                <Clock className="h-4 w-4" />
                <span>Schedule not set</span>
            </div>
        );
    }

    return (
        <div className="space-y-2">
            {/* Human-readable date */}
            <div className="flex items-center gap-2 text-sm text-foreground/80">
                <Calendar className="h-4 w-4 text-muted-foreground" />
                <span>{formatReadableDate(value, timezone)}</span>
            </div>

            {/* Countdown */}
            <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <span className={`text-sm font-medium ${countdown.isPast ? 'text-amber-600 dark:text-amber-400' : 'text-emerald-600 dark:text-emerald-400'}`}>
                    {countdown.text}
                </span>
                {!countdown.isPast && <span className="text-xs text-muted-foreground dark:text-zinc-500">until next run</span>}
            </div>
        </div>
    );
}

export default NextRunWidget;
