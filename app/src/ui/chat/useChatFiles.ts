// A file a chat box sends: one picked from your computer and uploaded, or one sent before and picked again.
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

/** A file a message carries, uploaded and kept. */
export interface ChatAttachment {
    resourceId: string;
    url: string;
    name: string;
    mimeType: string;
    sizeBytes: number;
}

export function isImageAttachment(a: { mimeType: string }): boolean {
    return a.mimeType.startsWith('image/');
}

/** A file sent before, offered to send again. */
export type ChatFile = ChatAttachment & { createdAt: string };

/** Files sent before, newest first, from `list`, filtered by name as you type. */
export function useChatFiles(list: (query: string) => Promise<ChatFile[]>, query: string) {
    const [files, setFiles] = useState<ChatFile[]>([]);
    const [loading, setLoading] = useState(true);
    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        const timer = setTimeout(async () => {
            try {
                const found = await list(query.trim());
                if (!cancelled) setFiles(found);
            } catch (error) {
                if (!cancelled) toast.error(error instanceof Error ? error.message : 'Could not load your files');
            } finally {
                if (!cancelled) setLoading(false);
            }
        }, query ? 150 : 0);
        return () => {
            cancelled = true;
            clearTimeout(timer);
        };
    }, [list, query]);
    return { files, loading };
}
