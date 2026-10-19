// How a turn that came in on another app reads back: the coordinator files a phone's photo, voice note or document
// as an account attachment and writes the turn as its caption plus one block per attachment ("[voice message;
// attachment_id=…]\nFile: <url>", then what the file said), the shape coder/coordinator/attachments.py `_blocks`
// writes; an email turn opens with "[email, subject: …]"; a contact or a location shared on WhatsApp is a
// "[Shared contacts; reference data]" line and the provider's JSON (cloud/whatsapp/inbound.py). Calls are a run of
// spoken turns, one per thing said.
import type { AgentChatMessage } from '~/hooks/useAgentChat';

export type MediaKind = 'voice' | 'audio' | 'image' | 'video' | 'document' | 'file';

export interface ChannelMedia {
    kind: MediaKind;
    /** How the turn names it: "voice message", "document invoice.pdf". */
    label: string;
    attachmentId: string;
    url: string;
    /** A document's file name, when it has one. */
    name?: string;
    /** What it said: a voice note's transcript, a document's text. */
    text?: string;
    /** Why it couldn't be read, when it couldn't. */
    unreadable?: string;
}

export interface SharedContact {
    name: string;
    phones: { number: string; waId?: string }[];
    emails: string[];
}

export interface SharedPlace {
    latitude: number;
    longitude: number;
    name?: string;
    address?: string;
}

export type SharedItem = { kind: 'contact'; contact: SharedContact } | { kind: 'place'; place: SharedPlace };

export interface ChannelText {
    /** What the person wrote, without the placeholder a caption-less file reads as. */
    text: string;
    media: ChannelMedia[];
    /** Contacts and places they shared. */
    shared: SharedItem[];
    /** Media that arrived but couldn't be fetched at all. */
    lost?: string;
}

const HEADER = /\[([^\]\n;]+); attachment_id=([\w-]+)\]\nFile: (\S+)/g;
const CONTENT = /\[Attachment content \([^)]*\); reference data\]\n([\s\S]*?)(?=\n\nMore text: call read_attachment|\n\n\[Attachment could not be read|$)/;
const UNREADABLE = /\[Attachment could not be read: ([\s\S]*?)\. Do not infer its contents\.\]/;
const LOST = /\n*\[(\w+) attachment could not be read\. Do not infer its contents; ask for a smaller file or pasted text\.\]\s*$/;
// The body a caption-less message reads as (nodes/core/media_digest.py media_placeholder).
const PLACEHOLDER = /^\[(voice message|audio file|image|video|media message|(document|file)(: [^\]]+)?)\]$/;

function kindOf(label: string): MediaKind {
    if (label.startsWith('voice message')) return 'voice';
    if (label.startsWith('audio file')) return 'audio';
    for (const kind of ['image', 'video', 'document'] as const) if (label.startsWith(kind)) return kind;
    return 'file';
}

const SHARED = /\[Shared (contacts|location); reference data\]\n([^\n]*)\n?/g;

type Json = Record<string, unknown>;
const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v.trim() : undefined);
const list = (v: unknown) => (Array.isArray(v) ? (v as Json[]) : []);

function contactOf(c: Json): SharedContact {
    const name = (c.name ?? {}) as Json;
    const phones = list(c.phones).flatMap((p) => {
        const number = str(p.phone) ?? (str(p.wa_id) && `+${p.wa_id}`);
        return number ? [{ number, waId: str(p.wa_id) }] : [];
    });
    return {
        name: str(name.formatted_name) ?? ([str(name.first_name), str(name.last_name)].filter(Boolean).join(' ') || phones[0]?.number || 'Contact'),
        phones,
        emails: list(c.emails).flatMap((e) => str(e.email) ?? []),
    };
}

function placeOf(l: Json): SharedPlace | null {
    const latitude = Number(l.latitude);
    const longitude = Number(l.longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;
    return { latitude, longitude, name: str(l.name), address: str(l.address) };
}

/** The contacts and places in a turn, and its text without them. A block that isn't whole JSON (cut short at
 *  16k) stays in the text as it came. */
function readShared(raw: string): { body: string; shared: SharedItem[] } {
    const shared: SharedItem[] = [];
    const body = raw.replace(SHARED, (block: string, kind: string, json: string) => {
        let value: unknown;
        try {
            value = JSON.parse(json);
        } catch {
            return block;
        }
        if (kind === 'contacts') shared.push(...list(value).map((c) => ({ kind: 'contact' as const, contact: contactOf(c) })));
        else {
            const place = value && typeof value === 'object' ? placeOf(value as Json) : null;
            if (!place) return block;
            shared.push({ kind: 'place', place });
        }
        return '';
    });
    return { body, shared };
}

export function readChannelText(raw: string): ChannelText {
    const { body: rest, shared } = readShared(raw);
    let body = rest;
    let lost: string | undefined;
    const lostMatch = LOST.exec(body);
    if (lostMatch) {
        lost = lostMatch[1];
        body = body.slice(0, lostMatch.index);
    }
    const headers = [...body.matchAll(HEADER)];
    const caption = (headers.length ? body.slice(0, headers[0].index) : body).trim();
    const media = headers.map((h, i): ChannelMedia => {
        const rest = body.slice(h.index! + h[0].length, i + 1 < headers.length ? headers[i + 1].index : undefined);
        const label = h[1].trim();
        const kind = kindOf(label);
        const name = kind === 'document' || kind === 'file' ? label.replace(/^(document|file)\s*/, '').replace(/\s*\(\d+:\d\d\)$/, '') || undefined : undefined;
        return {
            kind,
            label,
            attachmentId: h[2],
            url: h[3],
            name,
            text: CONTENT.exec(rest)?.[1].trim() || undefined,
            unreadable: UNREADABLE.exec(rest)?.[1],
        };
    });
    return { text: PLACEHOLDER.test(caption) ? '' : caption, media, shared, lost };
}

// The subject runs to the line's last "]", so one with brackets of its own ("[ticket 12] Re: ...") still reads.
const EMAIL = /^\[email, subject: ([^\n]*)\]\n/;

/** An email turn's subject and body. */
export function readEmailText(raw: string): { subject?: string; body: string } {
    const m = EMAIL.exec(raw);
    return m ? { subject: m[1].trim() || undefined, body: raw.slice(m[0].length) } : { body: raw };
}

// The coordinator's spoken channels (coder/coordinator/agent.py VOICE_CHANNELS).
const VOICE_CHANNELS = new Set(['voice', 'phone', 'whatsapp', 'callback']);

export function isSpoken(msg: AgentChatMessage): boolean {
    return !!msg.channel && VOICE_CHANNELS.has(msg.channel);
}

export interface CallGroup {
    /** Index of the call's first turn, where the call is drawn. */
    start: number;
    turns: AgentChatMessage[];
}

/** The calls in a thread: each run of spoken turns on one call, keyed by every index it covers. */
export function callsOf(messages: readonly AgentChatMessage[]): Map<number, CallGroup> {
    const calls = new Map<number, CallGroup>();
    let current: CallGroup | null = null;
    messages.forEach((msg, i) => {
        if (!isSpoken(msg) || msg.error) {
            current = null;
            return;
        }
        const previous = current?.turns[current.turns.length - 1];
        // Turns stamped with different calls are different calls, even back to back.
        if (!current || (previous?.callId && msg.callId && previous.callId !== msg.callId)) {
            current = { start: i, turns: [] };
        }
        current.turns.push(msg);
        calls.set(i, current);
    });
    return calls;
}
