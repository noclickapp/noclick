// Settings → Popups' read: which of the app's popups and banners the account's owner sees, read with GET /v1/popups
// through the client its host hands it (`ClientProvider`) and switched one at a time with PATCH /v1/popups. They are
// read again whenever they change anywhere (a popup's own "Don't show again", another tab), on the host's live frames
// (`WorkLiveContext`: a `popups` resource, or a `reset`), never on a timer.
import { useCallback, useEffect, useRef } from 'react';
import { toast } from 'sonner';
import { Popups } from 'noclick';
import { useClient } from '@/sdk/client';
import { useWorkFrames } from '@/sdk/live';
import { invalidateV1, useV1 } from '@/sdk/useV1';

/** The read's key in the client's cache. */
export const POPUPS_READ = 'settings:popups';

/** Reads the popups again wherever they're drawn: what a host calls when it hears of a change its own way. */
export function readPopupsAgain(): void {
    invalidateV1(POPUPS_READ);
}

/** Whether each popup shows, by its key; a popup not named shows. */
export type PopupsShown = Record<string, boolean>;

export interface PopupsState {
    /** Whether each popup shows; null while they're read. */
    shown: PopupsShown | null;
    /** Shows or hides one at once, and back if the API refuses it. */
    toggle: (key: string, shown: boolean) => Promise<void>;
}

export function usePopups(): PopupsState {
    const client = useClient();
    const { data, error, mutate } = useV1(POPUPS_READ, async () => (await Popups.get({ client })).popups, { client });
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'popups') readPopupsAgain();
    });
    useWorkFrames('reset', readPopupsAgain);

    // A read that failed with nothing to show is said once; the switches stay dimmed until one lands.
    const said = useRef<unknown>(undefined);
    useEffect(() => {
        if (!error || data || said.current === error) return;
        said.current = error;
        console.error('[PopupsSettings] failed to load popups:', error);
        toast.error('Failed to load popup preferences');
    }, [error, data]);

    const latest = useRef(data);
    latest.current = data;
    const toggle = useCallback(
        async (key: string, shown: boolean) => {
            const before = latest.current ?? {};
            mutate({ ...before, [key]: shown });
            try {
                mutate((await Popups.update({ [key]: shown }, { client })).popups);
            } catch (failure) {
                console.error('[PopupsSettings] failed to update popups:', failure);
                mutate({ ...(latest.current ?? before), [key]: !shown });
                toast.error('Failed to update popup preferences');
            }
        },
        [client, mutate]
    );

    return { shown: data ?? null, toggle };
}
