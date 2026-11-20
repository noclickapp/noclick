// Settings → Notifications: the email alerts NoClick sends the account's owner, one switch a category. The same
// preferences decide every send and the one-click unsubscribe link each alert email carries. Whoever draws it reads
// and writes them; this draws what it's told.
import { cn } from '@/ui/utils';
import { Switch } from '@/ui/switch';
import notificationCategories from './notificationCategories.json';
import { SettingsGroup, SettingsHeader, SettingsRow } from './parts';

/** Whether each category's emails are on, by its key; a category not named is on. */
export type NotificationPrefs = Record<string, boolean>;

/** A category's key (as NoClick names it), and what a person reads for it. */
export interface NotificationCategory {
    key: string;
    label: string;
    description: string;
}

/** Each category NoClick emails the owner about, in the order the section lists them: one table,
 *  `notificationCategories.json`, which the backend's own list of categories is held to. */
export const NOTIFICATION_CATEGORIES: readonly NotificationCategory[] = notificationCategories;

/** The section: its header and a switch per category, each on until it's read off. `prefs` null while they're read:
 *  the switches wait, dimmed. */
export function NotificationsView({ prefs, onToggle }: { prefs: NotificationPrefs | null; onToggle: (key: string, enabled: boolean) => void }) {
    const isLoading = prefs === null;
    return (
        <div>
            <SettingsHeader title="Notifications" description="Email alerts sent to your account email." />
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
