/*
Builder chat history: the chats, newest first, grouped by when, with search, resume, delete and a new chat.

`useChatHistory` owns the data (the list cached in useCachedValtioState + IndexedDB so it shows at once while a fresh
copy loads, resuming through the conversation cache first, deleting); `ChatHistory` is the dropdown that draws it,
and the builder panel draws it in place of its thread (chat/builder/BuilderHistory).
*/

import { useState, useEffect, useCallback, useRef, memo } from 'react';
import { createPortal } from 'react-dom';
import { Clock, Trash2, Plus, MessageSquare } from 'lucide-react';
import { useSocketEvent } from '~/hooks/useSocketEvent';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { useConversationCache } from '~/hooks/useConversationCache';
import { sendEvent, sendEventAsync, ListConversationsRequest, DeleteConversationRequest } from '~/lib/socket-sender';
import type { ConversationListEvent, ConversationResumeEvent } from '~/types/socket-events.generated';
import { mapPersistedMessages } from '~/hooks/conversationRestoreMapping';
import { fuzzyFilter } from '~/utils/fuzzySearch';
import { freshConversationId } from '~/lib/chat-storage';
import { BUILDER_WELCOME } from '~/lib/builderSteps';
import type { Message } from './types';

export interface Conversation {
    conversation_id: string;
    title: string;
    preview: string;
    last_activity: string;
    created_at: string;
    app_id?: string;
    app_name?: string;
}

export const HISTORY_GROUPS = ['Today', 'Yesterday', 'Last 7 Days', 'Last 30 Days', 'Older'] as const;

function groupOf(isoString: string): (typeof HISTORY_GROUPS)[number] {
    const diffDays = Math.floor((Date.now() - new Date(isoString).getTime()) / (1000 * 60 * 60 * 24));
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays <= 7) return 'Last 7 Days';
    if (diffDays <= 30) return 'Last 30 Days';
    return 'Older';
}

/** "now", "5m", "3h", "2d", "1w", else the date. */
export function historyTime(isoString: string): string {
    const date = new Date(isoString);
    const diffMinutes = Math.floor((Date.now() - date.getTime()) / (1000 * 60));
    if (diffMinutes < 1) return 'now';
    if (diffMinutes < 60) return `${diffMinutes}m`;
    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours}h`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays}d`;
    if (diffDays < 30) return `${Math.floor(diffDays / 7)}w`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

interface ChatHistoryOptions {
    currentConversationId: string;
    onConversationChange: (conversationId: string, messages: Message[]) => void;
    /** Read a fresh list while true (the dropdown open, the panel's history showing). */
    active: boolean;
    /** Called once a chat is resumed or a new one started. */
    onDone?: () => void;
}

/** The builder's chats: the list (fresh while `active`), search over it, and resuming, deleting or starting one. */
export function useChatHistory({ currentConversationId, onConversationChange, active, onDone }: ChatHistoryOptions) {
    const [conversations, setConversations] = useCachedValtioState<Conversation[]>('chat-history', 'conversations', []);
    const [searchQuery, setSearchQuery] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const [deletingId, setDeletingId] = useState<string | null>(null);
    const { getFromCache } = useConversationCache();

    useSocketEvent('conversations:list', useCallback((data: ConversationListEvent) => {
        setConversations(data.conversations as unknown as Conversation[]);
        setIsLoading(false);
    }, [setConversations]));

    useEffect(() => {
        if (!active) return;
        setIsLoading(true);
        sendEvent(ListConversationsRequest.create({ request_id: crypto.randomUUID(), tag: 'Loading conversations' }));
        const timeout = setTimeout(() => setIsLoading(false), 5000);
        return () => clearTimeout(timeout);
    }, [active]);

    const filtered = fuzzyFilter(conversations, searchQuery, (conv) => [
        { text: (conv.title ?? '').toLowerCase(), weight: 1, fuzzy: true },
        { text: (conv.app_name ?? '').toLowerCase(), weight: 0.6, fuzzy: true },
        { text: (conv.preview ?? '').toLowerCase(), weight: 0.4 },
    ]);
    const grouped = HISTORY_GROUPS.map((group) => ({
        group,
        conversations: filtered
            .filter((conv) => groupOf(conv.last_activity) === group)
            .sort((a, b) => new Date(b.last_activity).getTime() - new Date(a.last_activity).getTime()),
    })).filter((g) => g.conversations.length > 0);

    const startNew = useCallback(() => {
        onConversationChange(freshConversationId(), [{ text: BUILDER_WELCOME, isUser: false, isComplete: true }]);
        onDone?.();
    }, [onConversationChange, onDone]);

    const resume = useCallback(async (conversationId: string) => {
        try {
            // Opened before in this session: from the conversation cache, at once.
            const cached = getFromCache(conversationId);
            if (cached) {
                onConversationChange(conversationId, cached.messages.map((msg) => ({
                    text: msg.text,
                    isUser: msg.isUser,
                    isComplete: true,
                    content: msg.content || undefined,
                    agenticSteps: msg.agenticSteps,
                    editSegments: msg.editSegments,
                    editSteps: msg.editSteps,
                })));
                onDone?.();
                return;
            }
            const response = await sendEventAsync<ConversationResumeEvent>({ event_name: 'conversation:resume', session_id: conversationId });
            onConversationChange(response.session_id, mapPersistedMessages(response.messages));
            onDone?.();
        } catch (error) {
            console.error('[ChatHistory] Failed to resume conversation', error);
        }
    }, [getFromCache, onConversationChange, onDone]);

    const remove = useCallback(async (conversationId: string) => {
        try {
            setDeletingId(conversationId);
            // The ResponseEvent's data: {success, conversation_id?}.
            const response = await sendEventAsync(DeleteConversationRequest.create({ conversation_id: conversationId }));
            if ((response as { success?: boolean }).success) {
                setConversations((prev) => prev.filter((conv) => conv.conversation_id !== conversationId));
                if (conversationId === currentConversationId) startNew();
            } else {
                console.error('[ChatHistory] Delete failed:', response);
            }
        } catch (error) {
            console.error('[ChatHistory] Error deleting conversation:', error);
        } finally {
            setDeletingId(null);
        }
    }, [currentConversationId, setConversations, startNew]);

    return { conversations, grouped, searchQuery, setSearchQuery, isLoading, deletingId, startNew, resume, remove };
}

