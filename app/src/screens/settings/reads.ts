// Settings → Notifications' read: the email alerts NoClick sends the account's owner, read with GET /v1/notifications
// through the client its host hands it (`ClientProvider`) and switched one at a time with PATCH /v1/notifications. They
// are read again whenever they change anywhere (an alert's unsubscribe link, an agent on the owner's word, another tab),
// on the host's live frames (`WorkLiveContext`: a `notifications` resource, or a `reset`), never on a timer.
import { useCallback, useEffect, useRef } from 'react';
import { toast } from 'sonner';
import { Notifications } from 'noclick';
import { useClient } from '@/sdk/client';
import { useWorkFrames } from '@/sdk/live';
import { invalidateV1, useV1 } from '@/sdk/useV1';
import type { NotificationPrefs } from './notifications';

/** The read's key in the client's cache. */
export const NOTIFICATIONS_READ = 'settings:notifications';

/** Reads the alerts again wherever they're drawn: what a host calls when it hears of a change its own way. */
export function readNotificationsAgain(): void {
    invalidateV1(NOTIFICATIONS_READ);
}

export interface NotificationPrefsState {
    /** Whether each category's emails are on; null while they're read. */
    prefs: NotificationPrefs | null;
    /** Turns one category on or off at once, and back if the API refuses it. */
    toggle: (key: string, enabled: boolean) => Promise<void>;
}

export function useNotificationPrefs(): NotificationPrefsState {
    const client = useClient();
    const read = useV1(NOTIFICATIONS_READ, async () => (await Notifications.get({ client })).categories, { client });
    const { data, error, mutate } = read;
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'notifications') readNotificationsAgain();
    });
    useWorkFrames('reset', readNotificationsAgain);

    // A read that failed with nothing to show is said once; the switches stay dimmed until one lands.
    const said = useRef<unknown>(undefined);
    useEffect(() => {
        if (!error || data || said.current === error) return;
        said.current = error;
        console.error('[NotificationsSettings] failed to load prefs:', error);
        toast.error('Failed to load notification preferences');
    }, [error, data]);

    const latest = useRef(data);
    latest.current = data;
    const toggle = useCallback(
        async (key: string, enabled: boolean) => {
            const before = latest.current ?? {};
            mutate({ ...before, [key]: enabled });
            try {
                mutate((await Notifications.update({ [key]: enabled }, { client })).categories);
            } catch (failure) {
                console.error('[NotificationsSettings] failed to update prefs:', failure);
                mutate({ ...(latest.current ?? before), [key]: !enabled });
                toast.error('Failed to update notification preferences');
            }
        },
        [client, mutate]
    );

    return { prefs: data ?? null, toggle };
}
