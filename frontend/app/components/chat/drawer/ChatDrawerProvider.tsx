// Context provider for managing drawer state across the chat system
// Implements focus-based visibility where multiple drawers can be active
// but only the most recently activated one is visible

import { createContext, useState, useCallback, ReactNode, useRef } from 'react';

export interface DrawerOptions {
    /** Enable drag-to-resize functionality for this drawer. Default: false */
    resizable?: boolean;
    /** Apply emphasized treatment: dim the rest of the screen and animate a glow border around the drawer. Use for blocking flows like input requests. Default: false */
    emphasized?: boolean;
}

interface DrawerState {
    id: string;
    content: ReactNode;
    activatedAt: number;
    isClosing?: boolean;
    options?: DrawerOptions;
}

interface DrawerContextType {
    isOpen: boolean;
    content: ReactNode | null;
    visibleDrawerId: string | null;
    visibleDrawer: DrawerState | null;

    // Registry methods
    registerDrawer: (id: string, content: ReactNode, options?: DrawerOptions) => void;
    unregisterDrawer: (id: string) => void;
    updateDrawer: (id: string, content: ReactNode) => void;
}

export const DrawerContext = createContext<DrawerContextType | undefined>(undefined);

interface ChatDrawerProviderProps {
    children: ReactNode;
}

export function ChatDrawerProvider({ children }: ChatDrawerProviderProps) {
    const [activeDrawers, setActiveDrawers] = useState<Map<string, DrawerState>>(new Map());
    const [visibleDrawerId, setVisibleDrawerId] = useState<string | null>(null);
    const clearContentTimeoutRef = useRef<NodeJS.Timeout | null>(null);
    const pendingRemovals = useRef<Record<string, NodeJS.Timeout>>({});
    
    // Calculate derived state
    const isOpen = activeDrawers.size > 0;
    
    // Find the most recently activated closing drawer
    let closingDrawer: DrawerState | null = null;
    for (const drawer of activeDrawers.values()) {
        if (drawer.isClosing && (!closingDrawer || drawer.activatedAt > closingDrawer.activatedAt)) {
            closingDrawer = drawer;
        }
    }
    
    // Use visible drawer if available, otherwise use closing drawer for animation
    const visibleDrawer = visibleDrawerId 
        ? activeDrawers.get(visibleDrawerId) || null 
        : closingDrawer;
    
    const content = visibleDrawer?.content || null;

    const registerDrawer = useCallback((id: string, drawerContent: ReactNode, options?: DrawerOptions) => {
        console.log('[ChatDrawerProvider] registerDrawer called:', id, 'options:', options);
        console.log('[ChatDrawerProvider] Drawer content type:', typeof drawerContent);

        // Cancel any pending removal for this drawer
        if (pendingRemovals.current[id]) {
            clearTimeout(pendingRemovals.current[id]);
            delete pendingRemovals.current[id];
        }

        // Cancel any pending content clear
        if (clearContentTimeoutRef.current) {
            clearTimeout(clearContentTimeoutRef.current);
            clearContentTimeoutRef.current = null;
        }

        setActiveDrawers(prev => {
            const newMap = new Map(prev);
            newMap.set(id, {
                id,
                content: drawerContent,
                activatedAt: Date.now(),
                isClosing: false,
                options
            });
            console.log('[ChatDrawerProvider] Active drawers after register:', Array.from(newMap.keys()));
            return newMap;
        });

        setVisibleDrawerId(id);
        console.log('[ChatDrawerProvider] Set visible drawer ID to:', id);
    }, []);

    const unregisterDrawer = useCallback((id: string) => {
        console.log('[Drawer] unregisterDrawer called:', id);
        
        setActiveDrawers(prev => {
            const drawer = prev.get(id);
            if (!drawer) return prev;
            
            // Mark drawer as closing (keep it in activeDrawers for animation)
            const newMap = new Map(prev);
            newMap.set(id, { ...drawer, isClosing: true });
            
            // If this was the visible drawer, find the next one to show
            if (id === visibleDrawerId) {
                let mostRecentDrawer: DrawerState | null = null;
                for (const drawerState of prev.values()) {
                    if (drawerState.id !== id &&
                        !drawerState.isClosing &&
                        (!mostRecentDrawer || drawerState.activatedAt > mostRecentDrawer.activatedAt)) {
                        mostRecentDrawer = drawerState;
                    }
                }
                setVisibleDrawerId(mostRecentDrawer?.id || null);
            }
            
            return newMap;
        });
        
        // Track the removal timeout to prevent conflicts with re-registration
        pendingRemovals.current[id] = setTimeout(() => {
            setActiveDrawers(prev => {
                const newMap = new Map(prev);
                newMap.delete(id);
                return newMap;
            });
            delete pendingRemovals.current[id];
        }, 150);
    }, [visibleDrawerId]);

    const updateDrawer = useCallback((id: string, drawerContent: ReactNode) => {
        console.log('[Drawer] updateDrawer called:', id);

        setActiveDrawers(prev => {
            const newMap = new Map(prev);
            const existingDrawer = newMap.get(id);
            if (existingDrawer) {
                newMap.set(id, {
                    ...existingDrawer,
                    content: drawerContent
                });
            }
            return newMap;
        });
    }, []);


    return (
        <DrawerContext.Provider value={{
            isOpen,
            content,
            visibleDrawerId,
            visibleDrawer,
            registerDrawer,
            unregisterDrawer,
            updateDrawer
        }}>
            {children}
        </DrawerContext.Provider>
    );
}