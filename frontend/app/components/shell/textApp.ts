// The texting apps NoClick answers on: which to offer first, and how each opens a chat with it.
import type { PhoneLinkCode } from '~/hooks/usePhoneLink';

export type TextApp = 'whatsapp' | 'imessage';

// How each opens a chat with NoClick, with a drafted first message when there is one: WhatsApp's link, and for
// iMessage the Messages app's sms: link (iOS takes the body after "&").
export const TEXT_APPS = {
    whatsapp: { label: 'WhatsApp', app: 'WhatsApp', href: (number: string, body: string | null) => `https://wa.me/${number.replace(/\D/g, '')}${body ? `?text=${encodeURIComponent(body)}` : ''}` },
    imessage: { label: 'iMessage', app: 'Messages', href: (number: string, body: string | null) => `sms:${number}${body ? `&body=${encodeURIComponent(body)}` : ''}` },
} as const;

/** Opens `app` on NoClick's number, with the message that links this phone drafted when there's a code. */
export const chatHref = (app: TextApp, number: string, code: PhoneLinkCode | null) =>
    TEXT_APPS[app].href(number, code ? `Link my NoClick account: ${code.code}` : null);

// Which to offer first: iMessage where it's the bigger of the two (iPhones are most phones there and WhatsApp never
// became the default), WhatsApp everywhere else. An Android phone can't do iMessage at all.
const IMESSAGE_FIRST = new Set(['US', 'CA', 'AU', 'JP']);

export function preferredTextApp(country: string | undefined, userAgent: string): TextApp {
    if (/android/i.test(userAgent)) return 'whatsapp';
    return country && IMESSAGE_FIRST.has(country.toUpperCase()) ? 'imessage' : 'whatsapp';
}
