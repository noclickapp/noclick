/*
Chat History dropdown component matching the reference design.
Displays grouped conversations with search, time-based grouping, and clean UI.

Caching behavior:
- Conversations are cached using useCachedValtioState for instant loading
- Cached data is stored in IndexedDB and synced across tabs
- When dropdown opens, cached data displays immediately while fresh data loads in background
- Fresh data from backend automatically updates the cache
*/

import { useState, useEffect, useCallback, useRef, memo } from 'react';
import { createPortal } from 'react-dom';
import { Clock, Trash2, Plus, MessageSquare } from 'lucide-react';
import { useSocketEvent } from '~/hooks/useSocketEvent';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { useConversationCache } from '~/hooks/useConversationCache';
import { sendEvent, sendEventAsync, ListConversationsRequest, DeleteConversationRequest, ResumeConversationRequest } from '~/lib/socket-sender';
import type { ConversationListEvent, ConversationResumeEvent } from '~/types/socket-events.generated';
import { mapPersistedMessages } from '~/hooks/conversationRestoreMapping';
import { fuzzyFilter } from '~/utils/fuzzySearch';

interface Conversation {
    conversation_id: string;
    title: string;
    preview: string;
    last_activity: string;
    created_at: string;
    app_id?: string;
    app_name?: string;
}

interface ChatHistoryProps {
    currentConversationId: string;
    onConversationChange: (conversationId: string, messages: any[]) => void;
}

