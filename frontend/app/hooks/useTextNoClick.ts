// Texting NoClick from a phone, for any surface that offers it (the sidebar's card, the chat's Connect menu): the texting
// app to offer first (the one this device switched to, else the one most people where you are use), NoClick's number
// on it, and a link that opens the app on a drafted message carrying a link code, so the phone that sends it is
// linked to this account. `ready` once there's something to offer: codes on this account, a number on that app, and
// no phone linked yet.
import { useEffect, useState } from 'react';
import { useCoordinatorReach } from '~/hooks/useCoordinatorChat';
import { useDetectedCountry } from '~/hooks/useDetectedCountry';
import { useLinkedToast, usePhoneLink, usePhoneLinkCode } from '~/hooks/usePhoneLink';
import { useFeatureGate } from '~/lib/featureGates';
import { chatHref, preferredTextApp, type TextApp } from '~/components/shell/textApp';

export const TEXT_APP_ORDER: TextApp[] = ['whatsapp', 'imessage'];
const CHOICE_KEY = 'nc-text-app'; // the app this device switched to, over the guess

function savedChoice(): TextApp | null {
    try {
        const saved = localStorage.getItem(CHOICE_KEY);
        return saved === 'whatsapp' || saved === 'imessage' ? saved : null;
    } catch {
        return null; // storage blocked: the guess stands
    }
}

export function useTextNoClick(active: boolean, { announceLink = false }: { announceLink?: boolean } = {}) {
    const codeLinking = useFeatureGate('phone_channel');
    const reach = useCoordinatorReach(active && codeLinking);
    const link = usePhoneLink({ load: false });
    const country = useDetectedCountry();
    const [choice, setChoice] = useState<TextApp | null>(null);
    const [userAgent, setUserAgent] = useState('');
    useEffect(() => {
        setChoice(savedChoice());
        setUserAgent(navigator.userAgent);
    }, []);

    const numbers: Record<TextApp, string | null> = { whatsapp: reach?.phone ?? null, imessage: reach?.imessage ?? null };
    const offered = TEXT_APP_ORDER.filter((app) => numbers[app]);
    const wanted = active && codeLinking && offered.length > 0;
    const { status, refresh } = link;
    useEffect(() => {
        if (wanted && !status) void refresh({ quiet: true });
    }, [wanted, status, refresh]);
    const linked = link.phones[0]?.phone;
    const { code, pending } = usePhoneLinkCode(link, wanted && !!status && !linked);
    useLinkedToast(announceLink ? code : null, linked);

    const guess = choice ?? preferredTextApp(country, userAgent);
    const app: TextApp | undefined = numbers[guess] ? guess : offered[0];
    const number = app ? numbers[app] : null;
    const pick = (next: TextApp) => {
        setChoice(next);
        try {
            localStorage.setItem(CHOICE_KEY, next);
        } catch {
            // storage blocked: the switch holds for this visit
        }
    };
    return {
        // No code to send (this instance can't mint one) would start a separate account: nothing to offer then.
        ready: wanted && !!status && !linked && (!!code || pending) && !!app && !!number,
        app: app ?? 'whatsapp',
        number: number ?? '',
        /** Opens the app on the linking message; null while the next code is minted. */
        href: code && app && number ? chatHref(app, number, code) : null,
        /** Opens `target` on NoClick: on the linking message until a phone is linked (null while that code is minted),
         *  then on a plain chat. */
        hrefFor: (target: TextApp) => {
            const at = numbers[target];
            if (!at) return null;
            if (linked) return chatHref(target, at, null);
            return code ? chatHref(target, at, code) : null;
        },
        numbers,
        offered,
        pick,
        linked,
    };
}
