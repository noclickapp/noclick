// Centered, fully-expanded model picker for the FlowCanvas agent node.
// Replaces the node-anchored ModelDropdown popup: opens as a screen-centered
// dialog with the provider/feature filter rail always visible and keyboard
// navigation (↑↓ navigate, ↵ select, Esc close) via the shared list-nav hook.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import {
    Brain,
    Check,
    Eye,
    FilterX,
    ImagePlus,
    List,
    Search,
    Star,
    Video,
    Wrench,
} from 'lucide-react';
import { cn } from '~/lib/utils';
import { Dialog, DialogContent, DialogTitle } from '~/components/ui/dialog';
import { isCliAgentModel } from '~/lib/agentChat';
import { filterAndSortModels, modelShortName, normalizeForSearch } from '~/lib/modelFiltering';
import { bumpedIconScale } from '~/components/chat/ModelDropdown';
import { APIKeyRequestDrawer } from '~/components/chat/drawer/APIKeyRequestDrawer';
import { FAVORITE_MODELS } from '~/config/favoriteModels';
import { getProviderMetadata, type ModelProvider } from '~/types/provider';
import type { ModelWithSource } from '~/hooks/useModels';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { useListKeyboardNav } from '~/hooks/useListKeyboardNav';
import { useDrawer } from '~/hooks/useDrawer';
import { useAPIKeys } from '~/hooks/useAPIKeys';

/** Quiet inline tag on a picker row (Free, CLI Agent) — same treatment as the
 *  header's kbd hints so it reads as metadata, not a call to action. */
function RowTag({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <span
            title={title}
            className="flex-shrink-0 rounded px-1 py-px text-[10px] font-medium leading-4 bg-foreground/[0.06] text-muted-foreground"
        >
            {children}
        </span>
    );
}

const MODEL_FEATURES = [
    { key: 'imageAnalysis', label: 'Image Analysis', Icon: Eye },
    { key: 'imageGeneration', label: 'Image Generation', Icon: ImagePlus },
    { key: 'reasoning', label: 'Reasoning', Icon: Brain },
    { key: 'tools', label: 'Tool Support', Icon: Wrench },
    { key: 'videoGeneration', label: 'Video Generation', Icon: Video },
] as const;

interface ModelPickerModalProps {
    open: boolean;
    onClose: () => void;
    onModelSelect: (modelId: string) => void;
    selectedModelId: string;
    models: ModelWithSource[];
    /** Model ids pinned to the top of the list (e.g. CLI agents). */
    priorityModelIds?: readonly string[];
}

export function ModelPickerModal({ open, onClose, ...contentProps }: ModelPickerModalProps) {
    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
            {/* noAnimation: instant open/close like a command palette — also keeps
                Radix Presence from waiting on an exit animation that never fires
                when the tab is hidden. */}
            <DialogContent
                aria-describedby={undefined}
                noAnimation
                className="max-w-2xl p-0 gap-0 overflow-hidden"
            >
                <DialogTitle className="sr-only">Select model</DialogTitle>
                <ModelPickerContent onClose={onClose} {...contentProps} />
            </DialogContent>
        </Dialog>
    );
}

