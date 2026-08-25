import { useState, useEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useVirtualizer } from '@tanstack/react-virtual';
import { cn } from '~/lib/utils';
import { filterAndSortModels, normalizeForSearch } from '~/lib/modelFiltering';
import { useDrawer } from '~/hooks/useDrawer';
import { useAPIKeys } from '~/hooks/useAPIKeys';
import { getProviderMetadata, ModelProvider } from '~/types/provider';
import { Search, ChevronDown, Check, Star, List, Edit3, Trash2, Eye, ImagePlus, Brain, Wrench, Video, Filter, FilterX, ChevronUp, ChevronDown as ChevronDownIcon } from 'lucide-react';
import { APIKeyRequestDrawer } from '~/components/chat/drawer/APIKeyRequestDrawer';
import { FAVORITE_MODELS } from '~/config/favoriteModels';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';

interface ModelDropdownProps {
    isOpen: boolean;
    onToggle: () => void;
    onModelSelect: (modelId: string) => void;
    selectedModelId: string;
    models: any[];
    isRecording?: boolean;
    className?: string;
    isDemo?: boolean;
}

// OpenClaw's claw marker is transparent line-art in a padded viewBox, so it reads
// smaller than the solid badge icons other providers use. Bump just OpenClaw so its
// lobster is visibly larger than the rest. The icon wrappers below intentionally do
// NOT clip (no overflow-hidden), so the enlarged claw overflows its slot instead of
// being cropped by the square box — only OpenClaw is scaled up, so nothing else spills.
const ICON_SCALE_BUMP: Record<string, number> = { openclaw: 2.5 };
export function bumpedIconScale(provider: string | undefined, base: number): number {
    return base * (provider ? (ICON_SCALE_BUMP[provider] ?? 1) : 1);
}