export const ChatHistory = memo(function ChatHistory({
    currentConversationId,
    onConversationChange
}: ChatHistoryProps) {
    const [isOpen, setIsOpen] = useState(false);
    // Use cached valtio state for instant loading from cache while fetching fresh data
    const [conversations, setConversations] = useCachedValtioState<Conversation[]>(
        'chat-history',
        'conversations',
        []
    );
    const [searchQuery, setSearchQuery] = useState('');
    const [hoveredId, setHoveredId] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [deletingId, setDeletingId] = useState<string | null>(null);
    const buttonRef = useRef<HTMLDivElement>(null);
    const dropdownRef = useRef<HTMLDivElement>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);

    // Access conversation cache for instant loading of previously viewed conversations
    const { getFromCache, addToCache } = useConversationCache();

    // Handle conversation list response
    useSocketEvent('conversations:list', useCallback((data: ConversationListEvent) => {
        console.log('[ChatHistory] Received conversations:', data);
        setConversations(data.conversations as unknown as Conversation[]);
        setIsLoading(false);
    }, [setConversations]));

    // The backend now sends ResponseEvent for resume requests
    // handleResumeConversation now uses sendEventAsync to get the response

    // Load conversations when dropdown opens
    useEffect(() => {
        if (isOpen) {
            console.log('[ChatHistory] Loading conversations...');
            setIsLoading(true);
            sendEvent(ListConversationsRequest.create({
                request_id: crypto.randomUUID(),
                tag: 'Loading conversations',
            }));

            // Auto-focus search input
            setTimeout(() => {
                searchInputRef.current?.focus();
            }, 100);

            const timeout = setTimeout(() => {
                if (isLoading) {
                    console.warn('[ChatHistory] Request timed out');
                    setIsLoading(false);
                }
            }, 5000);

            return () => clearTimeout(timeout);
        }
    }, [isOpen]);

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node;
            const clickedOutsideButton = buttonRef.current && !buttonRef.current.contains(target);
            const clickedOutsideDropdown = dropdownRef.current && !dropdownRef.current.contains(target);

            if (clickedOutsideButton && clickedOutsideDropdown) {
                setIsOpen(false);
            }
        };

        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside);
        }

        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [isOpen]);

    const filteredConversations = fuzzyFilter(conversations, searchQuery, conv => [
        { text: (conv.title ?? '').toLowerCase(), weight: 1, fuzzy: true },
        { text: (conv.app_name ?? '').toLowerCase(), weight: 0.6, fuzzy: true },
        { text: (conv.preview ?? '').toLowerCase(), weight: 0.4 },
    ]);

    // Group conversations by time period and sort by most recent first
    const groupedConversations = filteredConversations.reduce((groups, conv) => {
        const lastActivity = new Date(conv.last_activity);
        const now = new Date();
        const diffDays = Math.floor((now.getTime() - lastActivity.getTime()) / (1000 * 60 * 60 * 24));

        let group = 'Older';
        if (diffDays === 0) group = 'Today';
        else if (diffDays === 1) group = 'Yesterday';
        else if (diffDays <= 7) group = 'Last 7 Days';
        else if (diffDays <= 30) group = 'Last 30 Days';

        if (!groups[group]) groups[group] = [];
        groups[group].push(conv);
        return groups;
    }, {} as Record<string, Conversation[]>);

    // Sort conversations within each group by last_activity (most recent first)
    Object.keys(groupedConversations).forEach(group => {
        groupedConversations[group].sort((a, b) =>
            new Date(b.last_activity).getTime() - new Date(a.last_activity).getTime()
        );
    });

    const groupOrder = ['Today', 'Yesterday', 'Last 7 Days', 'Last 30 Days', 'Older'];

    const formatTime = (isoString: string) => {
        const date = new Date(isoString);
        const now = new Date();
        const diffMinutes = Math.floor((now.getTime() - date.getTime()) / (1000 * 60));

        if (diffMinutes < 1) return 'now';
        if (diffMinutes < 60) return `${diffMinutes}m`;

        const diffHours = Math.floor(diffMinutes / 60);
        if (diffHours < 24) return `${diffHours}h`;

        const diffDays = Math.floor(diffHours / 24);
        if (diffDays === 1) return '1d';
        if (diffDays < 7) return `${diffDays}d`;
        if (diffDays < 14) return '1w';
        if (diffDays < 30) return `${Math.floor(diffDays / 7)}w`;

        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    };

    const handleResumeConversation = async (conversationId: string) => {
        console.log('[ChatHistory] Resuming conversation:', conversationId);
        try {
            // Check conversation cache first for instant loading
            // This cache is populated when conversations are loaded (via cacheCurrentConversation)
            const cached = getFromCache(conversationId);
            if (cached) {
                console.log('[ChatHistory] Cache hit! Using cached conversation');
                // Convert cached Message[] format to the format expected by onConversationChange
                const restoredMessages = cached.messages.map(msg => ({
                    text: msg.text,
                    isUser: msg.isUser,
                    isComplete: true,
                    content: msg.content || undefined,
                    agenticSteps: msg.agenticSteps,
                    editSegments: msg.editSegments,
                    editSteps: msg.editSteps,
                }));
        
                onConversationChange(conversationId, restoredMessages);
                setIsOpen(false);
                return;
            }
        
            // Cache miss — fetch from backend
            console.log('[ChatHistory] Cache miss, fetching from backend');
            const response = await sendEventAsync<ConversationResumeEvent>({
                event_name: 'conversation:resume',
                session_id: conversationId
            });
        
            console.log('[ChatHistory] Received resume response');
        
            const restoredMessages = mapPersistedMessages(response.messages);
        
            onConversationChange(response.session_id, restoredMessages);
            setIsOpen(false);
        } catch (error) {
            console.error('[ChatHistory] Failed to resume conversation', error);
        } 
    };

    const handleNewConversation = () => {
        const newConversationId = globalThis.crypto?.randomUUID?.() || Math.random().toString(36);
        console.log('[ChatHistory] New conversation:', newConversationId);
        onConversationChange(newConversationId, [
            { text: 'How can I help?', isUser: false, isComplete: true }
        ]);
        setIsOpen(false);
    };

    const handleDeleteConversation = async (conversationId: string) => {
        try {
            setDeletingId(conversationId);
            console.log('[ChatHistory] Deleting conversation:', conversationId);

            // Response is the data field from ResponseEvent: {success: boolean, conversation_id?: string}
            const response = await sendEventAsync(
                DeleteConversationRequest.create({ conversation_id: conversationId })
            );

            console.log('[ChatHistory] Delete response:', response);

            if ((response as any).success) {
                console.log('[ChatHistory] Delete successful');
                // Remove from local state immediately
                setConversations(prev => prev.filter(conv => conv.conversation_id !== conversationId));

                // If we deleted the current conversation, start a new one
                if (conversationId === currentConversationId) {
                    handleNewConversation();
                }
            } else {
                console.error('[ChatHistory] Delete failed:', response);
            }
        } catch (error) {
            console.error('[ChatHistory] Error deleting conversation:', error);
            // TODO: Show error toast to user
        } finally {
            setDeletingId(null);
        }
    };

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
                    {/* Header with Search */}
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
                                onClick={handleNewConversation}
                                className="flex items-center justify-center p-1.5 text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-accent dark:hover:bg-zinc-800/50 rounded-full transition-colors flex-shrink-0"
                                title="New Chat"
                            >
                                <Plus className="w-4 h-4" />
                            </button>
                        </div>
                    </div>

                    {/* Conversations List */}
                    <div className="flex-1 min-h-0 overflow-y-auto scrollbar-subtle">
                        {isLoading && conversations.length === 0 ? (
                            <div className="p-8 text-center text-muted-foreground dark:text-zinc-500 text-sm">
                                <Clock className="w-8 h-8 mx-auto mb-2 opacity-40 animate-spin" />
                                <p className="text-muted-foreground text-xs">Loading conversations...</p>
                            </div>
                        ) : filteredConversations.length === 0 ? (
                            <div>
                                <div className="py-0.5">
                                    <div className="px-3 py-1.5 text-[11px] font-medium text-muted-foreground dark:text-zinc-500">
                                        Today
                                    </div>
                                    <button
                                        onClick={handleNewConversation}
                                        className="w-full px-3 py-1.5 text-left hover:bg-accent/50 dark:hover:bg-zinc-900/50 transition-colors group"
                                    >
                                        <div className="flex items-start gap-2">
                                            <Plus className="w-4 h-4 text-muted-foreground/70 dark:text-zinc-600 mt-0.5 flex-shrink-0" />
                                            <div className="flex-1 min-w-0">
                                                <p className="text-[13px] text-muted-foreground font-normal">
                                                    New Chat
                                                </p>
                                            </div>
                                        </div>
                                    </button>
                                </div>
                                <div className="p-8 text-center text-muted-foreground dark:text-zinc-500 text-sm">
                                    <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-40" />
                                    <p className="text-muted-foreground text-xs">No conversations found</p>
                                </div>
                            </div>
                        ) : (
                            <div className="py-0.5">
                                {groupOrder.map((group, groupIndex) => {
                                    const groupConvs = groupedConversations[group];
                                    if (!groupConvs || groupConvs.length === 0) return null;

                                    return (
                                        <div key={group}>
                                            <div className="px-3 py-1.5 text-[11px] font-medium text-muted-foreground dark:text-zinc-500">
                                                {group}
                                            </div>

                                            {/* New Chat button - show as first item in first group */}
                                            {groupIndex === 0 && (
                                                <button
                                                    onClick={handleNewConversation}
                                                    className="w-full px-3 py-1.5 text-left hover:bg-accent/50 dark:hover:bg-zinc-900/50 transition-colors group"
                                                >
                                                    <div className="flex items-start gap-2">
                                                        <Plus className="w-4 h-4 text-muted-foreground/70 dark:text-zinc-600 mt-0.5 flex-shrink-0" />
                                                        <div className="flex-1 min-w-0">
                                                            <p className="text-[13px] text-muted-foreground font-normal">
                                                                New Chat
                                                            </p>
                                                        </div>
                                                    </div>
                                                </button>
                                            )}

                                            {groupConvs.map(conv => (
                                                <button
                                                    key={conv.conversation_id}
                                                    onClick={() => handleResumeConversation(conv.conversation_id)}
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
                                                                        {conv.app_name.length > 8
                                                                            ? conv.app_name.slice(0, 8) + '...'
                                                                            : conv.app_name}
                                                                    </span>
                                                                )}
                                                            </div>
                                                        </div>

                                                        {/* Timestamp - shifted left to make room for delete button */}
                                                        <span className="absolute right-0 top-0.5 text-[11px] text-muted-foreground/70 dark:text-zinc-600 translate-x-[-24px]">
                                                            {formatTime(conv.last_activity)}
                                                        </span>

                                                        {/* Delete button - fades in on hover */}
                                                        <button
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                handleDeleteConversation(conv.conversation_id);
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
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </div>,
                document.body
            )}
        </>
    );
});
