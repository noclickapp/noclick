// Slash command options component that displays available commands
// Filters based on input and handles command selection

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { cn } from '~/lib/utils';
import {
    Trash2,
    Sparkles,
    ArrowLeft,
    Users,
    LogOut,
    BarChart3,
    Pencil,
    MousePointerClick,
    Bug,
    Cpu,
} from 'lucide-react';
import { useAPIKeys } from '~/hooks/useAPIKeys';
import { useDrawer } from '~/hooks/useDrawer';
import { useCachedValtioState } from '~/hooks/useCachedValtioState';
import { toast } from 'sonner';
import { useAnalytics } from '~/lib/analytics';
import { useLocation } from 'react-router';
import { useDebugToolsEnabled } from '~/hooks/useDebugToolsEnabled';
import { ModelProvider } from '~/types/provider';
import { APIKeyRequestDrawer } from './APIKeyRequestDrawer';

// Custom Claude icon component
const ClawdIcon = ({ className, isSelected }: { className?: string, isSelected?: boolean }) => (
    <img
        src="/icons/clawd.svg"
        alt="Claude"
        className={cn(className, 'w-3.5 h-3.5')}
        style={{
            filter: isSelected ? 'brightness(1.1)' : 'grayscale(100%) brightness(0.85)',
            opacity: isSelected ? 1 : 0.85,
            objectFit: 'contain',
            transform: 'scale(1.4)'
        }}
    />
);

interface NestedOption {
    id: string;
    label: string;
    description?: string;
    isDefault?: boolean;
    suboptions?: NestedOption[];
    action?: () => void;
}

export interface Command {
    id: string;
    label: string;
    description: string;
    icon: React.ComponentType<{ className?: string }>;
    action?: () => void;
    suboptions?: NestedOption[];
    isDefault?: boolean;
}

interface ChatSlashOptionsProps {
    inputValue: string;
    onCommandSelect: (command: Command) => void;
    onInputChange: (value: string) => void;
    onModelSelect?: (model: string) => void;
    onClose: () => void;
}

// Define base commands (will be filtered based on context in component)
const getBaseCommands = (): Command[] => [
        // {
        //     id: 'model',
        //     label: '/model',
        //     description: 'Select AI model',
        //     icon: Cpu,
        //     suboptions: [
        //         {
        //             id: 'gpt-5',
        //             label: 'gpt-5',
        //             description: 'Latest GPT model',
        //             suboptions: [
        //                 {
        //                     id: 'gpt-5-think',
        //                     label: 'think',
        //                     description: 'Deep reasoning',
        //                     isDefault: true
        //                 },
        //                 {
        //                     id: 'gpt-5-medium',
        //                     label: 'medium',
        //                     description: 'Balanced'
        //                 },
        //                 {
        //                     id: 'gpt-5-low',
        //                     label: 'low',
        //                     description: 'Fast response'
        //                 }
        //             ]
        //         },
        //         {
        //             id: 'claude-4-sonnet',
        //             label: 'claude-4-sonnet',
        //             description: 'Latest Claude model',
        //             isDefault: true
        //         },
        //         {
        //             id: 'claude-4-opus',
        //             label: 'claude-4-opus',
        //             description: 'Most capable Claude'
        //         },
        //         {
        //             id: 'gemini-2.5-pro',
        //             label: 'gemini-2.5-pro',
        //             description: 'Google\'s latest model'
        //         },
        //         {
        //             id: 'gpt-4o',
        //             label: 'gpt-4o',
        //             description: 'Multimodal GPT'
        //         }
        //     ]
        // },
        {
            id: 'clear',
            label: '/clear',
            description: 'Clear chat history (/new, /reset)',
            icon: Trash2,
            action: () => {
                // Dispatch event - NoClick.tsx will handle clearing and sending request to backend
                document.dispatchEvent(new CustomEvent('noclick:clear-messages'));
            }
        },
        {
            id: 'draw',
            label: '/draw',
            description: 'Start drawing/annotation mode',
            icon: Pencil,
            action: () => {
                // Dispatch event - ViteViewer will handle opening drawing mode
                document.dispatchEvent(new CustomEvent('noclick:open-drawing'));
            }
        },
        {
            id: 'select',
            label: '/select',
            description: 'Start element inspector mode',
            icon: MousePointerClick,
            action: () => {
                // Dispatch event - ViteViewer will handle opening inspector mode
                document.dispatchEvent(new CustomEvent('noclick:toggle-inspector'));
            }
        },
        {
            id: 'claude',
            label: '/claude',
            description: 'Launch Claude Code in app directory',
            icon: ClawdIcon,
            action: () => {
                // Dispatch event - parent will handle launching Claude Code
                document.dispatchEvent(new CustomEvent('noclick:launch-claude'));
            }
        },
        {
            id: 'community',
            label: '/community',
            description: 'Join our Discord community (support)',
            icon: Users,
            action: () => {
                window.open('https://discord.com/invite/sHC2mrnss8', '_blank');
            }
        },
        {
            id: 'stars',
            label: '/stars',
            description: 'Set number of background stars (/stars <num>)',
            icon: Sparkles,
            // This command requires input parsing, action will be handled in parent
        },
        {
            id: 'usage',
            label: '/usage',
            description: 'View usage statistics and costs',
            icon: BarChart3,
            // This will be handled by the parent to show the drawer
        },
        {
            id: 'debug',
            label: '/debug',
            description: 'View SQL query performance logs (developers)',
            icon: Bug,
            // This will be handled by the parent to show the drawer
        },
        {
            id: 'logout',
            label: '/logout',
            description: 'Log out of your account',
            icon: LogOut,
            action: async () => {
                const formData = new FormData();
                await fetch('/dashboard', {
                    method: 'POST',
                    body: formData,
                });
                window.location.href = '/auth/login';
            }
        }
    ];

