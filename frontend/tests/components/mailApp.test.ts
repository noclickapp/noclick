// "Open mail" goes where the owner's mail is: a webmail we know opens its compose page, addressed to NoClick and
// signed in as the owner; any other address hands off to the system's mail app.
import { describe, expect, it } from 'vitest';
import { inboxLink, mailLink } from '~/components/shell/mailApp';

const TO = 'dhruv@noclick.app';

describe('mailLink', () => {
    it('opens Gmail compose as the owner, in a new tab', () => {
        const link = mailLink(TO, 'Dhruv.Yadav@Gmail.com');
        expect(link).toMatchObject({ label: 'Gmail', web: true });
        const url = new URL(link.href);
        expect(url.origin + url.pathname).toBe('https://mail.google.com/mail/');
        expect(Object.fromEntries(url.searchParams)).toEqual({ view: 'cm', fs: '1', to: TO, authuser: 'Dhruv.Yadav@Gmail.com' });
    });

    it('opens Outlook and Yahoo compose for their addresses', () => {
        expect(mailLink(TO, 'a@hotmail.co.uk')).toMatchObject({ label: 'Outlook', href: `https://outlook.live.com/mail/0/deeplink/compose?to=${encodeURIComponent(TO)}` });
        expect(mailLink(TO, 'a@yahoo.co.in')).toMatchObject({ label: 'Yahoo Mail', href: `https://compose.mail.yahoo.com/?to=${encodeURIComponent(TO)}` });
    });

    it('hands any other address to the system mail app', () => {
        expect(mailLink(TO, 'founder@acme.io')).toEqual({ label: 'mail', href: `mailto:${TO}`, web: false });
        expect(mailLink(TO, 'me@icloud.com').web).toBe(false);
        // Lookalikes are not the webmail.
        expect(mailLink(TO, 'a@gmail.com.evil.io').web).toBe(false);
    });
});

describe('inboxLink', () => {
    it('opens Gmail as the owner on the message NoClick sent, found by its Message-ID', () => {
        const link = inboxLink('Dhruv.Yadav@Gmail.com', 'abc123@noclick.email');
        expect(link).toMatchObject({ label: 'Gmail', web: true });
        const url = new URL(link!.href);
        expect(url.origin + url.pathname).toBe('https://mail.google.com/mail/');
        expect(url.searchParams.get('authuser')).toBe('Dhruv.Yadav@Gmail.com');
        expect(decodeURIComponent(url.hash)).toBe('#search/rfc822msgid:abc123@noclick.email');
        expect(new URL(inboxLink('a@gmail.com')!.href).hash).toBe('');
    });

    it('opens the Outlook and Yahoo inboxes, and nothing for an address on no webmail it knows', () => {
        expect(inboxLink('a@outlook.com', 'm@noclick.email')).toMatchObject({ label: 'Outlook', href: 'https://outlook.live.com/mail/0/' });
        expect(inboxLink('a@yahoo.com')).toMatchObject({ label: 'Yahoo Mail', href: 'https://mail.yahoo.com/' });
        // mailto: would open a new message, not the one NoClick sent.
        expect(inboxLink('founder@acme.io', 'm@noclick.email')).toBeNull();
        expect(inboxLink('a@gmail.com.evil.io')).toBeNull();
    });
});
