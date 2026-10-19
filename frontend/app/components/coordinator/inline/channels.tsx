// What you said somewhere else, drawn here the way that app drew it, so the thread reads as one conversation across
// WhatsApp, iMessage, calls and email; NoClick's answer says which of them it went back out on.
import type { ReactNode } from 'react';
import { ArrowUpRight, Check, CheckCheck, Clock3, Loader2, Mail, MailX, MapPin, Pause, Phone, Play, UserRound } from 'lucide-react';
import { ChannelTile } from '~/components/shell/AppTile';
import type { CoordinatorEmailReply } from '~/types/socket-events.generated';
import { cn } from '~/lib/utils';
import type { SharedContact, SharedItem, SharedPlace } from '../channelTurns';
import { clock, useAudio, waveOf } from './media';
import { CARD, GlyphTile, InlineCard, PILL_QUIET } from './primitives';

export type PhoneApp = 'whatsapp' | 'imessage';

const APP_NAMES: Record<PhoneApp, string> = { whatsapp: 'WhatsApp', imessage: 'iMessage' };

/** Under a message from another app: which app, and from where when that's known. */
export function Arrived({ app, detail }: { app: PhoneApp; detail?: string }) {
    return (
        <span className="inline-flex items-center gap-1.5 px-1 text-[12px] text-muted-foreground">
            <ChannelTile channel={app} size="sm" className="h-4 w-4 rounded-[5px]" />
            {APP_NAMES[app]}
            {detail && <span>· {detail}</span>}
        </span>
    );
}

// WhatsApp's own outgoing bubble: its green, its tail, the time and read ticks tucked in the corner.
const WA_BUBBLE = 'relative rounded-lg rounded-tr-none bg-[#d9fdd3] text-[#111b21] shadow-[0_1px_0.5px_rgba(11,20,26,0.13)] dark:bg-[#005c4b] dark:text-[#e9edef]';

function WaTail() {
    return (
        <svg viewBox="0 0 8 12" className="absolute -right-2 top-0 h-3 w-2 fill-[#d9fdd3] dark:fill-[#005c4b]" aria-hidden="true">
            <path d="M5.188 0H0v11.193l6.467-8.625C7.526 1.156 6.958 0 5.188 0z" />
        </svg>
    );
}

/** The time and read ticks in the corner, as WhatsApp always pairs them; a turn saved without a time has neither. */
function WaTime({ time }: { time?: string }) {
    if (!time) return null;
    return (
        <span className="float-right ml-2.5 mt-[7px] inline-flex translate-y-[3px] items-center gap-0.5 text-[11px] leading-none text-[#667781] dark:text-white/60">
            {time}
            <CheckCheck className="h-3.5 w-3.5 text-[#53bdeb]" strokeWidth={2} />
        </span>
    );
}

const WA_ROUND = 'grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#dfe5e7] text-[#8696a0] dark:bg-white/15 dark:text-white/75';

/** A contact shared from WhatsApp: who, and their numbers and email. */
function WaContact({ contact }: { contact: SharedContact }) {
    return (
        <div className="flex min-w-[220px] items-center gap-2.5 px-1 py-1.5">
            <span className={WA_ROUND}>
                <UserRound className="h-6 w-6" />
            </span>
            <div className="min-w-0">
                <p className="truncate text-[15px] font-medium">{contact.name}</p>
                {[...contact.phones.map((p) => p.number), ...contact.emails].map((line) => (
                    <p key={line} className="truncate text-[13px] tabular-nums opacity-75">
                        {line}
                    </p>
                ))}
            </div>
        </div>
    );
}