// Helper function to check if option has suboptions with defaults
const hasDefaultSuboptions = (option: Command | NestedOption): boolean => {
    return !!(option.suboptions && option.suboptions.some(sub => sub.isDefault));
};

// Helper function to get provider from model name
const getProviderForModel = (model: string): ModelProvider | null => {
    const modelLower = model.toLowerCase();
    if (modelLower.includes('gpt')) return ModelProvider.OPENAI;
    if (modelLower.includes('claude')) return ModelProvider.ANTHROPIC;
    if (modelLower.includes('gemini')) return ModelProvider.GEMINI;
    return null;
};

// Recursively select all default options through nested levels
const selectAllDefaults = (option: Command | NestedOption): { path: string[], finalOption: NestedOption | null } => {
    const path: string[] = [];
    let currentOption: Command | NestedOption = option;
    let finalOption: NestedOption | null = null;
    
    while (currentOption.suboptions && currentOption.suboptions.length > 0) {
        const defaultSub = currentOption.suboptions.find(sub => sub.isDefault);
        if (defaultSub) {
            path.push(defaultSub.label);
            finalOption = defaultSub;
            currentOption = defaultSub;
        } else {
            // No default found, stop here
            break;
        }
    }
    
    return { path, finalOption };
};

export function ChatSlashOptions({
    inputValue,
    onCommandSelect,
    onInputChange,
    onModelSelect,
    onClose
}: ChatSlashOptionsProps) {
    const location = useLocation();
    const [selectedIndex, setSelectedIndex] = useState(0);
    const [navigationPath, setNavigationPath] = useState<string[]>([]);
    const [, setIsShowingApiKeyDrawer] = useState(false);
    // Track if selection change was from keyboard (to avoid scrollIntoView on hover)
    const isKeyboardNavRef = useRef(false);
    const apiKeys = useAPIKeys();
    const { registerDrawer, unregisterDrawer } = useDrawer();
    const [starCount, setStarCount] = useCachedValtioState('noclick-ui', 'starCount', 250);
    const { logActivity } = useAnalytics();
    const debugToolsEnabled = useDebugToolsEnabled();

    // Check if an app is currently open from URL query parameter
    const activeAppId = useMemo(() => {
        const params = new URLSearchParams(location.search);
        return params.get('vite');
    }, [location.search]);

    // Filter commands based on context (only show /claude, /draw, /select when app is active)
    // Also filter /debug based on feature flag
    const commands = useMemo(() => {
        let baseCommands = getBaseCommands();

        // Filter out debug commands if not enabled
        if (!debugToolsEnabled) {
            baseCommands = baseCommands.filter(cmd => cmd.id !== 'debug');
        }

        if (!activeAppId) {
            // No app active, filter out app-specific commands
            return baseCommands.filter(cmd => !['claude', 'draw', 'select'].includes(cmd.id));
        }
        return baseCommands;
    }, [activeAppId, debugToolsEnabled]);

    const [currentOptions, setCurrentOptions] = useState<(Command | NestedOption)[]>(commands);
    
    // Helper function to handle model selection with API key check
    const handleModelSelection = useCallback((modelName: string) => {
        const provider = getProviderForModel(modelName);
        
        if (provider && !apiKeys.hasKey(provider)) {
            // Mark that we're showing the API key drawer
            setIsShowingApiKeyDrawer(true);
            
            // Register API key request drawer
            registerDrawer(
                `api-key-${provider}`,
                <APIKeyRequestDrawer
                    provider={provider}
                    onKeySubmit={(keys) => {
                        apiKeys.saveKeys(keys);
                        if (onModelSelect) {
                            onModelSelect(modelName);
                        }
                        setIsShowingApiKeyDrawer(false);
                        unregisterDrawer(`api-key-${provider}`);
                        onClose(); // Close ChatSlashOptions too
                    }}
                    onClose={() => {
                        setIsShowingApiKeyDrawer(false);
                        unregisterDrawer(`api-key-${provider}`);
                        // Don't close ChatSlashOptions - user might want to select another model
                    }}
                />
            );
        } else {
            // Normal model selection
            if (onModelSelect) {
                onModelSelect(modelName);
            }
            onClose(); // Close ourselves
        }
    }, [apiKeys, registerDrawer, unregisterDrawer, onModelSelect, onClose]);

    // Helper function to handle /stars command with input parsing
    const handleStarsCommand = useCallback((input: string) => {
        const trimmed = input.trim();
        const match = trimmed.match(/^\/stars\s+(\d+)$/);

        if (match) {
            const count = parseInt(match[1], 10);
            if (count <= 0) {
                toast.error('"We\'re supposed to look up and wonder at our place in the stars, not look down and worry about our place in the dirt" - Cooper', {
                    duration: 4000,
                });
                return false;
            } else {
                setStarCount(count);
                // Log analytics for star command usage
                logActivity('star_command_used', {
                    star_count: count,
                    previous_count: starCount
                });
                toast.success(`Background stars set to ${count}`, {
                    duration: 2000,
                });
                // Find the stars command to pass to onCommandSelect for input clearing
                const starsCommand = commands.find(cmd => cmd.id === 'stars');
                if (starsCommand) {
                    onCommandSelect(starsCommand);
                }
                onClose();
                return true;
            }
        }
        return false;
    }, [setStarCount, onCommandSelect, onClose, starCount, logActivity]);

    // Reset state when component mounts or input becomes "/"
    useEffect(() => {
        if (inputValue === '/') {
            setNavigationPath([]);
            setCurrentOptions(commands);
            setSelectedIndex(0);
        }
    }, [inputValue, commands]);

    // Update navigation state based on input changes
    useEffect(() => {
        const inputLower = inputValue.toLowerCase().trim();
        const endsWithSpace = inputValue.endsWith(' ');
        
        // Parse input to determine correct navigation state
        // Split by space but handle the initial slash correctly
        const withoutInitialSlash = inputLower.startsWith('/') ? inputLower.slice(1) : inputLower;
        const segments = withoutInitialSlash.split(' ').filter(Boolean);
        
        if (segments.length === 0) {
            // Empty input, reset to top level
            if (navigationPath.length > 0) {
                setNavigationPath([]);
                setCurrentOptions(commands);
                setSelectedIndex(0);
            }
            return;
        }
        
        // Walk the command tree to find navigation segments vs search terms
        let currentLevel: (Command | NestedOption)[] = commands;
        const correctPath: string[] = [];
        let targetOptions: (Command | NestedOption)[] = commands;
        
        for (let i = 0; i < segments.length; i++) {
            const segment = segments[i];
            const expectedLabel = i === 0 ? `/${segment}` : segment;
            
            const match = currentLevel.find(item => 
                item.label.toLowerCase() === expectedLabel
            );
            
            if (match) {
                
                // If this is the last segment
                if (i === segments.length - 1) {
                    // Only navigate if there's a trailing space indicating intent to drill down
                    if (endsWithSpace && match.suboptions) {
                        correctPath.push(match.label);
                        targetOptions = match.suboptions;
                    } else {
                        // No space - stay at current level for filtering the exact match
                        targetOptions = currentLevel;
                        break;
                    }
                } else {
                    // Not the last segment, this is a confirmed navigation segment
                    correctPath.push(match.label);
                    if (match.suboptions) {
                        currentLevel = match.suboptions;
                    }
                }
            } else {
                // No exact match found - remaining segments are search terms
                // Use the current level for display and let filtering handle the rest
                targetOptions = currentLevel;
                break;
            }
        }
        
        // Update navigation state if it has changed
        const newPathString = correctPath.join(' ');
        const currentPathString = navigationPath.join(' ');
        const optionsChanged = targetOptions.length !== currentOptions.length || 
            targetOptions[0]?.label !== currentOptions[0]?.label;
        
        if (newPathString !== currentPathString || optionsChanged) {
            setNavigationPath(correctPath);
            setCurrentOptions(targetOptions);
            setSelectedIndex(0);
        }
    }, [inputValue, currentOptions, navigationPath]);

    // Manage own lifecycle - close when input is cleared or doesn't start with '/'
    useEffect(() => {
        // If input is cleared or doesn't start with '/', close ourselves
        if (!inputValue || !inputValue.startsWith('/')) {
            onClose();
        }
    }, [inputValue, onClose]);

    // Calculate display options based on current state
    const displayOptions = useMemo(() => {
        if (navigationPath.length > 0) {
            // We're in a nested level, filter current options by any search term
            const inputLower = inputValue.toLowerCase();
            const expectedPrefix = navigationPath.join(' ').toLowerCase() + ' ';
            
            if (inputLower.startsWith(expectedPrefix)) {
                const searchTerm = inputLower.slice(expectedPrefix.length).trim();
                if (searchTerm) {
                    const filtered = currentOptions.filter(option => 
                        option.label.toLowerCase().includes(searchTerm) ||
                        (option.description && option.description.toLowerCase().includes(searchTerm))
                    );
                    return filtered;
                }
            }
            
            return currentOptions;
        } else {
            // Top level - filter commands by search
            const searchQuery = inputValue.slice(1).toLowerCase().trim();
            const filtered = commands.filter(cmd => 
                cmd.label.toLowerCase().includes(searchQuery) ||
                cmd.description.toLowerCase().includes(searchQuery)
            );
            return filtered;
        }
    }, [inputValue, navigationPath, currentOptions]);
    
    // Reset selection when display options change
    useEffect(() => {
        setSelectedIndex(0);
    }, [displayOptions]);
    
    // Scroll selected item into view when navigating with keyboard (not on hover)
    useEffect(() => {
        if (selectedIndex >= 0 && displayOptions.length > 0 && isKeyboardNavRef.current) {
            // Reset the flag after handling
            isKeyboardNavRef.current = false;
            // Use requestAnimationFrame to ensure DOM is updated
            requestAnimationFrame(() => {
                const buttons = document.querySelectorAll('.overflow-y-auto.scrollbar-subtle button');
                const selectedButton = buttons[selectedIndex] as HTMLElement;
                if (selectedButton) {
                    selectedButton.scrollIntoView({
                        block: 'nearest',
                        behavior: 'smooth'
                    });
                }
            });
        }
    }, [selectedIndex, displayOptions.length]);
    
    // Navigate into suboptions
    const navigateInto = useCallback((option: Command | NestedOption) => {
        if (option.suboptions && option.suboptions.length > 0) {
            setCurrentOptions(option.suboptions);
            setNavigationPath(prev => [...prev, option.label]);
            setSelectedIndex(0);
        } else if (option.action) {
            option.action();
            onCommandSelect(option as Command);
            onClose();
        }
    }, [onCommandSelect, onClose]);
    
    // Navigate back up the hierarchy
    // Navigate back by modifying input text (input-driven navigation)
    const navigateBack = useCallback(() => {
        const currentInput = inputValue.trim();
        
        if (currentInput === '/') {
            // At root level, close drawer
            onClose();
        } else if (currentInput.includes(' ')) {
            // Remove last segment and trailing space
            const segments = currentInput.split(' ');
            segments.pop(); // Remove last segment
            const newInput = segments.join(' ');
            onInputChange(newInput === '/' ? '/' : `${newInput} `);
        } else {
            // Single command, go back to root
            onInputChange('/');
        }
    }, [inputValue, onInputChange, onClose]);

    // Handle keyboard navigation
    useEffect(() => {
        const handleKeyDown = (e: Event) => {
            const keyboardEvent = e as unknown as KeyboardEvent;
            switch (keyboardEvent.key) {
                case 'ArrowDown':
                    keyboardEvent.preventDefault();
                    isKeyboardNavRef.current = true;
                    setSelectedIndex(prev =>
                        prev < displayOptions.length - 1 ? prev + 1 : 0
                    );
                    break;
                case 'ArrowUp':
                    keyboardEvent.preventDefault();
                    isKeyboardNavRef.current = true;
                    setSelectedIndex(prev =>
                        prev > 0 ? prev - 1 : displayOptions.length - 1
                    );
                    break;
                case 'Tab': {
                    keyboardEvent.preventDefault();
                    const tabOption = displayOptions[selectedIndex];
                    if (tabOption && tabOption.suboptions && tabOption.suboptions.length > 0) {
                        // Navigate into suboptions
                        const fullPath = navigationPath.length > 0 
                            ? `${navigationPath.join(' ')} ${tabOption.label} `
                            : `${tabOption.label} `;
                        onInputChange(fullPath);
                        setTimeout(() => {
                            setCurrentOptions(tabOption.suboptions!);
                            setNavigationPath(prev => [...prev, tabOption.label]);
                            setSelectedIndex(0);
                        }, 0);
                    }
                    break;
                }
                case 'Enter': {
                    keyboardEvent.preventDefault();

                    // Check for /stars command first
                    if (inputValue.trim().startsWith('/stars ')) {
                        const handled = handleStarsCommand(inputValue);
                        if (handled) {
                            return; // Exit early if command was handled
                        }
                    }

                    // Regular selection behavior - prioritize the selected item from filtered results
                    const selectedOption = displayOptions[selectedIndex];
                    if (selectedOption) {
                        // Check if option has default suboptions for automatic selection
                        if (hasDefaultSuboptions(selectedOption)) {
                            const { path: defaultPath, finalOption } = selectAllDefaults(selectedOption);
                            
                            // Handle model selections with all nested defaults
                            if (navigationPath.includes('/model') && onModelSelect) {
                                // Build complete model name WITHOUT the /model prefix
                                let fullModelName: string;
                                if (navigationPath.length > 1) {
                                    // We're already in a nested level (e.g., selected a variant)
                                    const modelName = navigationPath[1];
                                    fullModelName = `${modelName}-${selectedOption.label}`;
                                    if (defaultPath.length > 0) {
                                        fullModelName += `-${defaultPath.join('-')}`;
                                    }
                                } else {
                                    // Top level model selection - use the label without /model prefix
                                    const modelLabel = selectedOption.label.startsWith('/') 
                                        ? selectedOption.label.slice(1) 
                                        : selectedOption.label;
                                    fullModelName = defaultPath.length > 0
                                        ? `${modelLabel}-${defaultPath.join('-')}`
                                        : modelLabel;
                                }
                                handleModelSelection(fullModelName);
                            }
                            
                            if (finalOption?.action) {
                                finalOption.action();
                            } else if (selectedOption.action) {
                                selectedOption.action();
                            }
                            onCommandSelect(selectedOption as Command);
                            onClose();
                        }
                        // If it has suboptions but no defaults, navigate into them
                        else if (selectedOption.suboptions && selectedOption.suboptions.length > 0) {
                            // Build proper path for input completion
                            const fullPath = navigationPath.length > 0 
                                ? `${navigationPath.join(' ')} ${selectedOption.label} `
                                : `${selectedOption.label} `;
                            onInputChange(fullPath);
                            setTimeout(() => {
                                setCurrentOptions(selectedOption.suboptions!);
                                setNavigationPath(prev => [...prev, selectedOption.label]);
                                setSelectedIndex(0);
                            }, 0);
                        }
                        // If it's a final option (no suboptions), execute
                        else {
                            // Handle model selections with proper variant handling
                            if (navigationPath.includes('/model') && onModelSelect) {
                                // If we're deeper in the model path (e.g., gpt-5 -> think)
                                if (navigationPath.length > 1) {
                                    const modelName = navigationPath[1]; // e.g., "gpt-5"
                                    const variant = selectedOption.label; // e.g., "think"
                                    handleModelSelection(`${modelName}-${variant}`);
                                } else {
                                    // Direct model selection - remove any /model prefix
                                    const modelLabel = selectedOption.label.startsWith('/') 
                                        ? selectedOption.label.slice(1) 
                                        : selectedOption.label;
                                    handleModelSelection(modelLabel);
                                }
                            }
                            if (selectedOption.action) {
                                selectedOption.action();
                            }
                            onCommandSelect(selectedOption as Command);
                            onClose();
                        }
                    }
                    break;
                }
                case 'Escape':
                    keyboardEvent.preventDefault();
                    navigateBack();
                    break;
                case 'Backspace':
                    // Only handle backspace for navigation if not typing in input field or contenteditable
                    const activeEl = document.activeElement as HTMLElement;
                    const isEditable = activeEl?.tagName === 'TEXTAREA' || 
                                      activeEl?.tagName === 'INPUT' || 
                                      activeEl?.contentEditable === 'true';
                    if (!isEditable) {
                        keyboardEvent.preventDefault();
                        navigateBack();
                    }
                    break;
            }
        };
        
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [displayOptions, selectedIndex, navigateInto, navigateBack, onCommandSelect, onClose, inputValue, handleStarsCommand, onInputChange, navigationPath, onModelSelect, handleModelSelection]);
    
    // Handle option click
    const handleOptionClick = useCallback((option: Command | NestedOption, index: number) => {
        setSelectedIndex(index);
        if (option.suboptions && option.suboptions.length > 0) {
            // Build proper path for input completion
            const fullPath = navigationPath.length > 0 
                ? `${navigationPath.join(' ')} ${option.label} `
                : `${option.label} `;
            onInputChange(fullPath);
            // Use setTimeout to ensure input is updated before navigation state changes
            setTimeout(() => {
                setCurrentOptions(option.suboptions!);
                setNavigationPath(prev => [...prev, option.label]);
                setSelectedIndex(0);
            }, 0);
        } else {
            // Handle /stars command - focus the input for user to type the number
            if (option.id === 'stars') {
                onInputChange('/stars ');
                return; // Don't close the drawer, let user type the number
            }

            // Handle model selections with proper variant handling
            if (navigationPath.includes('/model') && onModelSelect) {
                // If we're deeper in the model path (e.g., gpt-5 -> think)
                if (navigationPath.length > 1) {
                    const modelName = navigationPath[1]; // e.g., "gpt-5"
                    const variant = option.label; // e.g., "think"
                    handleModelSelection(`${modelName}-${variant}`);
                } else {
                    // Direct model selection - remove any /model prefix
                    const modelLabel = option.label.startsWith('/') 
                        ? option.label.slice(1) 
                        : option.label;
                    handleModelSelection(modelLabel);
                }
            }
            if (option.action) {
                option.action();
            }
            onCommandSelect(option as Command);
            onClose();
        }
    }, [navigationPath, onInputChange, onModelSelect, onCommandSelect, onClose]);
    
    if (displayOptions.length === 0) {
        return (
            <div className="py-3 text-center text-muted-foreground dark:text-zinc-500">
                <p className="text-xs">No commands found</p>
                <p className="text-[10px] mt-0.5 text-muted-foreground/70 dark:text-zinc-600">Try typing a different command</p>
            </div>
        );
    }
    
    return (
        <div className="flex flex-col w-full">
            {/* Scrollable content area with explicit max-height for proper scrolling */}
            <div className="max-h-[calc(35vh-4rem)] overflow-y-auto scrollbar-subtle px-2">
                <div className="py-1">
                    {/* Header with navigation context */}
                    <div className="mb-1 flex items-center justify-between">
                        <div className="flex items-center gap-1">
                            {navigationPath.length > 0 && (
                                <button
                                    onClick={navigateBack}
                                    className="p-0.5 hover:bg-accent/50 dark:hover:bg-zinc-700/30 rounded transition-colors"
                                    aria-label="Go back"
                                >
                                    <ArrowLeft className="w-3 h-3 text-muted-foreground dark:text-zinc-500" />
                                </button>
                            )}
                            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                                {navigationPath.length > 0 ? navigationPath[navigationPath.length - 1].replace('/', '') : 'Commands'}
                            </h3>
                        </div>
                    </div>
                    
                    <div className="space-y-0.5">
                        {displayOptions.map((option, index) => {
                            const Icon = 'icon' in option ? option.icon : null;
                            const hasSuboptions = option.suboptions && option.suboptions.length > 0;
                            
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
                                    {Icon && (
                                        <Icon
                                            className={cn(
                                                'w-3.5 h-3.5 flex-shrink-0',
                                                selectedIndex === index ? 'text-blue-600 dark:text-blue-400' : 'text-muted-foreground dark:text-zinc-500'
                                            )}
                                        />
                                    )}

                                    <div className="flex items-center justify-between flex-1 min-w-0 overflow-hidden">
                                        <div className="flex items-center gap-1.5 flex-shrink-0">
                                            <span className={cn(
                                                'font-mono text-xs',
                                                selectedIndex === index ? 'text-foreground' : 'text-foreground/80'
                                            )}>
                                                {option.label}
                                            </span>
                                            {hasSuboptions && (
                                                <span className="px-1 py-0 bg-muted dark:bg-zinc-700/50 rounded text-[10px] text-muted-foreground font-mono">tab</span>
                                            )}
                                            {option.isDefault && (
                                                <span className="px-1 py-0 bg-foreground/10 text-muted-foreground dark:text-white/70 text-[10px] rounded border border-border dark:border-white/20">
                                                    default
                                                </span>
                                            )}
                                        </div>
                                        {option.description && (
                                            <span className={cn(
                                                'text-xs truncate ml-2',
                                                selectedIndex === index ? 'text-foreground/80' : 'text-muted-foreground dark:text-zinc-500'
                                            )}>
                                                {option.description}
                                            </span>
                                        )}
                                    </div>
                                </button>
                            );
                        })}
                    </div>
                </div>
            </div>
            
            {/* Fixed footer - always visible at bottom */}
            <div className="border-t border-border dark:border-zinc-700/50 pt-1 pb-2 px-2 flex-shrink-0 bg-popover/80 dark:bg-zinc-800/80">
                <div className="flex items-center gap-2 text-xs text-muted-foreground dark:text-zinc-500">
                    <span className="flex items-center gap-1">
                        <kbd className="px-1 py-0 bg-muted dark:bg-zinc-700/50 rounded text-xs text-muted-foreground">↑↓</kbd>
                        Navigate
                    </span>
                    {displayOptions[selectedIndex]?.suboptions && displayOptions[selectedIndex].suboptions!.length > 0 && (
                        <span className="flex items-center gap-1">
                            <kbd className="px-1 py-0 bg-muted dark:bg-zinc-700/50 rounded text-xs text-muted-foreground">tab</kbd>
                            Expand
                        </span>
                    )}
                    <span className="flex items-center gap-1">
                        <kbd className="px-1 py-0 bg-muted dark:bg-zinc-700/50 rounded text-xs text-muted-foreground">⏎</kbd>
                        {displayOptions[selectedIndex]?.suboptions && !hasDefaultSuboptions(displayOptions[selectedIndex]) 
                            ? 'Expand' 
                            : 'Select'}
                    </span>
                </div>
            </div>
        </div>
    );
}
