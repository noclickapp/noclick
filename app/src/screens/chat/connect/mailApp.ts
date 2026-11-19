// Where "Open mail" goes. Most people's mail is a website, where a mailto: link opens a desktop app they never set up,
// so an owner on a webmail we know gets its compose page, addressed and signed in as them; anyone else, mailto:.
// To read what NoClick emailed them, the same webmail opens on that message (Gmail finds it by its Message-ID) or
// their inbox; an address on no webmail we know has nowhere to open.
const enc = encodeURIComponent;

interface Webmail {
    domain: RegExp;
    label: string;
    compose: (to: string, owner: string) => string;
    inbox: (owner: string, messageId?: string) => string;
}

const WEBMAIL: Webmail[] = [
    {
        domain: /^(gmail|googlemail)\.com$/,
        label: 'Gmail',
        compose: (to, owner) => `https://mail.google.com/mail/?view=cm&fs=1&to=${enc(to)}&authuser=${enc(owner)}`,
        inbox: (owner, messageId) => `https://mail.google.com/mail/?authuser=${enc(owner)}${messageId ? `#search/rfc822msgid%3A${enc(messageId)}` : ''}`,
    },
    {
        domain: /^(outlook|hotmail|live|msn)\.[a-z.]+$/,
        label: 'Outlook',
        compose: (to) => `https://outlook.live.com/mail/0/deeplink/compose?to=${enc(to)}`,
        inbox: () => 'https://outlook.live.com/mail/0/',
    },
    { domain: /^(yahoo|ymail)\.[a-z.]+$/, label: 'Yahoo Mail', compose: (to) => `https://compose.mail.yahoo.com/?to=${enc(to)}`, inbox: () => 'https://mail.yahoo.com/' },
];

export interface MailLink {
    label: string;
    href: string;
    /** A website, opened in a new tab; mailto: hands off to the system's mail app in place. */
    web: boolean;
}

function webmailOf(ownerEmail: string): Webmail | undefined {
    const domain = ownerEmail.split('@')[1]?.toLowerCase() ?? '';
    return WEBMAIL.find((w) => w.domain.test(domain));
}

export function mailLink(to: string, ownerEmail: string): MailLink {
    const webmail = webmailOf(ownerEmail);
    return webmail ? { label: webmail.label, href: webmail.compose(to, ownerEmail), web: true } : { label: 'mail', href: `mailto:${to}`, web: false };
}

/** The owner's webmail, open on the message with this Message-ID where it can find one; null off any webmail we know. */
export function inboxLink(ownerEmail: string, messageId?: string | null): MailLink | null {
    const webmail = webmailOf(ownerEmail);
    return webmail ? { label: webmail.label, href: webmail.inbox(ownerEmail, messageId ?? undefined), web: true } : null;
}