/** The history as a dropdown under a clock button. */
export const ChatHistory = memo(function ChatHistory({
    currentConversationId,
    onConversationChange
}: {
    currentConversationId: string;
    onConversationChange: (conversationId: string, messages: Message[]) => void;
}) {
    const [isOpen, setIsOpen] = useState(false);
    const [hoveredId, setHoveredId] = useState<string | null>(null);
    const buttonRef = useRef<HTMLDivElement>(null);
    const dropdownRef = useRef<HTMLDivElement>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);
    const close = useCallback(() => setIsOpen(false), []);
    const history = useChatHistory({ currentConversationId, onConversationChange, active: isOpen, onDone: close });
    const { conversations, grouped, searchQuery, setSearchQuery, isLoading, deletingId } = history;

    useEffect(() => {
        if (!isOpen) return;
        const timer = setTimeout(() => searchInputRef.current?.focus(), 100);
        return () => clearTimeout(timer);
    }, [isOpen]);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node;
            const clickedOutsideButton = buttonRef.current && !buttonRef.current.contains(target);
            const clickedOutsideDropdown = dropdownRef.current && !dropdownRef.current.contains(target);
            if (clickedOutsideButton && clickedOutsideDropdown) setIsOpen(false);
        };
        if (isOpen) document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isOpen]);

    const newChatRow = (
        <button
            onClick={history.startNew}
            className="w-full px-3 py-1.5 text-left hover:bg-accent/50 dark:hover:bg-zinc-900/50 transition-colors group"
        >
            <div className="flex items-start gap-2">
                <Plus className="w-4 h-4 text-muted-foreground/70 dark:text-zinc-600 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                    <p className="text-[13px] text-muted-foreground font-normal">New Chat</p>
                </div>
            </div>
        </button>
    );

    return (
        <>
            <div ref={buttonRef} className="relative" data-onboarding="chat-history">
                <button
                    onClick={() => setIsOpen(!isOpen)}
                    className="flex items-center justify-center text-muted-foreground hover:text-foreground transition-colors duration-200"
                    title="Chat History"
                >
                    <Clock className="w-5 h-5" />
                </button>
            </div>

            {isOpen && createPortal(
                <div
                    ref={dropdownRef}
                    className="fixed top-[60px] left-3 right-3 sm:right-auto sm:w-[480px] bg-popover rounded-lg shadow-2xl flex flex-col overflow-hidden z-[9999]"
                    style={{ height: '300px', maxHeight: 'calc(100vh - 80px)' }}
                >
                    <div className="px-3 py-1.5 bg-popover flex-shrink-0">
                        <div className="relative flex items-center gap-2">
                            <input
                                ref={searchInputRef}
                                type="text"
                                placeholder="Search..."
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                className="flex-1 px-2 py-1 text-sm bg-transparent text-muted-foreground border-none focus:outline-none placeholder:text-[hsl(var(--placeholder))]"
                            />
                            <button
                                onClick={history.startNew}
                                className="flex items-center justify-center p-1.5 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-accent dark:hover:bg-zinc-800/50 rounded-full transition-colors flex-shrink-0"
                                title="New Chat"
                            >
                                <Plus className="w-4 h-4" />
                            </button>
                        </div>
                    </div>

                    <div className="flex-1 min-h-0 overflow-y-auto scrollbar-subtle">
                        {isLoading && conversations.length === 0 ? (
                            <div className="p-8 text-center text-muted-foreground dark:text-zinc-500 text-sm">
                                <Clock className="w-8 h-8 mx-auto mb-2 opacity-40 animate-spin" />
                                <p className="text-muted-foreground text-xs">Loading conversations...</p>
                            </div>
                        ) : grouped.length === 0 ? (
                            <div>
                                <div className="py-0.5">
                                    <div className="px-3 py-1.5 text-[11px] font-medium text-muted-foreground dark:text-zinc-500">Today</div>
                                    {newChatRow}
                                </div>
                                <div className="p-8 text-center text-muted-foreground dark:text-zinc-500 text-sm">
                                    <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-40" />
                                    <p className="text-muted-foreground text-xs">No conversations found</p>
                                </div>
                            </div>
                        ) : (
                            <div className="py-0.5">
                                {grouped.map(({ group, conversations: groupConvs }, groupIndex) => (
                                    <div key={group}>
                                        <div className="px-3 py-1.5 text-[11px] font-medium text-muted-foreground dark:text-zinc-500">{group}</div>
                                        {groupIndex === 0 && newChatRow}
                                        {groupConvs.map(conv => (
                                            <button
                                                key={conv.conversation_id}
                                                onClick={() => history.resume(conv.conversation_id)}
                                                onMouseEnter={() => setHoveredId(conv.conversation_id)}
                                                onMouseLeave={() => setHoveredId(null)}
                                                className={`w-full px-3 py-1.5 text-left transition-colors relative group ${
                                                    conv.conversation_id === currentConversationId
                                                        ? 'bg-accent dark:bg-zinc-800/60'
                                                        : 'hover:bg-accent/50 dark:hover:bg-zinc-900/50'
                                                }`}
                                            >
                                                <div className="flex items-start gap-2 relative pr-12">
                                                    <MessageSquare className="w-4 h-4 text-muted-foreground/70 dark:text-zinc-600 mt-0.5 flex-shrink-0" />
                                                    <div className="flex-1 min-w-0">
                                                        <div className="flex items-center gap-2">
                                                            <p className="text-[13px] text-foreground font-normal truncate">
                                                                {conv.title
                                                                    ? conv.title.length > 30
                                                                        ? conv.title.slice(0, 30) + '...'
                                                                        : conv.title
                                                                    : 'Untitled Conversation'}
                                                            </p>
                                                            {conv.app_name && (
                                                                <span
                                                                    className="inline-block text-[10px] px-1.5 py-0.5 bg-secondary/80 text-muted-foreground rounded flex-shrink-0"
                                                                    title={conv.app_name}
                                                                >
                                                                    {conv.app_name.length > 8 ? conv.app_name.slice(0, 8) + '...' : conv.app_name}
                                                                </span>
                                                            )}
                                                        </div>
                                                    </div>
                                                    <span className="absolute right-0 top-0.5 text-[11px] text-muted-foreground/70 dark:text-zinc-600 translate-x-[-24px]">
                                                        {historyTime(conv.last_activity)}
                                                    </span>
                                                    <button
                                                        onClick={(e) => {
                                                            e.stopPropagation();
                                                            void history.remove(conv.conversation_id);
                                                        }}
                                                        disabled={deletingId === conv.conversation_id}
                                                        className={`absolute right-0 top-0 p-1 text-muted-foreground/70 dark:text-zinc-600 hover:text-red-600 dark:hover:text-red-400 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed ${
                                                            hoveredId === conv.conversation_id ? 'opacity-100' : 'opacity-60'
                                                        }`}
                                                        title={deletingId === conv.conversation_id ? "Deleting..." : "Delete conversation"}
                                                    >
                                                        <Trash2 className={`w-3.5 h-3.5 ${deletingId === conv.conversation_id ? 'animate-pulse' : ''}`} />
                                                    </button>
                                                </div>
                                            </button>
                                        ))}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>,
                document.body
            )}
        </>
    );
});
