// A message that came by text or email, drawn as that app draws it: a WhatsApp or iMessage bubble with its photos,
// voice note and files, or an email with its subject and who it was from. An agent's session draws its person's
// messages with these, and so does a chat with the account's assistant. A file it carried is whoever shows them's
// card (`MESSAGE_FILE`).
import type { ComponentType } from 'react';
import { useSlot } from '@/slots';
import { EmailMessage } from '@/ui/chat/elsewhere';
import { IMessageMessage, IMessagePhotos, WhatsAppMessage, WhatsAppVoiceNote } from '@/ui/chat/channels';
import { readChannelText, readEmailText, type ChannelMedia } from '@/ui/chat/channelTurns';
import { clockTime, shortWhen } from '@/ui/chat/when';
import { MESSAGE_FILE } from '../slots';

/** A message as these draw it: its text (as the channel wrote it in), when it was sent, and an email's header. */
export interface TurnMessage {
    text: string;
    sentAt?: number;
    email?: { from?: string | null; to?: string | null; subject?: string | null };
}

/** How a file it carried is drawn: a card of the host's (`MESSAGE_FILE`) unless the caller hands its own. */
type FileCard = ComponentType<{ name: string; url: string }>;

function Files({ media, card }: { media: ChannelMedia[]; card?: FileCard }) {
    const filled = useSlot(MESSAGE_FILE);
    const FileCard = card ?? filled;
    return (
        <>
            {media.map((m) => (
                <FileCard key={m.attachmentId} name={m.name || m.label} url={m.url} />
            ))}
        </>
    );
}

function lostLine(lost: string | undefined): string {
    return lost ? `A ${lost} that couldn’t be read` : '';
}

export function WhatsAppTurn({ msg, fileCard }: { msg: TurnMessage; fileCard?: FileCard }) {
    const { text, media, shared, lost } = readChannelText(msg.text);
    const time = msg.sentAt ? clockTime(msg.sentAt) : undefined;
    const voice = media.find((m) => m.kind === 'voice' || m.kind === 'audio');
    if (voice) return <WhatsAppVoiceNote src={voice.url} transcript={voice.text} time={time} />;
    const files = media.filter((m) => m.kind !== 'image');
    return (
        <WhatsAppMessage
            text={text || lostLine(lost) || undefined}
            time={time}
            photos={media.filter((m) => m.kind === 'image').map((m) => m.url)}
            files={files.length ? <Files media={files} card={fileCard} /> : undefined}
            shared={shared}
        />
    );
}

export function IMessageTurn({ msg, fileCard }: { msg: TurnMessage; fileCard?: FileCard }) {
    const { text, media, lost } = readChannelText(msg.text);
    const photos = media.filter((m) => m.kind === 'image').map((m) => m.url);
    const files = media.filter((m) => m.kind !== 'image');
    const voice = media.find((m) => m.kind === 'voice' || m.kind === 'audio');
    return (
        <IMessageMessage
            text={text || voice?.text || lostLine(lost) || undefined}
            photo={photos.length ? <IMessagePhotos photos={photos} /> : undefined}
            files={files.length ? <Files media={files} card={fileCard} /> : undefined}
        />
    );
}

export function EmailTurn({ msg, fileCard }: { msg: TurnMessage; fileCard?: FileCard }) {
    const { subject, body } = readEmailText(msg.text);
    const { text, media } = readChannelText(body);
    // Mail since its header was kept says who it was from and to; older mail has only the subject in its text.
    const header = msg.email;
    return (
        <EmailMessage
            subject={header ? (header.subject ?? undefined) : subject}
            from={header?.from ?? undefined}
            to={header?.to ?? undefined}
            time={msg.sentAt ? shortWhen(msg.sentAt) : undefined}
            body={text}
            files={media.length ? <Files media={media} card={fileCard} /> : undefined}
        />
    );
}
