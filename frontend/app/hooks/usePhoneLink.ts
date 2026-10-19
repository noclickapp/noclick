// Verified phones over the phone:* socket events (utils/phone_identity.py owns
// the rules): load the linked numbers, send a code to a new one, check it,
// unlink, or mint a one-time code that links whichever phone texts it to
// NoClick (WhatsApp or iMessage). Settings → Phone, the chat's "Text NoClick"
// menu and the sidebar's prompt all link through here, and read one copy of
// the linked numbers, so a number linked in one shows in the others at once.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { toast } from 'sonner';
import { formatPhoneForDisplay } from '~/lib/phoneFormat';
import { sendEventAsync } from '~/lib/socket-sender';
import {
    PhoneLinkCheckRequest,
    PhoneLinkCodeRequest,
    PhoneLinkStartRequest,
    PhoneStatusRequest,
    PhoneUnlinkRequest,
} from '~/types/socket-events.generated';

export interface LinkedPhone {
    phone: string;
    verified_at: string;
    source: 'verify' | 'whatsapp' | 'imessage';
}

export interface PhoneStatus {
    configured: boolean;
    max_phones: number;
    phones: LinkedPhone[];
}

/** A one-time code that links the phone it's texted from. */
export interface PhoneLinkCode {
    code: string;
    /** Wall-clock time (ms) after which it has too little left to scan and send, so it's no longer shown. */
    showUntil: number;
}

export interface PhoneChallenge {
    challenge_id: string;
    phone: string;
    expires_at: string;
}

type Reply<T> = Partial<T> & { error?: string; kind?: string };

const errorText = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);

// A code is shown only while it has longer than this left: time to scan it, open the app and send. The server hands
// out codes with a minute more than this (LINK_CODE_FRESH), so asking to replace a stale one always gets a new one.
const SCAN_WINDOW_S = 3 * 60;

let sharedStatus: PhoneStatus | null = null;
let minting: Promise<PhoneLinkCode | null> | null = null;
const statusListeners = new Set<() => void>();
const subscribeStatus = (listener: () => void) => {
    statusListeners.add(listener);
    return () => void statusListeners.delete(listener);
};
function setStatus(next: PhoneStatus) {
    sharedStatus = next;
    statusListeners.forEach((listener) => listener());
}

/** `load: false` defers the status read until `refresh()` — for surfaces that
 *  only need it once the user opens a phone option. */
export function usePhoneLink({ load = true }: { load?: boolean } = {}) {
    const status = useSyncExternalStore(subscribeStatus, () => sharedStatus, () => null);
    const [challenge, setChallenge] = useState<PhoneChallenge | null>(null);
    const [busy, setBusy] = useState(false);

    /** `quiet` for a background re-read, which shouldn't toast each time it fails. */
    const refresh = useCallback(async ({ quiet = false }: { quiet?: boolean } = {}) => {
        try {
            const reply = (await sendEventAsync(PhoneStatusRequest.create({ request_id: crypto.randomUUID() }))) as Reply<PhoneStatus>;
            if (reply.error) throw new Error(reply.error);
            setStatus({ configured: !!reply.configured, max_phones: reply.max_phones ?? 1, phones: reply.phones ?? [] });
        } catch (error) {
            console.error('[usePhoneLink] failed to load status:', error);
            if (!quiet) toast.error('Failed to load your phone settings');
        }
    }, []);

    /** A link code with time to scan it, or null where this account can't link that way. */
    const mintLinkCode = useCallback((): Promise<PhoneLinkCode | null> => {
        // Surfaces that ask together (the sidebar's card and one in the chat) share one request: the server hands an
        // account's live code out again anyway, but two asks in one second are over its rate limit.
        minting ??= (async () => {
            const reply = (await sendEventAsync(PhoneLinkCodeRequest.create({ request_id: crypto.randomUUID() }))) as Reply<{ code: string; expires_in: number }>;
            if (reply.error || !reply.code || typeof reply.expires_in !== 'number') {
                // Not rolled out to this account, or no code store on this instance: the panel links the other way.
                if (reply.kind !== 'gated' && reply.kind !== 'codes_unavailable') console.error('[usePhoneLink] no link code:', reply.error);
                return null;
            }
            // Seconds left, counted from now on this clock: a client clock that's off can't skew it.
            return { code: reply.code, showUntil: Date.now() + (reply.expires_in - SCAN_WINDOW_S) * 1000 };
        })().finally(() => {
            minting = null;
        });
        return minting;
    }, []);

    useEffect(() => {
        if (load) void refresh();
    }, [load, refresh]);

    /** Send a code to `phone`; true once a challenge is open. */
    const startLink = useCallback(async (phone: string): Promise<boolean> => {
        setBusy(true);
        try {
            const reply = (await sendEventAsync(
                PhoneLinkStartRequest.create({ request_id: crypto.randomUUID(), phone })
            )) as Reply<PhoneChallenge>;
            if (reply.error || !reply.challenge_id) throw new Error(reply.error || 'No challenge returned');
            setChallenge({ challenge_id: reply.challenge_id, phone: reply.phone!, expires_at: reply.expires_at! });
            return true;
        } catch (error) {
            toast.error(errorText(error, 'Could not send a code'));
            return false;
        } finally {
            setBusy(false);
        }
    }, []);

    /** Check the code for the open challenge; true once the number is linked. */
    const checkCode = useCallback(
        async (code: string): Promise<boolean> => {
            if (!challenge) return false;
            setBusy(true);
            try {
                const reply = (await sendEventAsync(
                    PhoneLinkCheckRequest.create({ request_id: crypto.randomUUID(), challenge_id: challenge.challenge_id, code })
                )) as Reply<{ phone: string; verified_at: string }>;
                if (reply.error) {
                    // Expired, exhausted or taken: the challenge is spent, start over.
                    if (reply.kind && reply.kind !== 'invalid_code') setChallenge(null);
                    throw new Error(reply.error);
                }
                setChallenge(null);
                toast.success(`Linked ${formatPhoneForDisplay(reply.phone!)}`);
                await refresh();
                return true;
            } catch (error) {
                toast.error(errorText(error, 'Could not verify the code'));
                return false;
            } finally {
                setBusy(false);
            }
        },
        [challenge, refresh]
    );

    const unlink = useCallback(
        async (phone: string): Promise<boolean> => {
            setBusy(true);
            try {
                const reply = (await sendEventAsync(
                    PhoneUnlinkRequest.create({ request_id: crypto.randomUUID(), phone })
                )) as Reply<{ unlinked: boolean }>;
                if (reply.error) throw new Error(reply.error);
                toast.success(`Unlinked ${formatPhoneForDisplay(phone)}`);
                await refresh();
                return true;
            } catch (error) {
                toast.error(errorText(error, 'Could not unlink the phone'));
                return false;
            } finally {
                setBusy(false);
            }
        },
        [refresh]
    );

    const phones = status?.phones ?? [];
    return {
        status,
        isLoading: status === null,
        phones,
        canAdd: !status || phones.length < status.max_phones,
        challenge,
        cancelChallenge: () => setChallenge(null),
        busy,
        refresh,
        mintLinkCode,
        startLink,
        checkCode,
        unlink,
    };
}

