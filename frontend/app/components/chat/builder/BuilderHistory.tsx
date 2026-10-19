// Every chat with the builder, in place of the open one: newest first, grouped by when, searchable, each opening on
// a tap or deleted from its row. A new chat is the header's (one control, one way). A chat about another automation
// names it.
import { useEffect, useRef, useState } from 'react';
import { Search, Trash2 } from 'lucide-react';
import { FIELD } from '~/components/shell/fields';
import { AutomationMark } from '~/components/shell/glyphs';
import { cn } from '~/lib/utils';
import { historyTime, useChatHistory, type Conversation } from '../ChatHistory';
import type { Message } from '../types';

/** A row's words. A title cut from the request it previews reads as that request, once, cut where the row ends. */
export function historyRowWords(chat: Pick<Conversation, 'title' | 'preview'>): { title: string; preview?: string } {
    if (chat.title && chat.preview?.startsWith(chat.title)) return { title: chat.preview };
    return { title: chat.title || 'Untitled chat', preview: chat.preview || undefined };
}

function RowWords({ chat }: { chat: Conversation }) {
    const { title, preview } = historyRowWords(chat);
    return (
        <>
            <span className="block truncate text-[14px] leading-5 text-foreground">{title}</span>
            {preview && <span className="block truncate text-[12.5px] leading-[18px] text-muted-foreground">{preview}</span>}
        </>
    );
}

export function BuilderHistory({
    currentConversationId,
    workflowName,
    onConversationChange,
    onDone,
}: {
    currentConversationId: string;
    workflowName?: string;
    onConversationChange: (conversationId: string, messages: Message[]) => void;
    /** A chat opened or started: back to it. */
    onDone: () => void;
}) {
    const { grouped, conversations, searchQuery, setSearchQuery, isLoading, deletingId, resume, remove } = useChatHistory({
        currentConversationId,
        onConversationChange,
        active: true,
        onDone,
    });
    const search = useRef<HTMLInputElement>(null);
    const [pointerFine] = useState(() => typeof window !== 'undefined' && window.matchMedia('(pointer: fine)').matches);
    useEffect(() => {
        if (pointerFine) search.current?.focus();
    }, [pointerFine]);
    return (
        <div className="tl-open flex min-h-0 flex-1 flex-col" data-testid="builder-history-list">
            <div className="px-4 pb-2">
                <label className="relative block">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" strokeWidth={1.75} />
                    <input ref={search} value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search chats" className={cn(FIELD, 'h-9 rounded-full pl-9 text-[13.5px]')} />
                </label>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4 scrollbar-subtle">
                {grouped.length === 0 ? (
                    <p className="px-3 py-6 text-center text-[13px] text-muted-foreground">
                        {isLoading && conversations.length === 0 ? 'Loading your chats' : searchQuery ? `No chat matches “${searchQuery}”` : 'No chats yet'}
                    </p>
                ) : (
                    grouped.map(({ group, conversations: chats }) => (
                        <section key={group} className="mt-1 first:mt-0">
                            <h4 className="px-2.5 pb-1 pt-2 text-[12px] text-muted-foreground">{group}</h4>
                            {chats.map((chat) => (
                                <div
                                    key={chat.conversation_id}
                                    className={cn(
                                        'group relative flex items-start gap-3 rounded-xl px-2.5 py-2 transition-colors',
                                        chat.conversation_id === currentConversationId ? 'bg-foreground/[0.06]' : 'hover:bg-foreground/[0.04]'
                                    )}
                                >
                                    <button type="button" onClick={() => void resume(chat.conversation_id)} className="absolute inset-0 rounded-xl" aria-label={chat.title || 'Untitled chat'} />
                                    <span className="pointer-events-none min-w-0 flex-1 [@media(hover:none)]:pr-7">
                                        <RowWords chat={chat} />
                                        {chat.app_name && chat.app_name !== workflowName && (
                                            <span className="mt-1 inline-flex items-center gap-1.5 text-[12px] text-muted-foreground">
                                                <AutomationMark className="h-3.5 w-3.5" />
                                                {chat.app_name}
                                            </span>
                                        )}
                                    </span>
                                    <span className="pointer-events-none shrink-0 pt-px text-[12px] tabular-nums text-muted-foreground/70 group-hover:invisible [@media(hover:none)]:hidden">{historyTime(chat.last_activity)}</span>
                                    <button
                                        type="button"
                                        onClick={() => void remove(chat.conversation_id)}
                                        disabled={deletingId === chat.conversation_id}
                                        aria-label="Delete chat"
                                        className="absolute right-2 top-1.5 hidden h-7 w-7 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-foreground/[0.06] hover:text-red-600 group-hover:flex disabled:opacity-50 dark:hover:text-red-400 [@media(hover:none)]:flex"
                                    >
                                        <Trash2 className={cn('h-3.5 w-3.5', deletingId === chat.conversation_id && 'animate-pulse')} />
                                    </button>
                                </div>
                            ))}
                        </section>
                    ))
                )}
            </div>
        </div>
    );
}
