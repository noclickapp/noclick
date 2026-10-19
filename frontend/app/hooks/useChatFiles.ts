import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import type { AgentChatAttachment } from '~/lib/agentChat';

/** A file sent before, offered to send again. */
export type ChatFile = AgentChatAttachment & { createdAt: string };

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
