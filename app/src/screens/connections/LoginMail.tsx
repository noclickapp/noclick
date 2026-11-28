// A website login NoClick signed up for has an email address of its own, the account's email at the site: its page
// shows that address and the mail the site sent there, kept a week. NoClick types the codes and opens the verification
// links for the browser signing in; a person reads them here, never an agent.
import { useState } from 'react';
import type { Connection, LoginMail as LoginMailRead, LoginMessage } from 'noclick';
import { relativeShort } from '@/lib/formatters';
import { Section } from '@/screens/resources/ui';
import { useV1 } from '@/sdk/useV1';

/** The integration a website login is. */
export const WEBSITE_LOGIN = 'website_login';

const KINDS: Record<string, string> = { code: 'Code', link: 'Verification link' };

function Message({ message }: { message: LoginMessage }) {
    const [open, setOpen] = useState(false);
    return (
        <li className="border-b border-border last:border-b-0 dark:border-foreground/[0.06]">
            <button
                type="button"
                onClick={() => setOpen(!open)}
                aria-expanded={open}
                className="flex w-full items-baseline gap-3 px-4 py-3 text-left transition-colors hover:bg-foreground/[0.025] sm:px-5"
            >
                <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] text-foreground">{message.subject || '(no subject)'}</span>
                    <span className="block truncate text-[13px] text-muted-foreground">{message.sender}</span>
                </span>
                {KINDS[message.kind] && <span className="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-[12px] text-muted-foreground dark:bg-foreground/[0.06]">{KINDS[message.kind]}</span>}
                {message.receivedAt && <span className="shrink-0 text-[12.5px] tabular-nums text-muted-foreground">{relativeShort(message.receivedAt)}</span>}
            </button>
            {open && <p className="whitespace-pre-wrap break-words px-4 pb-4 text-[13.5px] leading-relaxed text-foreground/85 sm:px-5">{message.text}</p>}
        </li>
    );
}

/** The address and what came there, as read. */
export function LoginMailList({ mail }: { mail: LoginMailRead }) {
    return (
        <Section title="Mail" meta={mail.messages.length || undefined}>
            <p className="mb-3 text-[14px] text-muted-foreground">
                Its email at the site is <span className="font-medium text-foreground">{mail.address}</span>. NoClick types the codes sent here and opens the verification links; each message is kept a week.
            </p>
            {mail.messages.length ? (
                <ul className="overflow-hidden rounded-2xl border border-border dark:border-foreground/[0.08]">
                    {mail.messages.map((message) => (
                        <Message key={message.id} message={message} />
                    ))}
                </ul>
            ) : (
                <p className="text-[14px] text-muted-foreground">Nothing has come yet.</p>
            )}
        </Section>
    );
}

/** A website login's mail, read on its page; nothing for one a person added, which has no address of its own. */
export function LoginMail({ connection }: { connection: Connection }) {
    const { data } = useV1(`connections:mail:${connection.id}`, () => connection.loginMail());
    return data?.address ? <LoginMailList mail={data} /> : null;
}