const RECHECK_MS = 4000;

/** While `active`: a link code that always has time left to scan and send (`pending` while one is on its way, when
 *  nothing should be shown), and the linked numbers re-read every few seconds while the page is visible, so a surface
 *  turns to "linked" the moment the message lands. Off, or where codes aren't available, `code` is null and nothing is pending. */
export function usePhoneLinkCode(link: ReturnType<typeof usePhoneLink>, active: boolean): { code: PhoneLinkCode | null; pending: boolean } {
    const [state, setState] = useState<{ code: PhoneLinkCode | null; pending: boolean }>({ code: null, pending: active });
    // One request at a time, shared by an effect that runs again before it lands (React's dev double-run, a quick toggle).
    const inflight = useRef<Promise<PhoneLinkCode | null> | null>(null);
    const { mintLinkCode, refresh } = link;
    useEffect(() => {
        if (!active) {
            setState({ code: null, pending: false });
            return;
        }
        let live = true;
        let current: PhoneLinkCode | null = null;
        let unavailable = false;
        const mint = async () => {
            setState({ code: null, pending: true });
            inflight.current ??= mintLinkCode()
                .catch((error: unknown) => {
                    console.error('[usePhoneLinkCode] mint failed:', error);
                    return null;
                })
                .finally(() => {
                    inflight.current = null;
                });
            const next = await inflight.current;
            if (!live) return;
            current = next;
            unavailable = !next;
            setState({ code: next, pending: false });
        };
        // Judged on the wall clock every second and whenever the page comes back, never by a timer set for the
        // deadline: timers stall while a laptop sleeps and slow down in a background tab, just when a code goes stale on
        // screen. A hidden page drops its code and gets the next one when it's looked at again.
        const check = () => {
            if (current && Date.now() < current.showUntil) return;
            if (current) {
                current = null;
                setState({ code: null, pending: true });
            }
            if (!current && !unavailable && !inflight.current && document.visibilityState === 'visible') void mint();
        };
        void mint();
        const tick = setInterval(check, 1000);
        // Only while someone can be looking: a code sits on screen on every page until a phone is linked.
        const recheck = setInterval(() => document.visibilityState === 'visible' && void refresh({ quiet: true }), RECHECK_MS);
        document.addEventListener('visibilitychange', check);
        window.addEventListener('focus', check);
        return () => {
            live = false;
            clearInterval(tick);
            clearInterval(recheck);
            document.removeEventListener('visibilitychange', check);
            window.removeEventListener('focus', check);
        };
    }, [active, mintLinkCode, refresh]);
    return state;
}

/** Says "Linked …" once a phone that was offered a code turns up linked. */
export function useLinkedToast(code: PhoneLinkCode | null, linked: string | undefined) {
    const offered = useRef(false);
    useEffect(() => {
        if (code) offered.current = true;
        else if (linked && offered.current) {
            offered.current = false;
            // One toast however many surfaces offered the code.
            toast.success(`Linked ${formatPhoneForDisplay(linked)}`, { id: `phone-linked:${linked}` });
        }
    }, [code, linked]);
}