/** Under one shared contact WhatsApp can reach, as WhatsApp ends that bubble: Message. */
function WaMessageContact({ waId }: { waId: string }) {
    return (
        <a
            href={`https://wa.me/${waId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="-mx-2.5 -mb-1.5 mt-1.5 block border-t border-black/[0.08] py-2 text-center text-[14px] font-medium text-[#027eb5] hover:underline dark:border-white/[0.12] dark:text-[#53bdeb]"
        >
            Message
        </a>
    );
}

/** A place shared from WhatsApp, opening in Maps. */
function WaPlace({ place }: { place: SharedPlace }) {
    const where = `${place.latitude},${place.longitude}`;
    return (
        <a
            href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(where)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex min-w-[220px] items-center gap-2.5 px-1 py-1.5"
        >
            <span className={WA_ROUND}>
                <MapPin className="h-5 w-5" />
            </span>
            <span className="min-w-0">
                <span className="block truncate text-[15px] font-medium">{place.name ?? 'Location'}</span>
                <span className="block truncate text-[13px] opacity-75">{place.address ?? `${place.latitude.toFixed(5)}, ${place.longitude.toFixed(5)}`}</span>
            </span>
        </a>
    );
}

/** A photo sent from a phone, opening full size. */
function Photo({ src, className }: { src: string; className?: string }) {
    return (
        <a href={src} target="_blank" rel="noopener noreferrer" className={cn('block overflow-hidden', className)}>
            <img src={src} alt="" className="max-h-72 w-full object-cover" />
        </a>
    );
}

export function WhatsAppMessage({
    text,
    time,
    from,
    photos = [],
    files,
    shared = [],
}: {
    text?: string;
    time?: string;
    from?: string;
    photos?: string[];
    files?: ReactNode;
    shared?: SharedItem[];
}) {
    const contacts = shared.flatMap((item) => (item.kind === 'contact' ? [item.contact] : []));
    const reach = contacts.length === 1 ? contacts[0].phones.find((p) => p.waId)?.waId : undefined;
    return (
        <div className="flex flex-col items-end gap-1.5 pr-2" data-testid="coordinator-whatsapp-message">
            {files && <div className="flex max-w-[78%] flex-wrap justify-end gap-1.5">{files}</div>}
            {(text || photos.length > 0 || shared.length > 0) && (
                <div className={cn(WA_BUBBLE, 'max-w-[78%] text-[14.5px] leading-[1.35]', photos.length ? 'w-[300px] p-1' : 'px-2.5 py-1.5')}>
                    <WaTail />
                    {photos.map((src) => (
                        <Photo key={src} src={src} className="mb-1 rounded-md" />
                    ))}
                    {shared.map((item, i) => (
                        <div key={i} className={cn(i > 0 && 'mt-1.5 border-t border-black/[0.08] pt-1.5 dark:border-white/[0.12]')}>
                            {item.kind === 'contact' ? <WaContact contact={item.contact} /> : <WaPlace place={item.place} />}
                        </div>
                    ))}
                    <div className={cn(photos.length && 'px-1.5 pb-0.5', reach && 'flow-root')}>
                        {text && <span className="whitespace-pre-wrap break-words">{text}</span>}
                        <WaTime time={time} />
                    </div>
                    {reach && <WaMessageContact waId={reach} />}
                </div>
            )}
            <Arrived app="whatsapp" detail={from} />
        </div>
    );
}

/** A voice note as WhatsApp draws it, playing in place, with what it said under it. */
export function WhatsAppVoiceNote({ src, seconds, transcript, time, from }: { src?: string; seconds?: number; transcript?: string; time?: string; from?: string }) {
    const audio = useAudio(src);
    const bars = waveOf(src ?? transcript ?? 'voice');
    const length = audio.duration ?? seconds;
    return (
        <div className="flex flex-col items-end gap-1.5 pr-2" data-testid="coordinator-voice-note">
            <div className={cn(WA_BUBBLE, 'flex w-[300px] max-w-[78%] items-center gap-2.5 px-2.5 py-2')}>
                <WaTail />
                <button
                    type="button"
                    aria-label={audio.playing ? 'Pause voice note' : 'Play voice note'}
                    onClick={audio.toggle}
                    disabled={!audio.playable}
                    className="grid h-8 w-8 shrink-0 place-items-center text-[#54656f] disabled:opacity-50 dark:text-white/80"
                >
                    {audio.playing ? <Pause className="h-5 w-5" fill="currentColor" /> : <Play className="h-5 w-5" fill="currentColor" />}
                </button>
                <span className="flex h-7 flex-1 items-center gap-[2px]" aria-hidden="true">
                    {bars.map((h, i) => (
                        <span
                            key={i}
                            className={cn('w-[3px] rounded-full', i / bars.length < audio.progress ? 'bg-[#53bdeb]' : 'bg-[#8696a0]/70 dark:bg-white/40')}
                            style={{ height: `${h + 4}px` }}
                        />
                    ))}
                </span>
                <span className="flex shrink-0 flex-col items-end gap-1 whitespace-nowrap text-[11px] leading-none text-[#667781] dark:text-white/60">
                    {length !== undefined && <span className="tabular-nums">{clock(length)}</span>}
                    {time && (
                        <span className="inline-flex items-center gap-0.5">
                            {time}
                            <CheckCheck className="h-3.5 w-3.5 text-[#53bdeb]" strokeWidth={2} />
                        </span>
                    )}
                </span>
            </div>
            {transcript && <p className="max-w-[70%] px-1 text-right text-[13px] italic leading-snug text-muted-foreground">“{transcript}”</p>}
            <Arrived app="whatsapp" detail={from} />
        </div>
    );
}

// iMessage's blue bubble: rounder, no ticks, and "Delivered" under the last one.
export function IMessageMessage({ text, from, photo, files }: { text?: string; from?: string; photo?: ReactNode; files?: ReactNode }) {
    return (
        <div className="flex flex-col items-end gap-1" data-testid="coordinator-imessage-message">
            {photo && <div className="max-w-[260px] overflow-hidden rounded-[18px]">{photo}</div>}
            {files && <div className="flex max-w-[78%] flex-wrap justify-end gap-1.5">{files}</div>}
            {text && <div className="max-w-[78%] whitespace-pre-wrap break-words rounded-[18px] rounded-br-[6px] bg-[#0a84ff] px-3.5 py-[7px] text-[15px] leading-[1.35] text-white">{text}</div>}
            <span className="px-1 text-[11px] font-medium text-muted-foreground">Delivered</span>
            <Arrived app="imessage" detail={from} />
        </div>
    );
}

/** iMessage photos, one under the other as Messages stacks them. */
export function IMessagePhotos({ photos }: { photos: string[] }) {
    return (
        <div className="flex flex-col gap-1">
            {photos.map((src) => (
                <Photo key={src} src={src} />
            ))}
        </div>
    );
}

export interface CallLine {
    who: 'you' | 'noclick';
    text: string;
}

/** What was said on a call, a line each: who, then what. `live` announces lines as they arrive. */
export function CallLines({ lines, live, testId }: { lines: { who: string; text: string }[]; live?: boolean; testId?: string }) {
    return (
        <dl className="space-y-1.5 text-[14px] leading-snug" data-testid={testId} aria-live={live ? 'polite' : undefined}>
            {lines.map((line, i) => (
                <div key={i} className={cn('flex gap-3', live && 'motion-safe:animate-in motion-safe:fade-in motion-safe:duration-300')}>
                    <dt className="w-16 shrink-0 text-[12.5px] leading-[1.45rem] text-muted-foreground">{line.who}</dt>
                    <dd className="min-w-0 whitespace-pre-wrap break-words text-foreground/90">{line.text}</dd>
                </div>
            ))}
        </dl>
    );
}

/** A call with NoClick: who, how long, and what was said. */
export function CallCard({ title, meta, lines, actions }: { title: string; meta?: string; lines: CallLine[]; actions?: ReactNode }) {
    return (
        <InlineCard
            lead={
                <GlyphTile>
                    <Phone className="h-4 w-4" />
                </GlyphTile>
            }
            title={title}
            meta={meta}
            actions={actions}
        >
            <CallLines lines={lines.map((line) => ({ who: line.who === 'you' ? 'You' : 'NoClick', text: line.text }))} testId="coordinator-call" />
        </InlineCard>
    );
}

/** An email you sent NoClick's address, kept as an email: its subject, who it was from and to, then what it said
 *  (the thread quoted under it already left out). Mail from before NoClick kept the addresses shows neither line. */
export function EmailMessage({ subject, body, from, to, time, files }: { subject?: string; body: string; from?: string; to?: string; time?: string; files?: ReactNode }) {
    return (
        <div className="flex flex-col items-end gap-1.5" data-testid="coordinator-email-message">
            <article className={cn(CARD, 'max-w-[480px] px-4 py-3.5')}>
                <header className="flex items-baseline gap-3">
                    <h3 className={cn('min-w-0 flex-1 break-words text-[15px] font-medium leading-snug', subject ? 'text-foreground' : 'text-muted-foreground')}>{subject || '(no subject)'}</h3>
                    {time && <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">{time}</span>}
                </header>
                {(from || to) && (
                    <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-2.5 text-[12.5px] leading-[1.6]">
                        {from && (
                            <>
                                <dt className="text-muted-foreground">From</dt>
                                <dd className="truncate text-foreground/80">{from}</dd>
                            </>
                        )}
                        {to && (
                            <>
                                <dt className="text-muted-foreground">To</dt>
                                <dd className="truncate text-foreground/80">{to}</dd>
                            </>
                        )}
                    </dl>
                )}
                {body && <p className="mt-3 whitespace-pre-wrap break-words text-[14px] leading-relaxed text-foreground/90">{body}</p>}
                {files && <div className="mt-3 flex flex-wrap gap-1.5">{files}</div>}
            </article>
            <span className="inline-flex items-center gap-1.5 px-1 text-[12px] text-muted-foreground">
                <Mail className="h-3.5 w-3.5" />
                Email
            </span>
        </div>
    );
}

export type EmailReceiptState = CoordinatorEmailReply['state'];
export type EmailFailure = NonNullable<CoordinatorEmailReply['reason']>;

// Why an email never went out, in the owner's words; the gate's or the mail service's own text rides as a tooltip
// (the others' text is written for the coordinator, not the owner).
const NOT_SENT: Record<EmailFailure, string> = {
    empty: 'there was nothing to send',
    no_address: 'NoClick has no email address yet',
    no_owner_email: 'your account has no email address',
    credits: 'your NoClick balance has run out',
    send_failed: 'the mail service refused it',
    error: 'something went wrong on our side',
};

// How far a sent email got, in ink with red kept for a bounce: one tick handed over, two delivered, as phones say it.
const SAID: Record<Exclude<EmailReceiptState, 'failed'>, { text: string; icon?: ReactNode; title?: string }> = {
    sending: { text: 'Sending', icon: <Loader2 className="h-3.5 w-3.5 animate-spin" /> },
    sent: { text: 'Sent', icon: <Check className="h-3.5 w-3.5" strokeWidth={2.25} />, title: 'Handed to the mail service, not yet confirmed as delivered' },
    delayed: { text: 'Delivery delayed, retrying', icon: <Clock3 className="h-3.5 w-3.5" /> },
    delivered: { text: 'Delivered', icon: <CheckCheck className="h-3.5 w-3.5" strokeWidth={2.25} /> },
    bounced: { text: 'Bounced' },
    unknown: { text: 'Couldn’t confirm it was sent' },
};

/** Under NoClick's reply to your email: where the reply was emailed and how far it got, from the mail service's own
 *  answers, never assumed. `open` is your webmail, for an email that is (or will be) in your inbox. */
export function EmailReceipt({
    state,
    to,
    subject,
    reason,
    error,
    open,
}: {
    state: EmailReceiptState;
    /** Where it went (every state but failed). */
    to?: string;
    subject?: string | null;
    reason?: EmailFailure | null;
    error?: string | null;
    open?: { label: string; href: string } | null;
}) {
    if (state === 'failed') {
        return (
            <p
                className="mt-1.5 flex items-start gap-1.5 text-[12.5px] leading-snug text-red-600 dark:text-red-400"
                data-testid="coordinator-email-receipt"
                data-state={state}
                title={reason === 'credits' || reason === 'send_failed' ? (error ?? undefined) : undefined}
            >
                <MailX className="mt-px h-3.5 w-3.5 shrink-0" />
                <span>Couldn’t send the email: {NOT_SENT[reason ?? 'error'] ?? NOT_SENT.error}.</span>
            </p>
        );
    }
    const said = SAID[state];
    const showOpen = open && (state === 'sent' || state === 'delayed' || state === 'delivered');
    return (
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] leading-snug text-muted-foreground" data-testid="coordinator-email-receipt" data-state={state}>
            <span className="inline-flex min-w-0 max-w-full items-center gap-1.5">
                <Mail className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">
                    {state === 'sending' ? 'Emailing ' : state === 'unknown' ? 'Email to ' : 'Emailed to '}
                    <span className="text-foreground/80">{to}</span>
                    {subject && <> · {subject}</>}
                </span>
            </span>
            <span
                className={cn('inline-flex items-center gap-1', state === 'bounced' ? 'text-red-600 dark:text-red-400' : 'text-foreground/75')}
                title={said.title ?? (state === 'bounced' ? (error ?? undefined) : undefined)}
            >
                {said.icon}
                {said.text}
                {state === 'bounced' && error ? `: ${error}` : ''}
            </span>
            {showOpen && (
                <a href={open.href} target="_blank" rel="noopener noreferrer" className={cn(PILL_QUIET, '-my-1 h-7 px-2.5 text-[12.5px]')}>
                    Open {open.label}
                    <ArrowUpRight className="h-3.5 w-3.5" />
                </a>
            )}
        </div>
    );
}

export type ReplyApp = PhoneApp | 'call' | 'email';

/** Under NoClick's reply, when it went back out on the app you wrote from (or, with `label`, where else it went). An
 *  email reply says this only when it predates receipts (EmailReceipt says what became of the rest). */
export function RepliedOn({ app, detail, label: said }: { app: ReplyApp; detail?: string; label?: string }) {
    const label = said ?? { whatsapp: 'Replied on WhatsApp', imessage: 'Replied in iMessage', call: 'Said on the call', email: 'Replied by email' }[app];
    return (
        <span className="mt-1.5 inline-flex items-center gap-1.5 text-[12px] text-muted-foreground" data-testid="coordinator-replied-on">
            {app === 'whatsapp' || app === 'imessage' ? <ChannelTile channel={app} size="sm" className="h-4 w-4 rounded-[5px]" /> : app === 'call' ? <Phone className="h-3.5 w-3.5" /> : <Mail className="h-3.5 w-3.5" />}
            {label}
            {detail && <span>· {detail}</span>}
        </span>
    );
}
