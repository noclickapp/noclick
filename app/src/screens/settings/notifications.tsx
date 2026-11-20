// Settings → Notifications: the email alerts NoClick sends the account's owner, one switch a category. The same
// preferences decide every send and the one-click unsubscribe link each alert email carries. Whoever draws it reads
// and writes them; this draws what it's told.
import type { ReactNode } from 'react';
import { cn } from '@/ui/utils';
import { Switch } from '@/ui/switch';
import { SettingsGroup, SettingsHeader, SettingsRow } from './parts';

/** Whether each category's emails are on, by its key; a category not named is on. */
export type NotificationPrefs = Record<string, boolean>;

export const NOTIFICATION_CATEGORIES = [
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
        key: 'sign_in_expiring',
        label: 'Expiring sign-ins',
        description: 'A few days before a Claude sign-in your agents use expires, so you can sign in again in time.',
    },
    {
        key: 'approvals',
        label: 'Approvals',
        description: 'When an agent is waiting for you to approve something it asked to do with an account you restricted.',
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
    },
    {
        key: 'platform_paused',
        label: 'Paused apps and databases',
        description: "When your balance can't pay for your apps and databases: before they pause, and when they do.",
    },
    {
        key: 'referrals',
        label: 'People you invited',
        description: 'When someone you invited starts using NoClick and NoClick can’t tell you in the chat.',
    },
    {
        key: 'machines',
        label: 'Machines',
        description: 'When NoClick decides your request for machines: approved, or declined with the reason.',
    },
    {
        key: 'phone_numbers',
        label: 'Phone number orders',
        description: 'When the carrier approves the documents for a number, sends them back for changes, or ends the order.',
    },
    {
        key: 'digest',
        label: 'Weekly digest',
        description: 'A Monday summary of runs, failures, and what they spent.',
    },
] as const;

/** The section: its header, anything its host says above the switches (`notice`), and a switch per category, each
 *  on until it's read off. `prefs` null while they're read: the switches wait, dimmed. */
export function NotificationsView({ prefs, onToggle, notice }: { prefs: NotificationPrefs | null; onToggle: (key: string, enabled: boolean) => void; notice?: ReactNode }) {
    const isLoading = prefs === null;
    return (
        <div>
            <SettingsHeader title="Notifications" description="Email alerts sent to your account email." />
            {notice}
            <SettingsGroup
                className={cn('transition-opacity', isLoading && 'opacity-60')}
                note="Every alert email also carries a one-click unsubscribe link for its category."
            >
                {NOTIFICATION_CATEGORIES.map(({ key, label, description }) => (
                    <SettingsRow
                        key={key}
                        label={label}
                        description={description}
                        control={<Switch checked={prefs?.[key] ?? true} disabled={isLoading} aria-label={label} onCheckedChange={(checked) => onToggle(key, checked)} />}
                    />
                ))}
            </SettingsGroup>
        </div>
    );
}