export function ModelDropdown({
    isOpen,
    onToggle,
    onModelSelect,
    selectedModelId,
    models,
    isRecording = false,
    className = '',
    isDemo = false
}: ModelDropdownProps) {
    const [searchQuery, setSearchQuery] = useState('');
    const [selectedModelIndex, setSelectedModelIndex] = useState(0);
    const [isShowingApiKeyDrawer, setIsShowingApiKeyDrawer] = useState(false);
    const [currentApiKeyDrawerId, setCurrentApiKeyDrawerId] = useState<string | null>(null);
    const [selectedProviders, setSelectedProviders] = useState<Set<ModelProvider>>(new Set());
    const [providerSearchQuery, setProviderSearchQuery] = useState('');
    const [isEditMode, setIsEditMode] = useState(false);
    const [isFilterDropdownOpen, setIsFilterDropdownOpen] = useState(false);
    const [filterTab, setFilterTab] = useState<'provider' | 'features'>('provider');
    const [selectedFeatures, setSelectedFeatures] = useState<Set<string>>(new Set());
    const [filterPanelPosition, setFilterPanelPosition] = useState<{ top: number; left: number } | null>(null);

    // Detect mobile viewport
    const [isMobile, setIsMobile] = useState(false);

    useEffect(() => {
        const checkMobile = () => {
            setIsMobile(window.innerWidth < 768); // md breakpoint
        };

        checkMobile();
        window.addEventListener('resize', checkMobile);
        return () => window.removeEventListener('resize', checkMobile);
    }, []);

    // State for custom tooltip
    const [hoveredCapability, setHoveredCapability] = useState<{ label: string; x: number; y: number } | null>(null);
    const tooltipTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const isMouseOverTooltipTrigger = useRef(false);

    // Handle capability icon hover for custom tooltip with debounce
    const handleCapabilityHover = useCallback((e: React.MouseEvent, label: string) => {
        isMouseOverTooltipTrigger.current = true;
        const targetElement = e.currentTarget as HTMLElement;

        // Clear any existing timeout
        if (tooltipTimeoutRef.current) {
            clearTimeout(tooltipTimeoutRef.current);
        }

        // Add slight delay to prevent tooltip from appearing during quick mouse movements
        tooltipTimeoutRef.current = setTimeout(() => {
            // Only show if mouse is still over the trigger AND element still exists in DOM
            if (isMouseOverTooltipTrigger.current && targetElement && document.body.contains(targetElement)) {
                const rect = targetElement.getBoundingClientRect();
                setHoveredCapability({
                    label,
                    x: rect.left + rect.width / 2,
                    y: rect.top - 8
                });
            }
        }, 300); // 300ms delay for smoother experience
    }, []);

    const handleCapabilityLeave = useCallback(() => {
        isMouseOverTooltipTrigger.current = false;

        // Clear timeout if mouse leaves before tooltip shows
        if (tooltipTimeoutRef.current) {
            clearTimeout(tooltipTimeoutRef.current);
            tooltipTimeoutRef.current = null;
        }
        setHoveredCapability(null);
    }, []);

    // Persist view mode preference (favorites or all)
    const [viewMode, setViewMode] = useCachedValtioState<'favorites' | 'all'>(
        'chat',
        'modelViewMode',
        'all'
    );

    const dropdownRef = useRef<HTMLDivElement>(null);
    const toggleButtonRef = useRef<HTMLButtonElement>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);
    const parentRef = useRef<HTMLDivElement>(null);
    const providerSearchInputRef = useRef<HTMLInputElement>(null);
    const filterDropdownRef = useRef<HTMLDivElement>(null);
    const filterButtonRef = useRef<HTMLButtonElement>(null);
    const isMountedRef = useRef(true);
    const timeoutIdsRef = useRef<Set<NodeJS.Timeout>>(new Set());

    const { registerDrawer, unregisterDrawer } = useDrawer();
    const apiKeys = useAPIKeys();

    // User's custom favorite models (persisted to IndexedDB and cloud)
    // Initialized with default favorites from config
    const [userFavorites, setUserFavorites] = useCachedValtioState<string[]>(
        'chat',
        'favoriteModels',
        [...FAVORITE_MODELS]
    );


    // Cleanup effect to handle unmounting
    useEffect(() => {
        return () => {
            isMountedRef.current = false;
            // Clear all pending timeouts
            timeoutIdsRef.current.forEach(timeoutId => clearTimeout(timeoutId));
            timeoutIdsRef.current.clear();
        };
    }, []);

    // Get unique providers from models
    const availableProviders = Array.from(new Set((models || []).map(model => model.provider)));

    // Filter providers based on search query
    const filteredProviders = availableProviders.filter(provider => {
        const metadata = getProviderMetadata(provider);
        if (!metadata) return false; // Skip providers without metadata
        const normalizedTitle = normalizeForSearch(metadata.title);
        const normalizedQuery = normalizeForSearch(providerSearchQuery);
        return normalizedTitle.includes(normalizedQuery);
    });
    
    const filteredModels = filterAndSortModels(models || [], {
        searchQuery,
        selectedProviders,
        selectedFeatures,
        viewMode,
        userFavorites,
    });

    // Virtualizer for dropdown list
    const rowVirtualizer = useVirtualizer({
        count: filteredModels.length,
        getScrollElement: () => parentRef.current,
        estimateSize: () => 32, // Fixed height per item (32px)
        overscan: 7, // Render extra items for smooth scrolling (8 visible + 7 = ~15 total)
    });

    // Scroll to selected model when dropdown opens
    useEffect(() => {
        if (!isOpen) return;

        const selectedIndex = filteredModels.findIndex(model => model.id === selectedModelId);
        if (selectedIndex >= 0) {
            setSelectedModelIndex(selectedIndex);

            // Ensure dropdown is visible before scrolling
            requestAnimationFrame(() => {
                rowVirtualizer.scrollToIndex(selectedIndex, { align: 'center' });
            });
        }
    }, [isOpen]);

    // Helper function to safely execute timeouts only when component is mounted
    const safeSetTimeout = useCallback((callback: () => void, delay: number) => {
        const timeoutId = setTimeout(() => {
            timeoutIdsRef.current.delete(timeoutId);
            if (isMountedRef.current) {
                callback();
            }
        }, delay);
        timeoutIdsRef.current.add(timeoutId);
        return timeoutId;
    }, []);

    // Helper function to get provider from model ID using the unified model system
    const getProviderForModel = useCallback((modelId: string): ModelProvider | null => {
        const model = models.find(m => m.id === modelId);
        if (!model) return null;
        
        const metadata = getProviderMetadata(model.provider);

        // Skip if no metadata
        if (!metadata) return null;

        // Only return provider if it doesn't allow usage-based billing AND has required API keys
        // If allowUsageBased is true, user can use our billing system instead of providing API keys
        if (!metadata.allowUsageBased && metadata.requiredApiKeys && metadata.requiredApiKeys.length > 0) {
            return model.provider;
        }

        return null;
    }, [models]);

    const handleModelSelect = useCallback((modelId: string) => {
        // Always close dropdown immediately for better UX
        onToggle();
        // Always call onModelSelect immediately
        onModelSelect(modelId);

        const provider = getProviderForModel(modelId);
        const hasKeys = provider ? apiKeys.hasRequiredKeys(provider) : true;
        
        // Show drawer if:
        // 1. Provider requires API keys (allowUsageBased: false)
        // 2. We don't have the required API keys
        if (provider && !hasKeys) {
            const drawerId = `api-key-${provider}`;
            
            // If we're opening the same drawer, don't re-register it
            if (currentApiKeyDrawerId === drawerId) {
                return;
            }
            
            // Close existing drawer if different, then register new one
            if (currentApiKeyDrawerId && currentApiKeyDrawerId !== drawerId) {
                unregisterDrawer(currentApiKeyDrawerId);
                setCurrentApiKeyDrawerId(null);
                setIsShowingApiKeyDrawer(false);
                
                // Use setTimeout to ensure unregister completes before register
                safeSetTimeout(() => {
                    setIsShowingApiKeyDrawer(true);
                    setCurrentApiKeyDrawerId(drawerId);

                    // Don't close usage-dashboard - let drawer system handle visibility stack

                    registerDrawer(
                        drawerId,
                        <APIKeyRequestDrawer
                            provider={provider}
                            onKeySubmit={(keys) => {
                                // Save all provided API keys
                                apiKeys.saveKeys(keys);
                                setIsShowingApiKeyDrawer(false);
                                setCurrentApiKeyDrawerId(null);
                                unregisterDrawer(drawerId);
                            }}
                            onClose={() => {
                                unregisterDrawer(drawerId);
                                setIsShowingApiKeyDrawer(false);
                                setCurrentApiKeyDrawerId(null);
                            }}
                        />
                    );
                }, 0);
                return;
            }
            
            // Mark that we're showing the new API key drawer
            setIsShowingApiKeyDrawer(true);
            setCurrentApiKeyDrawerId(drawerId);

            // Don't close usage-dashboard - let drawer system handle visibility stack

            // Register API key request drawer
            registerDrawer(
                drawerId,
                <APIKeyRequestDrawer
                    provider={provider}
                    onKeySubmit={(keys) => {
                        // Save all provided API keys
                        apiKeys.saveKeys(keys);
                        setIsShowingApiKeyDrawer(false);
                        setCurrentApiKeyDrawerId(null);
                        unregisterDrawer(drawerId);
                    }}
                    onClose={() => {
                        unregisterDrawer(drawerId);
                        setIsShowingApiKeyDrawer(false);
                        setCurrentApiKeyDrawerId(null);
                    }}
                />
            );
        } else {
            // Close any existing API key drawer when selecting a model that doesn't need keys
            if (currentApiKeyDrawerId) {
                unregisterDrawer(currentApiKeyDrawerId);
                setCurrentApiKeyDrawerId(null);
                setIsShowingApiKeyDrawer(false);
            }
        }
    }, [getProviderForModel, apiKeys, registerDrawer, unregisterDrawer, currentApiKeyDrawerId, safeSetTimeout, onModelSelect, onToggle]);

    const handleToggle = useCallback(() => {
        if (!isOpen) {
            setSearchQuery('');
            setIsEditMode(false); // Exit edit mode when opening
            setIsFilterDropdownOpen(false); // Close filter panel when dropdown closes

            // Focus search input when dropdown opens
            safeSetTimeout(() => {
                if (searchInputRef.current) {
                    searchInputRef.current.focus();
                }
            }, 0);
        }
        onToggle();
    }, [isOpen, onToggle, safeSetTimeout]);

    const handleFilterToggle = useCallback(() => {
        if (!isFilterDropdownOpen && filterButtonRef.current && dropdownRef.current) {
            const dropdownRect = dropdownRef.current.getBoundingClientRect();

            // Position filter panel to the right of the dropdown
            setFilterPanelPosition({
                top: dropdownRect.top,
                left: dropdownRect.right + 8 // 8px gap
            });
        }
        setIsFilterDropdownOpen(!isFilterDropdownOpen);
    }, [isFilterDropdownOpen]);
    
    const handleProviderToggle = useCallback((provider: ModelProvider) => {
        setSelectedProviders(prev => {
            const newSet = new Set(prev);
            if (newSet.has(provider)) {
                newSet.delete(provider);
            } else {
                newSet.add(provider);
            }
            return newSet;
        });
    }, []);

    const handleFeatureToggle = useCallback((feature: string) => {
        setSelectedFeatures(prev => {
            const newSet = new Set(prev);
            if (newSet.has(feature)) {
                newSet.delete(feature);
            } else {
                newSet.add(feature);
            }
            return newSet;
        });
    }, []);

    const clearAllFilters = useCallback(() => {
        setSelectedProviders(new Set());
        setSelectedFeatures(new Set());
    }, []);

    // Toggle favorite status of a model
    const toggleFavorite = useCallback((modelId: string, event: React.MouseEvent) => {
        event.stopPropagation(); // Prevent model selection when clicking pin

        setUserFavorites(prev => {
            if (prev.includes(modelId)) {
                // Remove from favorites
                return prev.filter(id => id !== modelId);
            } else {
                // Add to favorites
                return [...prev, modelId];
            }
        });
    }, [setUserFavorites]);

    // Check if a model is favorited
    const isFavorite = useCallback((modelId: string) => {
        return userFavorites.includes(modelId);
    }, [userFavorites]);

    // Remove model from favorites
    const removeFavorite = useCallback((modelId: string, event: React.MouseEvent) => {
        event.stopPropagation();
        setUserFavorites(prev => prev.filter(id => id !== modelId));
    }, [setUserFavorites]);

    // Move favorite up in the list
    const moveFavoriteUp = useCallback((modelId: string, event: React.MouseEvent) => {
        event.stopPropagation();
        setUserFavorites(prev => {
            const index = prev.indexOf(modelId);
            if (index <= 0) return prev; // Already at top or not found

            const newFavorites = [...prev];
            // Swap with previous item
            [newFavorites[index - 1], newFavorites[index]] = [newFavorites[index], newFavorites[index - 1]];
            return newFavorites;
        });
    }, [setUserFavorites]);

    // Move favorite down in the list
    const moveFavoriteDown = useCallback((modelId: string, event: React.MouseEvent) => {
        event.stopPropagation();
        setUserFavorites(prev => {
            const index = prev.indexOf(modelId);
            if (index === -1 || index >= prev.length - 1) return prev; // Not found or already at bottom

            const newFavorites = [...prev];
            // Swap with next item
            [newFavorites[index], newFavorites[index + 1]] = [newFavorites[index + 1], newFavorites[index]];
            return newFavorites;
        });
    }, [setUserFavorites]);

    // Detect mobile screen size
    useEffect(() => {
        const checkMobile = () => {
            setIsMobile(window.innerWidth < 768); // Tailwind md breakpoint
        };

        checkMobile();
        window.addEventListener('resize', checkMobile);
        return () => window.removeEventListener('resize', checkMobile);
    }, []);

    // Clear tooltip when dropdown closes or when scrolling
    useEffect(() => {
        if (!isOpen) {
            // Clear tooltip timeout
            if (tooltipTimeoutRef.current) {
                clearTimeout(tooltipTimeoutRef.current);
                tooltipTimeoutRef.current = null;
            }
            setHoveredCapability(null);
        }
    }, [isOpen]);

    // Clear tooltip on scroll to prevent it from sticking
    useEffect(() => {
        const scrollContainer = parentRef.current;
        if (!scrollContainer) return;

        const handleScroll = () => {
            // Clear tooltip immediately on scroll
            if (tooltipTimeoutRef.current) {
                clearTimeout(tooltipTimeoutRef.current);
                tooltipTimeoutRef.current = null;
            }
            setHoveredCapability(null);
        };

        scrollContainer.addEventListener('scroll', handleScroll, { passive: true });
        return () => scrollContainer.removeEventListener('scroll', handleScroll);
    }, []);

    // Cleanup tooltip timeout on unmount
    useEffect(() => {
        return () => {
            if (tooltipTimeoutRef.current) {
                clearTimeout(tooltipTimeoutRef.current);
            }
        };
    }, []);

    // Reset keyboard navigation to top when user searches
    useEffect(() => {
        // Only reset when user is actively typing (not when clearing on open)
        if (searchQuery.length > 0) {
            setSelectedModelIndex(0);
            // Reset scroll position to top when searching
            rowVirtualizer.scrollToIndex(0, { align: 'start' });
        }
    }, [searchQuery, rowVirtualizer]);

    // Handle keyboard navigation in dropdown with auto-scroll
    useEffect(() => {
        if (!isOpen) return;

        const handleKeyDown = (e: Event) => {
            const keyboardEvent = e as unknown as KeyboardEvent;
            switch (keyboardEvent.key) {
                case 'ArrowDown':
                    keyboardEvent.preventDefault();
                    setSelectedModelIndex(prev => {
                        const newIndex = prev < filteredModels.length - 1 ? prev + 1 : 0;
                        // Auto-scroll to keep selected item visible in virtualized list
                        safeSetTimeout(() => {
                            if (isMountedRef.current) {
                                rowVirtualizer.scrollToIndex(newIndex);
                            }
                        }, 0);
                        return newIndex;
                    });
                    break;
                case 'ArrowUp':
                    keyboardEvent.preventDefault();
                    setSelectedModelIndex(prev => {
                        const newIndex = prev > 0 ? prev - 1 : filteredModels.length - 1;
                        // Auto-scroll to keep selected item visible in virtualized list
                        safeSetTimeout(() => {
                            if (isMountedRef.current) {
                                rowVirtualizer.scrollToIndex(newIndex);
                            }
                        }, 0);
                        return newIndex;
                    });
                    break;
                case 'Enter':
                    keyboardEvent.preventDefault();
                    if (filteredModels[selectedModelIndex]) {
                        handleModelSelect(filteredModels[selectedModelIndex].id);
                    }
                    break;
                case 'Escape':
                    keyboardEvent.preventDefault();
                    onToggle();
                    break;
            }
        };

        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, filteredModels, selectedModelIndex, handleModelSelect, safeSetTimeout, rowVirtualizer, onToggle]);

    // Close dropdown when clicking outside (only when dropdown is open)
    useEffect(() => {
        // Only add the event listener when dropdown is open
        if (!isOpen) {
            return;
        }

        const handleClickOutside = (event: MouseEvent) => {
            // Don't close if we're showing the API key drawer (skip in demo mode)
            if (!isDemo && isShowingApiKeyDrawer) {
                return;
            }

            const target = event.target as Node;
            const targetElement = event.target as HTMLElement;

            // Check if click is inside a portal-rendered dropdown (has data attribute or is child of one)
            const isClickOnPortalDropdown = targetElement.closest?.('[data-model-dropdown-portal="true"]');

            const isClickOnDropdown = dropdownRef.current && dropdownRef.current.contains(target);
            const isClickOnToggleButton = toggleButtonRef.current && toggleButtonRef.current.contains(target);
            const isClickOnFilterDropdown = filterDropdownRef.current && filterDropdownRef.current.contains(target);
            const isClickOnFilterButton = filterButtonRef.current && filterButtonRef.current.contains(target);

            // Keep filter panel open when clicking inside main dropdown or filter panel
            if (isClickOnDropdown || isClickOnFilterDropdown || isClickOnFilterButton || isClickOnPortalDropdown) {
                return;
            }

            // Only close main dropdown and filter panel if clicking outside all dropdown elements
            if (!isClickOnDropdown && !isClickOnToggleButton && !isClickOnFilterDropdown && !isClickOnFilterButton && !isClickOnPortalDropdown) {
                onToggle();
                setIsFilterDropdownOpen(false);
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isOpen, isShowingApiKeyDrawer, onToggle, isDemo, isFilterDropdownOpen]);

    // Helper function to get display name for models
    const getModelDisplayName = (modelId: string): string => {
        const model = models.find(model => model.id === modelId);
        return model ? model.id : modelId;
    };

    const getDisplayText = (modelId?: string) => {
        const fullName = modelId ? getModelDisplayName(modelId) : getModelDisplayName(selectedModelId);
        // Split by "/" and return the last part
        const parts = fullName.split('/');
        return parts[parts.length - 1];
    };

    // Virtualized model item component
    const VirtualizedModelItem = ({ virtualItem, models, selectedIndex }: {
        virtualItem: any;
        models: any[];
        selectedIndex: number;
    }) => {
        const model = models?.[virtualItem.index];
        if (!model) return null;

        const providerMetadata = getProviderMetadata(model.provider);
        if (!providerMetadata) return null; // Skip if no metadata
        const isCurrentlySelected = model.id === selectedModelId;
        const isHovered = selectedIndex === virtualItem.index;

        // Get position in favorites list for up/down button logic
        const favoriteIndex = userFavorites.indexOf(model.id);
        const isFirstFavorite = favoriteIndex === 0;
        const isLastFavorite = favoriteIndex === userFavorites.length - 1;

        return (
            <div
                style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: `${virtualItem.size}px`,
                    transform: `translateY(${virtualItem.start}px)`,
                }}
            >
                {isEditMode && viewMode === 'favorites' ? (
                    <div
                        onMouseEnter={() => setSelectedModelIndex(virtualItem.index)}
                        className={cn(
                            "w-full text-left px-2.5 py-1.5 transition-all duration-150 flex items-center gap-1.5 h-full relative text-xs",
                            isCurrentlySelected ? "bg-accent/50 dark:bg-zinc-700/30 text-foreground/80"
                                : "text-muted-foreground hover:bg-accent/40 dark:hover:bg-zinc-700/20"
                        )}
                    >
                        {isCurrentlySelected && (
                            <div className="absolute left-0.5 top-1/2 -translate-y-1/2 w-1 h-1 bg-foreground rounded-full" />
                        )}
                        {/* Up/Down arrows for reordering */}
                        <div className="flex flex-col gap-0 flex-shrink-0">
                            <button
                                onClick={(e) => moveFavoriteUp(model.id, e)}
                                disabled={isFirstFavorite}
                                className={cn(
                                    "p-0 rounded transition-colors",
                                    isFirstFavorite
                                        ? "text-muted-foreground/70 dark:text-zinc-600 cursor-not-allowed opacity-30"
                                        : "text-muted-foreground hover:text-foreground hover:bg-accent dark:hover:bg-zinc-600/50"
                                )}
                                title="Move up"
                            >
                                <ChevronUp className="w-3 h-3" />
                            </button>
                            <button
                                onClick={(e) => moveFavoriteDown(model.id, e)}
                                disabled={isLastFavorite}
                                className={cn(
                                    "p-0 rounded transition-colors",
                                    isLastFavorite
                                        ? "text-muted-foreground/70 dark:text-zinc-600 cursor-not-allowed opacity-30"
                                        : "text-muted-foreground hover:text-foreground hover:bg-accent dark:hover:bg-zinc-600/50"
                                )}
                                title="Move down"
                            >
                                <ChevronDownIcon className="w-3 h-3" />
                            </button>
                        </div>
                        <div className="w-4 h-4 flex-shrink-0 flex items-center justify-center">
                            <div
                                className={cn(isRecording ? "grayscale opacity-60" : "opacity-80")}
                                style={{ transform: `scale(${bumpedIconScale(model.provider, 0.5)})` }}
                            >
                                {providerMetadata.icon}
                            </div>
                        </div>
                        <span className={cn("truncate flex-1", isCurrentlySelected && "font-medium")}>
                            {getDisplayText(model.id)}
                        </span>
                        {model.capabilities && (
                            <div className="flex items-center gap-1 flex-shrink-0">
                                {model.capabilities.imageAnalysis && (
                                    <span
                                        onMouseEnter={(e) => handleCapabilityHover(e, 'Image analysis')}
                                        onMouseLeave={handleCapabilityLeave}
                                        className="flex-shrink-0 inline-flex items-center"
                                    >
                                        <Eye className="w-3 h-3 text-muted-foreground/80 dark:text-zinc-400/80" />
                                    </span>
                                )}
                                {model.capabilities.imageGeneration && (
                                    <span
                                        onMouseEnter={(e) => handleCapabilityHover(e, 'Image generation')}
                                        onMouseLeave={handleCapabilityLeave}
                                        className="flex-shrink-0 inline-flex items-center"
                                    >
                                        <ImagePlus className="w-3 h-3 text-muted-foreground/80 dark:text-zinc-400/80" />
                                    </span>
                                )}
                                {model.capabilities.reasoning && (
                                    <span
                                        onMouseEnter={(e) => handleCapabilityHover(e, 'Reasoning')}
                                        onMouseLeave={handleCapabilityLeave}
                                        className="flex-shrink-0 inline-flex items-center"
                                    >
                                        <Brain className="w-3 h-3 text-muted-foreground/80 dark:text-zinc-400/80" />
                                    </span>
                                )}
                                {model.capabilities.tools && (
                                    <span
                                        onMouseEnter={(e) => handleCapabilityHover(e, 'Tool support')}
                                        onMouseLeave={handleCapabilityLeave}
                                        className="flex-shrink-0 inline-flex items-center"
                                    >
                                        <Wrench className="w-3 h-3 text-muted-foreground/80 dark:text-zinc-400/80" />
                                    </span>
                                )}
                                {model.capabilities.videoGeneration && (
                                    <span
                                        onMouseEnter={(e) => handleCapabilityHover(e, 'Video generation')}
                                        onMouseLeave={handleCapabilityLeave}
                                        className="flex-shrink-0 inline-flex items-center"
                                    >
                                        <Video className="w-3 h-3 text-muted-foreground/80 dark:text-zinc-400/80" />
                                    </span>
                                )}
                            </div>
                        )}
                        <div className="flex items-center gap-1 ml-auto flex-shrink-0">
                            <button
                                onClick={(e) => removeFavorite(model.id, e)}
                                className="p-0.5 rounded hover:bg-red-500/20 transition-colors text-muted-foreground dark:text-zinc-500 hover:text-red-600 dark:hover:text-red-400"
                                title="Remove from favorites"
                            >
                                <Trash2 className="w-3 h-3" />
                            </button>
                            {isCurrentlySelected && (
                                <Check className="w-3 h-3 text-muted-foreground dark:text-white/70" />
                            )}
                        </div>
                    </div>
                ) : (
                    <div
                        onClick={(e) => {
                            // Only handle click if not clicking on the star button
                            const target = e.target as HTMLElement;
                            if (!target.closest('[data-star-button]')) {
                                e.stopPropagation();
                                handleModelSelect(model.id);
                            }
                        }}
                        onMouseEnter={() => setSelectedModelIndex(virtualItem.index)}
                        className={cn(
                            "w-full text-left px-2.5 py-1.5 transition-all flex items-center gap-1.5 h-full relative text-xs cursor-pointer",
                            isHovered ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                : isCurrentlySelected ? "bg-accent/50 dark:bg-zinc-700/30 text-foreground/80"
                                : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                        )}
                    >
                        {isCurrentlySelected && (
                            <div className="absolute left-0.5 top-1/2 -translate-y-1/2 w-1 h-1 bg-foreground rounded-full" />
                        )}
                        <div className="w-4 h-4 flex-shrink-0 flex items-center justify-center">
                            <div
                                className={cn(isRecording ? "grayscale opacity-60" : "opacity-80")}
                                style={{ transform: `scale(${bumpedIconScale(model.provider, 0.5)})` }}
                            >
                                {providerMetadata.icon}
                            </div>
                        </div>
                        <span className={cn("truncate flex-1", isCurrentlySelected && "font-medium")}>
                            {getDisplayText(model.id)}
                        </span>
                        {model.capabilities && (
                            <div className="flex items-center gap-1 flex-shrink-0">
                                {model.capabilities.imageAnalysis && (
                                    <span
                                        onMouseEnter={(e) => handleCapabilityHover(e, 'Image analysis')}
                                        onMouseLeave={handleCapabilityLeave}
                                        className="flex-shrink-0 inline-flex items-center"
                                    >
                                        <Eye className="w-3 h-3 text-muted-foreground/80 dark:text-zinc-400/80" />
                                    </span>
                                )}
                                {model.capabilities.imageGeneration && (
                                    <span
                                        onMouseEnter={(e) => handleCapabilityHover(e, 'Image generation')}
                                        onMouseLeave={handleCapabilityLeave}
                                        className="flex-shrink-0 inline-flex items-center"
                                    >
                                        <ImagePlus className="w-3 h-3 text-muted-foreground/80 dark:text-zinc-400/80" />
                                    </span>
                                )}
                                {model.capabilities.reasoning && (
                                    <span
                                        onMouseEnter={(e) => handleCapabilityHover(e, 'Reasoning')}
                                        onMouseLeave={handleCapabilityLeave}
                                        className="flex-shrink-0 inline-flex items-center"
                                    >
                                        <Brain className="w-3 h-3 text-muted-foreground/80 dark:text-zinc-400/80" />
                                    </span>
                                )}
                                {model.capabilities.tools && (
                                    <span
                                        onMouseEnter={(e) => handleCapabilityHover(e, 'Tool support')}
                                        onMouseLeave={handleCapabilityLeave}
                                        className="flex-shrink-0 inline-flex items-center"
                                    >
                                        <Wrench className="w-3 h-3 text-muted-foreground/80 dark:text-zinc-400/80" />
                                    </span>
                                )}
                                {model.capabilities.videoGeneration && (
                                    <span
                                        onMouseEnter={(e) => handleCapabilityHover(e, 'Video generation')}
                                        onMouseLeave={handleCapabilityLeave}
                                        className="flex-shrink-0 inline-flex items-center"
                                    >
                                        <Video className="w-3 h-3 text-muted-foreground/80 dark:text-zinc-400/80" />
                                    </span>
                                )}
                            </div>
                        )}
                        <div className="flex items-center gap-1 ml-auto flex-shrink-0">
                            {viewMode === 'all' && (
                                <button
                                    data-star-button
                                    onClick={(e) => toggleFavorite(model.id, e)}
                                    className={cn(
                                        "p-0.5 rounded hover:bg-accent dark:hover:bg-zinc-600/50 transition-colors",
                                        isFavorite(model.id) ? "text-yellow-600 dark:text-yellow-400" : "text-muted-foreground dark:text-zinc-500 hover:text-foreground/80"
                                    )}
                                    title={isFavorite(model.id) ? "Remove from favorites" : "Add to favorites"}
                                >
                                    <Star className={cn(
                                        "w-3 h-3",
                                        isFavorite(model.id) && "fill-current"
                                    )} />
                                </button>
                            )}
                            {isCurrentlySelected && (
                                <Check className="w-3 h-3 text-muted-foreground dark:text-white/70" />
                            )}
                        </div>
                    </div>
                )}
            </div>
        );
    };

    return (
        <div className={cn("relative", className)}>
            <button
                ref={toggleButtonRef}
                onClick={handleToggle}
                className={cn(
                    "flex items-center gap-1 transition-colors nodrag nowheel",
                    className?.includes('demo-model-dropdown')
                        ? "pl-0 pr-1 py-0 text-sm text-muted-foreground dark:text-zinc-500 hover:text-foreground/80"
                        : "px-1 py-0.5 text-xs text-muted-foreground dark:text-zinc-500 hover:text-foreground/80"
                )}
            >
                {(() => {
                    const model = models.find(m => m.id === selectedModelId);
                    const providerMetadata = model ? getProviderMetadata(model.provider) : null;
                    const icon = providerMetadata?.icon;
                    return icon ? (
                        <div className={cn(
                            "flex-shrink-0 flex items-center justify-center",
                            className?.includes('demo-model-dropdown') ? "w-5 h-5" : "w-4 h-4"
                        )}>
                            <div
                                className={cn("grayscale", isRecording ? "opacity-60" : "opacity-80")}
                                style={{ transform: `scale(${bumpedIconScale(model?.provider, className?.includes('demo-model-dropdown') ? 0.55 : 0.45)})` }}
                            >
                                {icon}
                            </div>
                        </div>
                    ) : null;
                })()}
                <span>{getDisplayText()}</span>
                <ChevronDown className={cn(
                    className?.includes('demo-model-dropdown') ? "w-4 h-4" : "w-3 h-3"
                )} />
            </button>

            {/* Dropdown content - anchored above the toggle button */}
            {(() => {
                // Common dropdown content - defined once, used in both portal and inline modes
                const dropdownContent = (
                    <>
                        {/* Search bar - compact and subtle */}
                    <div className="relative border-b border-border dark:border-zinc-700/30 flex items-center">
                        <Search className="absolute left-2.5 top-1/2 transform -translate-y-1/2 w-2.5 h-2.5 text-muted-foreground dark:text-zinc-500" />
                        <input
                            ref={searchInputRef}
                            type="text"
                            placeholder={isEditMode ? "Use arrows to reorder..." : "Search models..."}
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            disabled={isEditMode}
                            className={cn(
                                "flex-1 pl-7 pr-2.5 py-2 bg-transparent text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none border-0 rounded-t-lg",
                                className?.includes('demo-model-dropdown') ? "text-sm" : "text-xs",
                                isEditMode && "cursor-not-allowed opacity-60"
                            )}
                        />
                        {/* Filter button */}
                        {!isEditMode && (
                            <button
                                ref={filterButtonRef}
                                onClick={handleFilterToggle}
                                className={cn(
                                    "mr-1 p-1.5 rounded transition-colors flex items-center",
                                    isFilterDropdownOpen
                                        ? "bg-blue-500/20 text-blue-600 dark:text-blue-300"
                                        : (selectedProviders.size > 0 || selectedFeatures.size > 0)
                                        ? "bg-blue-500/20 text-blue-600 dark:text-blue-300"
                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                )}
                                title={isFilterDropdownOpen ? "Close filters" : "Filter models"}
                            >
                                <Filter className="w-3.5 h-3.5" />
                                {(selectedProviders.size > 0 || selectedFeatures.size > 0) && (
                                    <span className="ml-1 text-xs font-medium">
                                        {selectedProviders.size + selectedFeatures.size}
                                    </span>
                                )}
                            </button>
                        )}
                        {/* Edit button - only show in favorites view */}
                        {viewMode === 'favorites' && (
                            <button
                                onClick={() => setIsEditMode(!isEditMode)}
                                className={cn(
                                    "mr-2 px-2 py-1 text-xs rounded border transition-colors flex items-center gap-1",
                                    isEditMode
                                        ? "bg-blue-500/20 border-blue-500/50 text-blue-600 dark:text-blue-300"
                                        : "bg-secondary/50 dark:bg-zinc-700/30 border-border dark:border-zinc-600/50 text-muted-foreground hover:bg-secondary dark:hover:bg-zinc-700/50 hover:text-foreground"
                                )}
                            >
                                <Edit3 className="w-3 h-3" />
                                <span>{isEditMode ? "Done" : "Edit"}</span>
                            </button>
                        )}
                    </div>

                    {/* Models list - virtualized for performance */}
                    <div className={cn(
                        className?.includes('demo-model-dropdown') ? "h-56" : "h-64"
                    )}>
                        {/* Mobile: Show filter panel inline when open */}
                        {isMobile && isFilterDropdownOpen ? (
                            <div className="h-64 overflow-hidden">
                                {/* Filter panel content for mobile */}
                                <div className="h-full flex flex-col bg-muted/50">
                                    {/* Tab Headers with Clear Icon */}
                                    <div className="flex items-center gap-1 p-2 border-b border-border dark:border-zinc-700/30">
                                        {/* Clear filters icon - leftmost */}
                                        {(selectedProviders.size > 0 || selectedFeatures.size > 0) && (
                                            <button
                                                onClick={clearAllFilters}
                                                className="p-1.5 text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 hover:bg-red-500/10 transition-colors rounded"
                                                title="Clear all filters"
                                            >
                                                <FilterX className="w-3.5 h-3.5" />
                                            </button>
                                        )}
                                        <button
                                            onClick={() => setFilterTab('provider')}
                                            className={cn(
                                                "flex-1 px-2 py-1.5 text-xs rounded transition-colors",
                                                filterTab === 'provider'
                                                    ? "bg-accent dark:bg-zinc-700/70 text-foreground"
                                                    : "text-muted-foreground hover:text-foreground"
                                            )}
                                        >
                                            Provider
                                            {selectedProviders.size > 0 && (
                                                <span className="ml-1 text-[10px] bg-blue-500/30 text-blue-600 dark:text-blue-300 px-1 rounded">
                                                    {selectedProviders.size}
                                                </span>
                                            )}
                                        </button>
                                        <button
                                            onClick={() => setFilterTab('features')}
                                            className={cn(
                                                "flex-1 px-2 py-1.5 text-xs rounded transition-colors",
                                                filterTab === 'features'
                                                    ? "bg-accent dark:bg-zinc-700/70 text-foreground"
                                                    : "text-muted-foreground hover:text-foreground"
                                            )}
                                        >
                                            Features
                                            {selectedFeatures.size > 0 && (
                                                <span className="ml-1 text-[10px] bg-blue-500/30 text-blue-600 dark:text-blue-300 px-1 rounded">
                                                    {selectedFeatures.size}
                                                </span>
                                            )}
                                        </button>
                                    </div>

                                    {/* Provider Tab Content */}
                                    {filterTab === 'provider' && (
                                        <div className="flex-1 p-2 overflow-hidden flex flex-col">
                                            {/* Provider search */}
                                            <div className="relative mb-2">
                                                <Search className="absolute left-2.5 top-1/2 transform -translate-y-1/2 w-2.5 h-2.5 text-muted-foreground dark:text-zinc-500" />
                                                <input
                                                    ref={providerSearchInputRef}
                                                    type="text"
                                                    placeholder="Search providers..."
                                                    value={providerSearchQuery}
                                                    onChange={(e) => setProviderSearchQuery(e.target.value)}
                                                    className="w-full pl-7 pr-2.5 py-1.5 text-xs bg-muted/50 dark:bg-zinc-700/20 rounded text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none border border-input dark:border-zinc-600/50"
                                                />
                                            </div>

                                            {/* Provider list */}
                                            <div className="flex-1 overflow-y-auto scrollbar-subtle">
                                                {filteredProviders.length === 0 ? (
                                                    <div className="text-xs text-muted-foreground dark:text-zinc-500 text-center py-4">
                                                        No providers found
                                                    </div>
                                                ) : (
                                                    filteredProviders.map((provider) => {
                                                        const metadata = getProviderMetadata(provider);
                                                        if (!metadata) return null;
                                                        const isSelected = selectedProviders.has(provider);

                                                        return (
                                                            <button
                                                                key={provider}
                                                                onClick={() => handleProviderToggle(provider)}
                                                                className={cn(
                                                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-2 rounded mb-0.5",
                                                                    isSelected
                                                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                                                )}
                                                            >
                                                                <div className="w-5 h-5 flex-shrink-0 flex items-center justify-center overflow-hidden">
                                                                    <div className="transform scale-[0.6]">
                                                                        {metadata.icon}
                                                                    </div>
                                                                </div>
                                                                <span className="flex-1">{metadata.title}</span>
                                                                {isSelected && (
                                                                    <Check className="w-3 h-3 text-foreground flex-shrink-0" />
                                                                )}
                                                            </button>
                                                        );
                                                    })
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    {/* Features Tab Content */}
                                    {filterTab === 'features' && (
                                        <div className="flex-1 p-2 space-y-0.5 overflow-y-auto scrollbar-subtle">
                                            <button
                                                onClick={() => handleFeatureToggle('imageAnalysis')}
                                                className={cn(
                                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-2 rounded",
                                                    selectedFeatures.has('imageAnalysis')
                                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                                )}
                                            >
                                                <Eye className="w-3.5 h-3.5 text-muted-foreground/80 dark:text-zinc-400/80 flex-shrink-0" />
                                                <span className="flex-1">Image Analysis</span>
                                                {selectedFeatures.has('imageAnalysis') && (
                                                    <Check className="w-3 h-3 text-foreground flex-shrink-0" />
                                                )}
                                            </button>

                                            <button
                                                onClick={() => handleFeatureToggle('imageGeneration')}
                                                className={cn(
                                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-2 rounded",
                                                    selectedFeatures.has('imageGeneration')
                                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                                )}
                                            >
                                                <ImagePlus className="w-3.5 h-3.5 text-muted-foreground/80 dark:text-zinc-400/80 flex-shrink-0" />
                                                <span className="flex-1">Image Generation</span>
                                                {selectedFeatures.has('imageGeneration') && (
                                                    <Check className="w-3 h-3 text-foreground flex-shrink-0" />
                                                )}
                                            </button>

                                            <button
                                                onClick={() => handleFeatureToggle('reasoning')}
                                                className={cn(
                                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-2 rounded",
                                                    selectedFeatures.has('reasoning')
                                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                                )}
                                            >
                                                <Brain className="w-3.5 h-3.5 text-muted-foreground/80 dark:text-zinc-400/80 flex-shrink-0" />
                                                <span className="flex-1">Reasoning</span>
                                                {selectedFeatures.has('reasoning') && (
                                                    <Check className="w-3 h-3 text-foreground flex-shrink-0" />
                                                )}
                                            </button>

                                            <button
                                                onClick={() => handleFeatureToggle('tools')}
                                                className={cn(
                                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-2 rounded",
                                                    selectedFeatures.has('tools')
                                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                                )}
                                            >
                                                <Wrench className="w-3.5 h-3.5 text-muted-foreground/80 dark:text-zinc-400/80 flex-shrink-0" />
                                                <span className="flex-1">Tool Support</span>
                                                {selectedFeatures.has('tools') && (
                                                    <Check className="w-3 h-3 text-foreground flex-shrink-0" />
                                                )}
                                            </button>

                                            <button
                                                onClick={() => handleFeatureToggle('videoGeneration')}
                                                className={cn(
                                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-2 rounded",
                                                    selectedFeatures.has('videoGeneration')
                                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                                )}
                                            >
                                                <Video className="w-3.5 h-3.5 text-muted-foreground/80 dark:text-zinc-400/80 flex-shrink-0" />
                                                <span className="flex-1">Video Generation</span>
                                                {selectedFeatures.has('videoGeneration') && (
                                                    <Check className="w-3 h-3 text-foreground flex-shrink-0" />
                                                )}
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        ) : (
                            // Desktop or mobile with filter closed: Show model list
                            <>
                                {!filteredModels || filteredModels.length === 0 ? (
                                    <div className="px-3 py-2 text-xs text-muted-foreground dark:text-zinc-500 text-center">
                                        {models ? "No models found" : "Loading models..."}
                                    </div>
                                ) : (
                                    <div
                                        ref={parentRef}
                                        className={cn(
                                            "overflow-auto scrollbar-subtle",
                                            className?.includes('demo-model-dropdown') ? "h-56" : "h-64"
                                        )}
                                    >
                                        <div
                                            style={{
                                                height: `${rowVirtualizer.getTotalSize()}px`,
                                                width: '100%',
                                                position: 'relative',
                                            }}
                                        >
                                            {rowVirtualizer.getVirtualItems().map((virtualItem) => (
                                                <VirtualizedModelItem
                                                    key={virtualItem.key}
                                                    virtualItem={virtualItem}
                                                    models={filteredModels}
                                                    selectedIndex={selectedModelIndex}
                                                />
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </>
                        )}
                    </div>

                    {/* Bottom toggle bar */}
                    <div className="border-t border-border dark:border-zinc-700/30 px-2 py-1.5">
                        <button
                            onClick={() => {
                                const newMode = viewMode === 'favorites' ? 'all' : 'favorites';
                                setViewMode(newMode);
                                setSearchQuery('');
                                setSelectedProviders(new Set());
                                setSelectedFeatures(new Set());
                                setIsFilterDropdownOpen(false);
                                setIsEditMode(false);
                            }}
                            className="flex items-center justify-center w-full gap-2 px-3 py-1.5 text-xs text-foreground/80 bg-secondary/50 dark:bg-zinc-700/30 rounded border border-border dark:border-zinc-600/50 hover:bg-secondary dark:hover:bg-zinc-700/50 hover:text-foreground transition-all group"
                        >
                            {viewMode === 'favorites' ? (
                                <>
                                    <List className="w-3.5 h-3.5 transition-transform group-hover:scale-110" />
                                    <span className="font-medium">Show All</span>
                                </>
                            ) : (
                                <>
                                    <Star className="w-3.5 h-3.5 transition-transform group-hover:scale-110" />
                                    <span className="font-medium">Favorites</span>
                                </>
                            )}
                        </button>
                    </div>
                    </>
                );

                return (
                    <div
                        ref={dropdownRef}
                        className={cn(
                            "absolute bottom-full mb-0.5 ml-0 bg-popover dark:bg-zinc-800 backdrop-blur-md border border-border dark:border-zinc-600/70 rounded-lg shadow-xl z-50 nowheel",
                            className?.includes('demo-model-dropdown') ? "min-w-[360px]" : "min-w-[320px]",
                            !isOpen && "hidden"
                        )}
                        onWheel={(e) => e.stopPropagation()}
                    >
                        {dropdownContent}
                    </div>
                );
            })()}

            {/* Filter Side Panel - rendered as portal to avoid clipping (desktop only) */}
            {!isMobile && isFilterDropdownOpen && isOpen && filterPanelPosition && createPortal(
                <div
                    ref={filterDropdownRef}
                    data-model-dropdown-portal="true"
                    className="fixed bg-popover dark:bg-zinc-800 backdrop-blur-md border border-border dark:border-zinc-600/70 rounded-lg shadow-xl z-[9999] w-64"
                    style={{
                        top: `${filterPanelPosition.top}px`,
                        left: `${filterPanelPosition.left}px`,
                        maxHeight: 'calc(100vh - 80px)'
                    }}
                    onMouseDown={(e) => e.stopPropagation()}
                >
                    {/* Tab Headers with Clear Icon */}
                    <div className="flex items-center gap-1 p-2 border-b border-border dark:border-zinc-700/30">
                        {/* Clear filters icon - leftmost */}
                        {(selectedProviders.size > 0 || selectedFeatures.size > 0) && (
                            <button
                                onClick={clearAllFilters}
                                className="p-1.5 text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 hover:bg-red-500/10 transition-colors rounded"
                                title="Clear all filters"
                            >
                                <FilterX className="w-3.5 h-3.5" />
                            </button>
                        )}
                        <button
                            onClick={() => setFilterTab('provider')}
                            className={cn(
                                "flex-1 px-2 py-1.5 text-xs rounded transition-colors",
                                filterTab === 'provider'
                                    ? "bg-accent dark:bg-zinc-700/70 text-foreground"
                                    : "text-muted-foreground hover:text-foreground"
                            )}
                        >
                            Provider
                            {selectedProviders.size > 0 && (
                                <span className="ml-1 text-[10px] bg-blue-500/30 text-blue-600 dark:text-blue-300 px-1 rounded">
                                    {selectedProviders.size}
                                </span>
                            )}
                        </button>
                        <button
                            onClick={() => setFilterTab('features')}
                            className={cn(
                                "flex-1 px-2 py-1.5 text-xs rounded transition-colors",
                                filterTab === 'features'
                                    ? "bg-accent dark:bg-zinc-700/70 text-foreground"
                                    : "text-muted-foreground hover:text-foreground"
                            )}
                        >
                            Features
                            {selectedFeatures.size > 0 && (
                                <span className="ml-1 text-[10px] bg-blue-500/30 text-blue-600 dark:text-blue-300 px-1 rounded">
                                    {selectedFeatures.size}
                                </span>
                            )}
                        </button>
                    </div>

                    {/* Provider Tab Content */}
                    {filterTab === 'provider' && (
                        <div className="p-2">
                            {/* Provider search */}
                            <div className="relative mb-2">
                                <Search className="absolute left-2.5 top-1/2 transform -translate-y-1/2 w-2.5 h-2.5 text-muted-foreground dark:text-zinc-500" />
                                <input
                                    ref={providerSearchInputRef}
                                    type="text"
                                    placeholder="Search providers..."
                                    value={providerSearchQuery}
                                    onChange={(e) => setProviderSearchQuery(e.target.value)}
                                    className="w-full pl-7 pr-2.5 py-1.5 text-xs bg-muted/50 dark:bg-zinc-700/20 rounded text-foreground/80 placeholder:text-[hsl(var(--placeholder))] focus:outline-none border border-input dark:border-zinc-600/50"
                                />
                            </div>

                            {/* Provider list */}
                            <div className="h-52 overflow-y-auto scrollbar-subtle">
                                {filteredProviders.length === 0 ? (
                                    <div className="px-2.5 py-2 text-xs text-muted-foreground dark:text-zinc-500 text-center">
                                        No providers found
                                    </div>
                                ) : (
                                    filteredProviders.map((provider) => {
                                        const metadata = getProviderMetadata(provider);
                                        if (!metadata) return null; // Skip if no metadata
                                        const isSelected = selectedProviders.has(provider);
                                        return (
                                            <button
                                                key={provider}
                                                onClick={() => handleProviderToggle(provider)}
                                                className={cn(
                                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-1.5 rounded-sm mb-0.5",
                                                    isSelected
                                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                                )}
                                            >
                                                <div className="w-4 h-4 flex-shrink-0 flex items-center justify-center">
                                                    <div className="transform scale-[0.5]">
                                                        {metadata.icon}
                                                    </div>
                                                </div>
                                                <span className="truncate">{metadata.title}</span>
                                                {isSelected && (
                                                    <Check className="ml-auto w-3 h-3 text-foreground flex-shrink-0" />
                                                )}
                                            </button>
                                        );
                                    })
                                )}
                            </div>
                        </div>
                    )}

                    {/* Features Tab Content */}
                    {filterTab === 'features' && (
                        <div className="p-2 space-y-0.5">
                            <button
                                onClick={() => handleFeatureToggle('imageAnalysis')}
                                className={cn(
                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-2 rounded",
                                    selectedFeatures.has('imageAnalysis')
                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                )}
                            >
                                <Eye className="w-3.5 h-3.5 text-muted-foreground/80 dark:text-zinc-400/80 flex-shrink-0" />
                                <span className="flex-1">Image Analysis</span>
                                {selectedFeatures.has('imageAnalysis') && (
                                    <Check className="w-3 h-3 text-foreground flex-shrink-0" />
                                )}
                            </button>

                            <button
                                onClick={() => handleFeatureToggle('imageGeneration')}
                                className={cn(
                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-2 rounded",
                                    selectedFeatures.has('imageGeneration')
                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                )}
                            >
                                <ImagePlus className="w-3.5 h-3.5 text-muted-foreground/80 dark:text-zinc-400/80 flex-shrink-0" />
                                <span className="flex-1">Image Generation</span>
                                {selectedFeatures.has('imageGeneration') && (
                                    <Check className="w-3 h-3 text-foreground flex-shrink-0" />
                                )}
                            </button>

                            <button
                                onClick={() => handleFeatureToggle('reasoning')}
                                className={cn(
                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-2 rounded",
                                    selectedFeatures.has('reasoning')
                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                )}
                            >
                                <Brain className="w-3.5 h-3.5 text-muted-foreground/80 dark:text-zinc-400/80 flex-shrink-0" />
                                <span className="flex-1">Reasoning</span>
                                {selectedFeatures.has('reasoning') && (
                                    <Check className="w-3 h-3 text-foreground flex-shrink-0" />
                                )}
                            </button>

                            <button
                                onClick={() => handleFeatureToggle('tools')}
                                className={cn(
                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-2 rounded",
                                    selectedFeatures.has('tools')
                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                )}
                            >
                                <Wrench className="w-3.5 h-3.5 text-muted-foreground/80 dark:text-zinc-400/80 flex-shrink-0" />
                                <span className="flex-1">Tool Support</span>
                                {selectedFeatures.has('tools') && (
                                    <Check className="w-3 h-3 text-foreground flex-shrink-0" />
                                )}
                            </button>

                            <button
                                onClick={() => handleFeatureToggle('videoGeneration')}
                                className={cn(
                                    "w-full px-2.5 py-1.5 text-xs transition-colors text-left flex items-center gap-2 rounded",
                                    selectedFeatures.has('videoGeneration')
                                        ? "bg-accent dark:bg-zinc-700/50 text-foreground"
                                        : "text-muted-foreground hover:bg-accent/50 dark:hover:bg-zinc-700/30 hover:text-foreground"
                                )}
                            >
                                <Video className="w-3.5 h-3.5 text-muted-foreground/80 dark:text-zinc-400/80 flex-shrink-0" />
                                <span className="flex-1">Video Generation</span>
                                {selectedFeatures.has('videoGeneration') && (
                                    <Check className="w-3 h-3 text-foreground flex-shrink-0" />
                                )}
                            </button>
                        </div>
                    )}
                </div>,
                document.body
            )}

            {/* Custom tooltip for capability icons */}
            {hoveredCapability && createPortal(
                <div
                    className="fixed z-[10000] px-2 py-1 text-xs text-foreground bg-card border border-border dark:border-zinc-700 rounded shadow-lg pointer-events-none whitespace-nowrap transition-opacity duration-150 animate-in fade-in"
                    style={{
                        left: `${hoveredCapability.x}px`,
                        top: `${hoveredCapability.y}px`,
                        transform: 'translate(-50%, -100%)'
                    }}
                >
                    {hoveredCapability.label}
                </div>,
                document.body
            )}
        </div>
    );
}
