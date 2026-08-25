// Email notification preferences: per-category toggles (workflow failures,
// credit alerts, credential disconnections, weekly digest) backed by
// user_notification_preferences via the notifications:prefs:* socket events. The same store gates every send
// and the one-click unsubscribe links in alert emails.

import { useEffect, useState } from 'react';
import { AlertTriangle, CalendarRange, Coins, KeyRound, Unplug } from 'lucide-react';
import { toast } from 'sonner';
import { cn } from '~/lib/utils';
import { Switch } from '~/components/ui/switch';
import { sendEventAsync } from '~/lib/socket-sender';
import { useInstanceCapabilities } from '~/hooks/useInstanceCapabilities';
import {
    NotificationPrefsGetRequest,
    NotificationPrefsUpdateRequest,
} from '~/types/socket-events.generated';

type NotificationPrefs = Record<string, boolean>;

const CATEGORIES = [
    {
        key: 'run_failure',
        label: 'Workflow failures',
        description: 'When a workflow triggered by a webhook, schedule, or email fails.',
        icon: AlertTriangle,
    },
    {
        key: 'credits',
        label: 'Credit balance',
        description: 'When your credits run low or a run is blocked at zero.',
        icon: Coins,
    },
    {
        key: 'credential_revoked',
        label: 'Credential disconnections',
        description: 'When a connected account stops working and needs to be reconnected.',
        icon: KeyRound,
    },
    {
        key: 'channel_disconnected',
        label: 'Channel disconnections',
        description: 'When a live channel connection (like WhatsApp) drops and messages stop arriving.',
        icon: Unplug,
    },
    {
        key: 'digest',
        label: 'Weekly digest',
        description: 'A Monday summary of runs, failures, and credits used.',
        icon: CalendarRange,
    },
] as const;

export function NotificationsSettings() {
    const capabilities = useInstanceCapabilities();
    const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);
    const isLoading = prefs === null;

    useEffect(() => {
        const fetchPrefs = async () => {
            try {
                const response = (await sendEventAsync(
                    NotificationPrefsGetRequest.create({ request_id: crypto.randomUUID() }),
                )) as { prefs?: NotificationPrefs; error?: string };
                if (response.prefs) setPrefs(response.prefs);
            } catch (error) {
                console.error('[NotificationsSettings] failed to load prefs:', error);
                toast.error('Failed to load notification preferences');
            }
        };
        fetchPrefs();
    }, []);

    const handleToggle = async (key: string, enabled: boolean) => {
        // Optimistic flip; revert on failure.
        setPrefs((prev) => ({ ...(prev ?? {}), [key]: enabled }));
        try {
            const response = (await sendEventAsync(
                NotificationPrefsUpdateRequest.create({
                    request_id: crypto.randomUUID(),
                    prefs: { [key]: enabled },
                }),
            )) as { prefs?: NotificationPrefs; error?: string };
            if (response.error) throw new Error(response.error);
            if (response.prefs) setPrefs(response.prefs);
        } catch (error) {
            console.error('[NotificationsSettings] failed to update prefs:', error);
            setPrefs((prev) => ({ ...(prev ?? {}), [key]: !enabled }));
            toast.error('Failed to update notification preferences');
        }
    };

    return (
        <div className="max-w-2xl">
            <div className="mb-6">
                <h2 className="text-lg font-semibold text-foreground">Notifications</h2>
                <p className="text-sm text-muted-foreground dark:text-white/40 mt-1">
                    Email alerts sent to your account email.
                </p>
            </div>

            {/* Without a mail provider these toggles govern mail that is never
                sent — send_system_alert logs a warning and returns. Say so,
                with the two variables that fix it. */}
            {!capabilities.email && (
                <div className="mb-6 rounded-xl border border-amber-500/20 bg-amber-500/[0.07] px-4 py-3">
                    <p className="text-sm text-amber-600 dark:text-amber-400 font-medium">
                        No mail provider configured
                    </p>
                    <p className="text-sm text-muted-foreground dark:text-white/50 mt-1">
                        These preferences are saved, but nothing sends until this instance has an
                        email provider. Set <code className="font-mono text-xs">RESEND_API_KEY</code>{' '}
                        and <code className="font-mono text-xs">FROM_EMAIL</code> in{' '}
                        <code className="font-mono text-xs">backend/.env</code> and restart.
                    </p>
                </div>
            )}

            {/* Apple-style grouped list: one card, hairline-divided rows */}
            <div
                className={cn(
                    'rounded-xl border border-border dark:border-white/[0.06] bg-card dark:bg-foreground/[0.03] divide-y divide-border dark:divide-white/[0.06] overflow-hidden transition-opacity',
                    isLoading && 'opacity-60',
                )}
            >
                {CATEGORIES.map(({ key, label, description, icon: Icon }) => (
                    <div key={key} className="flex items-center gap-3.5 px-4 py-3.5">
                        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-foreground/[0.06] flex-shrink-0">
                            <Icon className="w-4 h-4 text-muted-foreground dark:text-white/60 stroke-[1.5]" />
                        </div>
                        <div className="flex-1 min-w-0">
                            <p className="text-[0.9375rem] font-medium text-foreground leading-tight">{label}</p>
                            <p className="text-xs text-muted-foreground dark:text-white/40 mt-0.5 truncate">{description}</p>
                        </div>
                        <Switch
                            checked={prefs?.[key] ?? true}
                            disabled={isLoading}
                            onCheckedChange={(checked) => handleToggle(key, checked)}
                        />
                    </div>
                ))}
            </div>

            <p className="text-xs text-muted-foreground/70 dark:text-white/30 mt-3 px-1">
                Every alert email also carries a one-click unsubscribe link for its category.
            </p>
        </div>
    );
}
