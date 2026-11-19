// What you're writing in each box (a channel's, a thread's), kept while you look elsewhere: its words and its files,
// each file uploaded to the channel the moment it's attached so Send only waits for what's still going up. Files
// shown before they land live until the page goes.
import { useCallback, useEffect, useRef, useState } from 'react';
import type { DraftAttachment } from '@/screens/channels/ChannelComposer';
import type { ChannelsTransport } from '@/screens/channels/transport';
import type { ChannelAttachment } from '@/screens/channels/types';
import type { VoiceClip } from '@/ui/useVoiceClip';

export interface Draft {
    text: string;
    attachments: DraftAttachment[];
}

export const EMPTY_DRAFT: Draft = { text: '', attachments: [] };

const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.');

function kindOf(file: File, clip?: VoiceClip): ChannelAttachment['kind'] {
    if (clip || file.type.startsWith('audio/')) return 'audio';
    if (file.type.startsWith('image/')) return 'image';
    if (file.type.startsWith('video/')) return 'video';
    return 'file';
}

export interface Drafts {
    get(key: string): Draft;
    setText(key: string, text: string): void;
    /** Attach a file to `key`'s box, uploading it to `channelId`. */
    attach(key: string, channelId: string, file: File, clip?: VoiceClip): void;
    remove(key: string, localId: string): void;
    /** Empty the box, handing back what it held. */
    take(key: string): Draft;
    /** Put back what a failed send took, unless something new was written meanwhile. */
    restore(key: string, draft: Draft): void;
}

export function useDrafts(transport: ChannelsTransport): Drafts {
    const [drafts, setDrafts] = useState<Record<string, Draft>>({});
    const current = useRef(drafts);
    current.current = drafts;
    const blobUrls = useRef<Set<string>>(new Set());
    useEffect(() => {
        const urls = blobUrls.current;
        return () => urls.forEach((url) => URL.revokeObjectURL(url));
    }, []);

    const update = useCallback((key: string, change: (d: Draft) => Draft) => setDrafts((prev) => ({ ...prev, [key]: change(prev[key] ?? EMPTY_DRAFT) })), []);

    return {
        get: (key) => drafts[key] ?? EMPTY_DRAFT,
        setText: (key, text) => update(key, (d) => ({ ...d, text })),
        attach: (key, channelId, file, clip) => {
            const url = URL.createObjectURL(file);
            blobUrls.current.add(url);
            const kind = kindOf(file, clip);
            const item: DraftAttachment = {
                localId: crypto.randomUUID(),
                name: file.name || 'Pasted image.png',
                mimeType: file.type || 'application/octet-stream',
                sizeBytes: file.size,
                previewUrl: kind === 'image' ? url : undefined,
                status: 'uploading',
                kind,
                url,
                voice: !!clip,
                durationMs: clip?.durationMs,
                peaks: clip?.peaks,
            };
            update(key, (d) => ({ ...d, attachments: [...d.attachments, item] }));
            const settle = (patch: Partial<DraftAttachment>) => update(key, (d) => ({ ...d, attachments: d.attachments.map((a) => (a.localId === item.localId ? { ...a, ...patch } : a)) }));
            const named = file.name ? file : new File([file], item.name, { type: item.mimeType });
            transport.upload(channelId, named, clip ? { durationMs: clip.durationMs, peaks: clip.peaks } : undefined).then(
                (attachment) => settle({ status: 'ready', attachment }),
                (e) => settle({ status: 'error', error: errorText(e) })
            );
        },
        remove: (key, localId) =>
            update(key, (d) => {
                const gone = d.attachments.find((a) => a.localId === localId);
                if (gone) {
                    URL.revokeObjectURL(gone.url);
                    blobUrls.current.delete(gone.url);
                }
                return { ...d, attachments: d.attachments.filter((a) => a.localId !== localId) };
            }),
        take: (key) => {
            const taken = current.current[key] ?? EMPTY_DRAFT;
            update(key, () => EMPTY_DRAFT);
            return taken;
        },
        restore: (key, draft) => update(key, (d) => (d.text || d.attachments.length ? d : draft)),
    };
}

/** What a sent draft's files become on the message: the server's copies, shown from where they were picked. */
export const sentFiles = (draft: Draft): ChannelAttachment[] => draft.attachments.map((a) => ({ ...(a.attachment as ChannelAttachment), url: a.url }));
