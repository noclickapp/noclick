// Context options drawer that displays available context when user types @
// Shows filterable list of context items (files, data, conversations, etc.)
// Inserts selected context at cursor position

import { useState, useEffect, useCallback, useMemo } from 'react';
import { cn } from '~/lib/utils';
import {
    FileText,
    Database,
    MessageSquare,
    Clipboard,
    Globe
} from 'lucide-react';
import { useAnalytics } from '~/lib/analytics';

export interface ContextOption {
    id: string;
    label: string;
    description: string;
    icon: React.ComponentType<{ className?: string }>;
    value: string; // what gets inserted when selected
}

interface ChatContextOptionsProps {
    query: string; // text after @ for filtering
    onContextSelect: (option: ContextOption) => void;
    onClose: () => void;
}

// TODO: this needs to be updated to database/workflows/apps list
const contextOptions: ContextOption[] = [
    {
        id: 'files',
        label: 'Files & Documents',
        description: 'Reference uploaded files',
        icon: FileText,
        value: 'My Files'
    },
    {
        id: 'data',
        label: 'Data Sources',
        description: 'Reference data connections',
        icon: Database,
        value: 'Data Sources'
    },
    {
        id: 'conversations',
        label: 'Previous Conversations',
        description: 'Reference past chats',
        icon: MessageSquare,
        value: 'Past Chats'
    },
    {
        id: 'clipboard',
        label: 'Clipboard Content',
        description: 'Insert clipboard',
        icon: Clipboard,
        value: 'Clipboard Content'
    },
    {
        id: 'web',
        label: 'Web Pages',
        description: 'Reference URLs',
        icon: Globe,
        value: 'Web Pages'
    }
];

export function ChatContextOptions({
    query,
    onContextSelect,
    onClose
}: ChatContextOptionsProps) {
    const [selectedIndex, setSelectedIndex] = useState(0);
    const { logActivity } = useAnalytics();

    // Filter options based on query
    const filteredOptions = useMemo(() => {
        if (!query || query.trim() === '') {
            return contextOptions;
        }

        const searchQuery = query.toLowerCase().trim();
        return contextOptions.filter(option =>
            option.label.toLowerCase().includes(searchQuery) ||
            option.description.toLowerCase().includes(searchQuery) ||
            option.value.toLowerCase().includes(searchQuery)
        );
    }, [query]);

    // Reset selection when filtered options change
    useEffect(() => {
        setSelectedIndex(0);
    }, [filteredOptions]);

    // Scroll selected item into view
    useEffect(() => {
        if (selectedIndex >= 0 && filteredOptions.length > 0) {
            requestAnimationFrame(() => {
                const container = document.querySelector('.context-options-list');
                const buttons = container?.querySelectorAll('button');
                const selectedButton = buttons?.[selectedIndex] as HTMLElement;
                if (selectedButton) {
                    selectedButton.scrollIntoView({
                        block: 'nearest',
                        behavior: 'smooth'
                    });
                }
            });
        }
    }, [selectedIndex, filteredOptions.length]);

    // Handle keyboard navigation
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            switch (e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    setSelectedIndex(prev =>
                        prev < filteredOptions.length - 1 ? prev + 1 : 0
                    );
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    setSelectedIndex(prev =>
                        prev > 0 ? prev - 1 : filteredOptions.length - 1
                    );
                    break;
                case 'Enter':
                    e.preventDefault();
                    if (filteredOptions[selectedIndex]) {
                        handleOptionSelect(filteredOptions[selectedIndex]);
                    }
                    break;
                case 'Escape':
                    e.preventDefault();
                    onClose();
                    break;
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [filteredOptions, selectedIndex, onClose]);

    const handleOptionSelect = useCallback((option: ContextOption) => {
        logActivity('context_option_selected', {
            option_id: option.id,
            option_label: option.label,
            query: query
        });
        onContextSelect(option);
    }, [onContextSelect, query, logActivity]);

    const handleOptionClick = useCallback((option: ContextOption, index: number) => {
        setSelectedIndex(index);
        handleOptionSelect(option);
    }, [handleOptionSelect]);

    if (filteredOptions.length === 0) {
        return (
            <div className="py-3 text-center text-muted-foreground dark:text-zinc-500">
                <p className="text-xs">No context found</p>
                <p className="text-[10px] mt-0.5 text-muted-foreground/70 dark:text-zinc-600">Try typing a different query</p>
            </div>
        );
    }

    return (
        <div className="flex flex-col w-full">
            {/* Scrollable content area */}
            <div className="max-h-[calc(35vh-4rem)] overflow-y-auto scrollbar-subtle px-2 context-options-list">
                <div className="py-1">
                    {/* Header */}
                    <div className="mb-1 flex items-center justify-between">
                        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                            Context
                        </h3>
                    </div>

                    <div className="space-y-0.5">
                        {filteredOptions.map((option, index) => {
                            const Icon = option.icon;

                            return (
                                <button
                                    key={option.id}
                                    onClick={(e) => {
                                        e.preventDefault();
                                        e.stopPropagation();
                                        handleOptionClick(option, index);
                                    }}
                                    onMouseEnter={() => setSelectedIndex(index)}
                                    className={cn(
                                        'w-full flex items-center gap-2 px-2 py-1 rounded-md transition-all duration-150',
                                        'text-left group cursor-pointer',
                                        selectedIndex === index
                                            ? 'bg-accent dark:bg-zinc-700/70 text-foreground'
                                            : 'text-muted-foreground hover:bg-accent/60 dark:hover:bg-zinc-700/40 hover:text-foreground'
                                    )}
                                    style={{ pointerEvents: 'auto' }}
                                >
                                    <Icon className={cn(
                                        'w-3.5 h-3.5 flex-shrink-0',
                                        selectedIndex === index ? 'text-blue-600 dark:text-blue-400' : 'text-muted-foreground dark:text-zinc-500'
                                    )} />

                                    <div className="flex items-center justify-between flex-1 min-w-0 overflow-hidden">
                                        <span className={cn(
                                            'text-xs font-medium flex-shrink-0',
                                            selectedIndex === index ? 'text-foreground' : 'text-foreground/80'
                                        )}>
                                            {option.label}
                                        </span>
                                        <span className={cn(
                                            'text-xs truncate ml-2',
                                            selectedIndex === index ? 'text-foreground/80' : 'text-muted-foreground dark:text-zinc-500'
                                        )}>
                                            {option.description}
                                        </span>
                                    </div>
                                </button>
                            );
                        })}
                    </div>
                </div>
            </div>

            {/* Fixed footer */}
            <div className="border-t border-border dark:border-zinc-700/50 pt-1 pb-2 px-2 flex-shrink-0 bg-popover/80 dark:bg-zinc-800/80">
                <div className="flex items-center gap-2 text-xs text-muted-foreground dark:text-zinc-500">
                    <span className="flex items-center gap-1">
                        <kbd className="px-1 py-0 bg-muted dark:bg-zinc-700/50 rounded text-xs text-muted-foreground">↑↓</kbd>
                        Navigate
                    </span>
                    <span className="flex items-center gap-1">
                        <kbd className="px-1 py-0 bg-muted dark:bg-zinc-700/50 rounded text-xs text-muted-foreground">⏎</kbd>
                        Select
                    </span>
                    <span className="flex items-center gap-1">
                        <kbd className="px-1 py-0 bg-muted dark:bg-zinc-700/50 rounded text-xs text-muted-foreground">Esc</kbd>
                        Close
                    </span>
                </div>
            </div>
        </div>
    );
}