// All picker state lives here so it remounts fresh on every open (Radix only
// mounts DialogContent children while the dialog is open).
function ModelPickerContent({
    onClose,
    onModelSelect,
    selectedModelId,
    models,
    priorityModelIds,
}: Omit<ModelPickerModalProps, 'open'>) {
    const [searchQuery, setSearchQuery] = useState('');
    const [providerSearchQuery, setProviderSearchQuery] = useState('');
    const [selectedProviders, setSelectedProviders] = useState<Set<ModelProvider>>(new Set());
    const [selectedFeatures, setSelectedFeatures] = useState<Set<string>>(new Set());

    // Shared with the chat dropdown so view mode + favorites stay in sync.
    const [viewMode, setViewMode] = useCachedValtioState<'favorites' | 'all'>(
        'chat',
        'modelViewMode',
        'all',
    );
    const [userFavorites, setUserFavorites] = useCachedValtioState<string[]>(
        'chat',
        'favoriteModels',
        [...FAVORITE_MODELS],
    );

    const listRef = useRef<HTMLDivElement>(null);

    const { registerDrawer, unregisterDrawer } = useDrawer();
    const apiKeys = useAPIKeys();

    const filteredModels = useMemo(
        () =>
            filterAndSortModels(models || [], {
                searchQuery,
                selectedProviders,
                selectedFeatures,
                viewMode,
                userFavorites,
                priorityModelIds,
                freeFirst: true,
            }),
        [models, searchQuery, selectedProviders, selectedFeatures, viewMode, userFavorites, priorityModelIds],
    );

    // Providers backing the priority model ids (e.g. the CLI agent harnesses),
    // in priority order and deduped. Derived from the same priorityModelIds
    // that pin those models to the top of the list, so the rail and the model
    // list stay ordered the same way.
    const priorityProviders = useMemo(() => {
        const ordered: ModelProvider[] = [];
        const seen = new Set<ModelProvider>();
        for (const id of priorityModelIds || []) {
            const provider = (models || []).find((m) => m.id === id)?.provider;
            if (provider && !seen.has(provider)) {
                seen.add(provider);
                ordered.push(provider);
            }
        }
        return ordered;
    }, [models, priorityModelIds]);

    const availableProviders = useMemo(() => {
        const unique = Array.from(new Set((models || []).map((m) => m.provider)));
        const filtered = unique.filter((provider) => {
            const metadata = getProviderMetadata(provider);
            if (!metadata) return false;
            return normalizeForSearch(metadata.title).includes(
                normalizeForSearch(providerSearchQuery),
            );
        });
        // Pin harness providers to the top (in priority order); everything else
        // keeps its original relative order via the stable sort.
        const rank = (provider: ModelProvider) => {
            const i = priorityProviders.indexOf(provider);
            return i === -1 ? Number.MAX_SAFE_INTEGER : i;
        };
        return filtered.sort((a, b) => rank(a) - rank(b));
    }, [models, providerSearchQuery, priorityProviders]);

    const rowVirtualizer = useVirtualizer({
        count: filteredModels.length,
        getScrollElement: () => listRef.current,
        estimateSize: () => 36,
        overscan: 8,
    });

    // Selecting a model whose provider has no usage-based billing and missing
    // API keys opens the key-request drawer (after the modal closes).
    const pickModel = useCallback(
        (modelId: string) => {
            onModelSelect(modelId);
            onClose();

            const model = (models || []).find((m) => m.id === modelId);
            const metadata = model ? getProviderMetadata(model.provider) : undefined;
            const needsKeys =
                model &&
                metadata &&
                !metadata.allowUsageBased &&
                (metadata.requiredApiKeys?.length ?? 0) > 0 &&
                !apiKeys.hasRequiredKeys(model.provider);
            if (!needsKeys) return;

            const drawerId = `api-key-${model.provider}`;
            registerDrawer(
                drawerId,
                <APIKeyRequestDrawer
                    provider={model.provider}
                    onKeySubmit={(keys) => {
                        apiKeys.saveKeys(keys);
                        unregisterDrawer(drawerId);
                    }}
                    onClose={() => unregisterDrawer(drawerId)}
                />,
            );
        },
        [models, onModelSelect, onClose, apiKeys, registerDrawer, unregisterDrawer],
    );

    const { index: highlightedIndex, setIndex, handleKeyDown } = useListKeyboardNav({
        count: filteredModels.length,
        active: true,
        wrap: true,
        onSelect: (i) => {
            const model = filteredModels[i];
            if (model) pickModel(model.id);
        },
        onEscape: onClose,
    });

    // Scroll the highlight into view only for keyboard moves — mouse-enter
    // highlights must not yank the virtualized list (same gating idea as
    // usePickerKeyboardNav, adapted for the virtualizer).
    const keyboardNavRef = useRef(false);
    useEffect(() => {
        if (!keyboardNavRef.current) return;
        keyboardNavRef.current = false;
        rowVirtualizer.scrollToIndex(highlightedIndex);
    }, [highlightedIndex, rowVirtualizer]);

    // Arrows/Enter/Esc are consumed here; stop them hard so canvas-level
    // native listeners (ReactFlow shortcuts) never see them.
    const handleSearchKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            keyboardNavRef.current = true;
        }
        handleKeyDown(e);
        if (e.defaultPrevented) {
            e.stopPropagation();
            e.nativeEvent.stopImmediatePropagation();
        }
    };

    // On open: start the highlight on the current model, centered. Runs in a
    // plain effect (NOT rAF — rAF stalls in hidden tabs and can fire after the
    // user already typed, clobbering the highlight reset).
    useEffect(() => {
        const selectedIndex = filteredModels.findIndex((m) => m.id === selectedModelId);
        if (selectedIndex >= 0) {
            setIndex(selectedIndex);
            rowVirtualizer.scrollToIndex(selectedIndex, { align: 'center' });
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Reset the highlight to the top whenever the visible set changes.
    const isFirstRender = useRef(true);
    useEffect(() => {
        if (isFirstRender.current) {
            isFirstRender.current = false;
            return;
        }
        setIndex(0);
        rowVirtualizer.scrollToIndex(0, { align: 'start' });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [searchQuery, selectedProviders, selectedFeatures, viewMode]);

    const toggleProvider = (provider: ModelProvider) => {
        setSelectedProviders((prev) => {
            const next = new Set(prev);
            if (next.has(provider)) next.delete(provider);
            else next.add(provider);
            return next;
        });
    };

    const toggleFeature = (feature: string) => {
        setSelectedFeatures((prev) => {
            const next = new Set(prev);
            if (next.has(feature)) next.delete(feature);
            else next.add(feature);
            return next;
        });
    };

    const toggleFavorite = (modelId: string, e: React.MouseEvent) => {
        e.stopPropagation();
        setUserFavorites((prev) =>
            prev.includes(modelId) ? prev.filter((id) => id !== modelId) : [...prev, modelId],
        );
    };

    const switchViewMode = (mode: 'favorites' | 'all') => {
        if (mode === viewMode) return;
        setViewMode(mode);
        setSearchQuery('');
        setSelectedProviders(new Set());
        setSelectedFeatures(new Set());
    };

    const hasActiveFilters = selectedProviders.size > 0 || selectedFeatures.size > 0;

    return (
        <div data-testid="model-picker-modal" className="flex h-[min(560px,75vh)] flex-col">
            {/* Search header — pr leaves room for the dialog's built-in close X */}
            <div className="flex items-center gap-2.5 border-b border-border/30 dark:border-zinc-700/30 px-4 py-3 pr-14 flex-shrink-0">
                <Search className="h-4 w-4 flex-shrink-0 text-muted-foreground dark:text-zinc-500" />
                <input
                    data-testid="model-picker-search"
                    // eslint-disable-next-line jsx-a11y/no-autofocus
                    autoFocus
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={handleSearchKeyDown}
                    placeholder="Search models…"
                    className="flex-1 bg-transparent text-sm text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none"
                />
                <div className="hidden sm:flex items-center gap-3 text-[10px] text-muted-foreground dark:text-zinc-500 flex-shrink-0">
                    <span>
                        <kbd className="px-1 py-0.5 bg-foreground/[0.06] rounded">↑↓</kbd> navigate
                    </span>
                    <span>
                        <kbd className="px-1 py-0.5 bg-foreground/[0.06] rounded">↵</kbd> select
                    </span>
                    <span>
                        <kbd className="px-1 py-0.5 bg-foreground/[0.06] rounded">esc</kbd> close
                    </span>
                </div>
            </div>

            <div className="flex flex-1 min-h-0">
                {/* Filter rail — always expanded */}
                <div className="w-52 flex-shrink-0 border-r border-border/30 dark:border-zinc-700/30 flex flex-col min-h-0">
                    <div className="flex items-center justify-between px-3 pt-3 pb-1.5 flex-shrink-0">
                        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                            Providers
                        </span>
                        {hasActiveFilters && (
                            <button
                                onClick={() => {
                                    setSelectedProviders(new Set());
                                    setSelectedFeatures(new Set());
                                }}
                                className="p-1 rounded text-red-600 dark:text-red-400 hover:text-red-300 hover:bg-red-500/10 transition-colors"
                                title="Clear all filters"
                            >
                                <FilterX className="h-3.5 w-3.5" />
                            </button>
                        )}
                    </div>
                    <div className="mx-3 mb-1.5 flex flex-shrink-0 items-center gap-1.5 rounded-md bg-foreground/[0.04] px-2 py-1 transition-colors focus-within:bg-muted dark:focus-within:bg-white/[0.07]">
                        <Search className="h-3 w-3 flex-shrink-0 text-muted-foreground dark:text-zinc-500" />
                        <input
                            type="text"
                            value={providerSearchQuery}
                            onChange={(e) => setProviderSearchQuery(e.target.value)}
                            placeholder="Filter providers…"
                            className="w-full min-w-0 bg-transparent text-xs text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none"
                        />
                    </div>
                    <div className="flex-1 overflow-y-auto scrollbar-subtle px-2 pb-2 min-h-0">
                        {availableProviders.length === 0 ? (
                            <div className="px-2 py-3 text-center text-xs text-muted-foreground dark:text-zinc-500">
                                No providers found
                            </div>
                        ) : (
                            availableProviders.map((provider) => {
                                const metadata = getProviderMetadata(provider);
                                if (!metadata) return null;
                                const isSelected = selectedProviders.has(provider);
                                return (
                                    <button
                                        key={provider}
                                        onClick={() => toggleProvider(provider)}
                                        className={cn(
                                            'mb-0.5 flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs transition-colors',
                                            isSelected
                                                ? 'bg-secondary dark:bg-zinc-700/50 text-foreground'
                                                : 'text-muted-foreground hover:bg-accent dark:hover:bg-zinc-700/30 hover:text-foreground',
                                        )}
                                    >
                                        <div className="flex h-4 w-4 flex-shrink-0 items-center justify-center">
                                            <div style={{ transform: `scale(${bumpedIconScale(provider, 0.5)})` }}>
                                                {metadata.icon}
                                            </div>
                                        </div>
                                        <span className="truncate flex-1">{metadata.title}</span>
                                        {isSelected && (
                                            <Check className="h-3 w-3 flex-shrink-0 text-foreground" />
                                        )}
                                    </button>
                                );
                            })
                        )}
                    </div>
                    <div className="border-t border-border/30 dark:border-zinc-700/30 px-2 py-2 flex-shrink-0">
                        <span className="block px-1 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                            Features
                        </span>
                        {MODEL_FEATURES.map(({ key, label, Icon }) => {
                            const isSelected = selectedFeatures.has(key);
                            return (
                                <button
                                    key={key}
                                    onClick={() => toggleFeature(key)}
                                    className={cn(
                                        'mb-0.5 flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs transition-colors',
                                        isSelected
                                            ? 'bg-secondary dark:bg-zinc-700/50 text-foreground'
                                            : 'text-muted-foreground hover:bg-accent dark:hover:bg-zinc-700/30 hover:text-foreground',
                                    )}
                                >
                                    <Icon className="h-3.5 w-3.5 flex-shrink-0 text-zinc-400/80" />
                                    <span className="flex-1">{label}</span>
                                    {isSelected && (
                                        <Check className="h-3 w-3 flex-shrink-0 text-foreground" />
                                    )}
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* Model list — virtualized */}
                <div className="flex-1 min-w-0 min-h-0">
                    {filteredModels.length === 0 ? (
                        <div className="px-4 py-12 text-center text-sm text-muted-foreground dark:text-zinc-500">
                            {models?.length ? 'No models found' : 'Loading models…'}
                        </div>
                    ) : (
                        <div ref={listRef} className="h-full overflow-y-auto scrollbar-subtle">
                            <div
                                style={{
                                    height: `${rowVirtualizer.getTotalSize()}px`,
                                    width: '100%',
                                    position: 'relative',
                                }}
                            >
                                {rowVirtualizer.getVirtualItems().map((virtualItem) => {
                                    const model = filteredModels[virtualItem.index];
                                    const providerMetadata = getProviderMetadata(model.provider);
                                    if (!providerMetadata) return null;
                                    const isCurrentlySelected = model.id === selectedModelId;
                                    const isHighlighted = highlightedIndex === virtualItem.index;
                                    const isFavorite = userFavorites.includes(model.id);
                                    return (
                                        // Keyboard interaction lives on the search input
                                        // (combobox pattern); rows are pointer targets.
                                        <div
                                            key={virtualItem.key}
                                            role="option"
                                            aria-selected={isCurrentlySelected}
                                            tabIndex={-1}
                                            style={{
                                                position: 'absolute',
                                                top: 0,
                                                left: 0,
                                                width: '100%',
                                                height: `${virtualItem.size}px`,
                                                transform: `translateY(${virtualItem.start}px)`,
                                            }}
                                            onClick={() => pickModel(model.id)}
                                            onKeyDown={(e) => e.key === 'Enter' && pickModel(model.id)}
                                            onMouseEnter={() => setIndex(virtualItem.index)}
                                            className={cn(
                                                'flex cursor-pointer items-center gap-2 px-3 text-sm transition-colors',
                                                isHighlighted
                                                    ? 'bg-secondary dark:bg-zinc-700/50 text-foreground'
                                                    : isCurrentlySelected
                                                      ? 'bg-secondary dark:bg-zinc-700/30 text-foreground/80'
                                                      : 'text-muted-foreground',
                                            )}
                                        >
                                            <div className="flex h-5 w-5 flex-shrink-0 items-center justify-center">
                                                <div
                                                    className="opacity-80"
                                                    style={{ transform: `scale(${bumpedIconScale(model.provider, 0.55)})` }}
                                                >
                                                    {providerMetadata.icon}
                                                </div>
                                            </div>
                                            <span className={cn('truncate flex-1', isCurrentlySelected && 'font-medium')}>
                                                {modelShortName(model.id)}
                                            </span>
                                            {isCliAgentModel(model.id) && (
                                                <RowTag title="Full coding-agent CLI running in a sandbox — not a single model">
                                                    CLI Agent
                                                </RowTag>
                                            )}
                                            {model.free && (
                                                <RowTag title="Served at $0 by the provider">
                                                    Free
                                                </RowTag>
                                            )}
                                            {model.capabilities && (
                                                <div className="flex flex-shrink-0 items-center gap-1.5">
                                                    {MODEL_FEATURES.filter(
                                                        ({ key }) => model.capabilities?.[key],
                                                    ).map(({ key, label, Icon }) => (
                                                        <span
                                                            key={key}
                                                            title={label}
                                                            className="inline-flex items-center"
                                                        >
                                                            <Icon className="h-3 w-3 text-zinc-400/80" />
                                                        </span>
                                                    ))}
                                                </div>
                                            )}
                                            {isCurrentlySelected && (
                                                <Check className="h-3 w-3 flex-shrink-0 text-muted-foreground dark:text-white/70" />
                                            )}
                                            <button
                                                onClick={(e) => toggleFavorite(model.id, e)}
                                                className={cn(
                                                    'rounded p-0.5 transition-colors hover:bg-zinc-600/50',
                                                    isFavorite
                                                        ? 'text-yellow-600 dark:text-yellow-400'
                                                        : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80',
                                                )}
                                                title={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
                                            >
                                                <Star className={cn('h-3 w-3', isFavorite && 'fill-current')} />
                                            </button>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Footer: view-mode toggle + result count */}
            <div className="flex items-center justify-between border-t border-border/30 dark:border-zinc-700/30 px-4 py-2 flex-shrink-0">
                <div className="flex items-center gap-0.5 rounded-lg border border-border bg-muted p-0.5 dark:border-foreground/[0.08] dark:bg-foreground/[0.02]">
                    <button
                        onClick={() => switchViewMode('all')}
                        className={cn(
                            'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors',
                            viewMode === 'all'
                                ? 'bg-card text-foreground shadow-sm dark:bg-foreground/[0.08] dark:text-foreground/90 dark:shadow-none'
                                : 'text-foreground/50 hover:text-foreground/70',
                        )}
                    >
                        <List className="h-3.5 w-3.5" />
                        <span className="font-medium">All</span>
                    </button>
                    <button
                        onClick={() => switchViewMode('favorites')}
                        className={cn(
                            'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors',
                            viewMode === 'favorites'
                                ? 'bg-card text-foreground shadow-sm dark:bg-foreground/[0.08] dark:text-foreground/90 dark:shadow-none'
                                : 'text-foreground/50 hover:text-foreground/70',
                        )}
                    >
                        <Star className="h-3.5 w-3.5" />
                        <span className="font-medium">Favorites</span>
                    </button>
                </div>
                <span className="text-xs text-muted-foreground dark:text-zinc-500">
                    {filteredModels.length} {filteredModels.length === 1 ? 'model' : 'models'}
                </span>
            </div>
        </div>
    );
}
