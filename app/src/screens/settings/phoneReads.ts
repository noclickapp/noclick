// Settings → Phone's read: the numbers linked to the account, read with GET /v1/account/phones through the client its
// host hands it (`ClientProvider`), a new one linked by a code texted to it (POST /v1/account/phones, then .../verify)
// and one unlinked (DELETE /v1/account/phones/{phone}). These are the signed-in owner's, or a key's that names
// `account:phones` (screens/console/ownerOnly.ts: this app's key doesn't). Read again whenever they change anywhere (a
// number linked by texting NoClick, another tab), on the host's live frames (`WorkLiveContext`: a `phones` resource,
// or a `reset`), never on a timer.
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { AccountPhones, NoClickError, type LinkedPhone } from 'noclick';
import { formatPhoneForDisplay } from '@/lib/phoneFormat';
import { useClient } from '@/sdk/client';
import { useWorkFrames } from '@/sdk/live';
import { invalidateV1, useV1 } from '@/sdk/useV1';

/** The read's key in the client's cache. */
export const PHONES_READ = 'settings:phones';

/** Reads the linked numbers again wherever they're drawn: what a host calls when it hears of a change its own way. */
export function readPhonesAgain(): void {
    invalidateV1(PHONES_READ);
}

/** What the account has linked, and how many it may. */
export interface PhoneStatus {
    /** Whether this NoClick sends codes to link a number. */
    configured: boolean;
    maxPhones: number;
    phones: readonly LinkedPhone[];
}

/** A code texted to a number, waiting to be typed back. */
export interface PhoneChallenge {
    id: string;
    phone: string;
}

export interface PhonesState {
    /** Null while it's read. */
    status: PhoneStatus | null;
    phones: readonly LinkedPhone[];
    /** Whether another number may be linked (while it's read, yes). */
    canAdd: boolean;
    challenge: PhoneChallenge | null;
    cancelChallenge: () => void;
    /** A send, a check or an unlink is under way. */
    busy: boolean;
    /** Texts a code to `phone`; true once it's on its way. */
    startLink: (phone: string) => Promise<boolean>;
    /** Checks the code for the open challenge; true once the number is linked. */
    checkCode: (code: string) => Promise<boolean>;
    unlink: (phone: string) => Promise<boolean>;
}

const why = (error: unknown, otherwise: string) => (error instanceof Error && error.message ? error.message : otherwise);

export function usePhones(): PhonesState {
    const client = useClient();
    const read = useV1(PHONES_READ, async () => {
        const linked = await AccountPhones.get({ client });
        return { configured: linked.configured, maxPhones: linked.maxPhones, phones: linked.phones } satisfies PhoneStatus;
    }, { client });
    useWorkFrames('platform:resource', (frame) => {
        if (frame.kind === 'phones') readPhonesAgain();
    });
    useWorkFrames('reset', readPhonesAgain);
    const { data, error, refresh } = read;
    const [challenge, setChallenge] = useState<PhoneChallenge | null>(null);

    // A read that failed with nothing to show is said once; the list and the form wait until one lands.
    const said = useRef<unknown>(undefined);
    useEffect(() => {
        if (!error || data || said.current === error) return;
        said.current = error;
        console.error('[PhoneSettings] failed to load the linked numbers:', error);
        toast.error('Failed to load your phone settings');
    }, [error, data]);
    const [busy, setBusy] = useState(false);

    const startLink = useCallback(
        async (phone: string) => {
            setBusy(true);
            try {
                const sent = await AccountPhones.link(phone, { client });
                setChallenge({ id: sent.id, phone: sent.phone });
                return true;
            } catch (error) {
                toast.error(why(error, 'Could not send a code'));
                return false;
            } finally {
                setBusy(false);
            }
        },
        [client]
    );

    const checkCode = useCallback(
        async (code: string) => {
            if (!challenge) return false;
            setBusy(true);
            try {
                const linked = await AccountPhones.verify(challenge.id, code, { client });
                setChallenge(null);
                toast.success(`Linked ${formatPhoneForDisplay(linked.phone)}`);
                await refresh();
                return true;
            } catch (error) {
                // Expired, out of tries or taken: the challenge is spent, start over. A wrong code can be tried again.
                if (!(error instanceof NoClickError) || error.details.reason !== 'invalid_code') setChallenge(null);
                toast.error(why(error, 'Could not verify the code'));
                return false;
            } finally {
                setBusy(false);
            }
        },
        [challenge, client, refresh]
    );

    const unlink = useCallback(
        async (phone: string) => {
            setBusy(true);
            try {
                await AccountPhones.unlink(phone, { client });
                toast.success(`Unlinked ${formatPhoneForDisplay(phone)}`);
                await refresh();
                return true;
            } catch (error) {
                toast.error(why(error, 'Could not unlink the phone'));
                return false;
            } finally {
                setBusy(false);
            }
        },
        [client, refresh]
    );

    const status = data ?? null;
    const phones = status?.phones ?? [];
    return {
        status,
        phones,
        canAdd: !status || phones.length < status.maxPhones,
        challenge,
        cancelChallenge: () => setChallenge(null),
        busy,
        startLink,
        checkCode,
        unlink,
    };
}
