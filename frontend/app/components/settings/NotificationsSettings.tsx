// Email notification preferences: per-category toggles (workflow failures,
// credit alerts, credential disconnections, weekly digest) backed by
// user_notification_preferences via the notifications:prefs:* socket events. The same store gates every send
// and the one-click unsubscribe links in alert emails.

import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { cn } from '~/lib/utils';
import { Switch } from '~/components/ui/switch';
import { SettingsGroup, SettingsHeader, SettingsRow } from '~/components/settings/SettingsParts';
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
        label: 'Automation failures',
        description: 'When an automation started by a webhook, schedule or email fails.',
    },
    {
        key: 'credits',
        label: 'Balance',
        description: 'When your balance runs low, or a run stops because it ran out.',
    },
    {
        key: 'topup',
        label: 'Funds and auto top-up',
        description: 'When funds you added fall below your line, or auto top-up pauses or stops.',
        billingOnly: true,
    },
    {
        key: 'credential_revoked',
        label: 'Disconnected accounts',
        description: 'When a connected account stops working and needs connecting again.',
    },
    {
        key: 'channel_disconnected',
        label: 'Channel disconnections',
        description: 'When a live channel connection (like WhatsApp) drops and messages stop arriving.',
    },
    {
        key: 'schedule_paused',
        label: 'Paused schedules',
        description: 'When a schedule is paused because its runs kept failing the same way.',
    },
    {
        key: 'spend_cap',
        label: 'Monthly spending cap',
        description: 'When your account reaches the monthly cap you set and work that costs money stops.',
        billingOnly: true,
    },
    {
        key: 'platform_paused',
        label: 'Paused apps and databases',
        description: "When your balance can't pay for your apps and databases: before they pause, and when they do.",
        billingOnly: true,
    },
    {
        key: 'referrals',
        label: 'People you invited',
        description: 'When someone you invited starts using NoClick and NoClick can’t tell you in the chat.',
        billingOnly: true,
    },
    {
        key: 'phone_numbers',
        label: 'Phone number orders',
        description: 'When the carrier approves the documents for a number, sends them back for changes, or ends the order.',
        billingOnly: true,
    },
    {
        key: 'digest',
        label: 'Weekly digest',
        description: 'A Monday summary of runs, failures, and what they spent.',
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
        <div>
            <SettingsHeader title="Notifications" description="Email alerts sent to your account email." />

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

            <SettingsGroup
                className={cn('transition-opacity', isLoading && 'opacity-60')}
                note="Every alert email also carries a one-click unsubscribe link for its category."
            >
                {CATEGORIES.filter((c) => !('billingOnly' in c) || capabilities.billing).map(({ key, label, description }) => (
                    <SettingsRow
                        key={key}
                        label={label}
                        description={description}
                        control={<Switch checked={prefs?.[key] ?? true} disabled={isLoading} aria-label={label} onCheckedChange={(checked) => handleToggle(key, checked)} />}
                    />
                ))}
            </SettingsGroup>
        </div>
    );
}
