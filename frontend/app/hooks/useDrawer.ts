// Hook for accessing drawer controls from any component
// Provides registry-based drawer management with focus-based visibility

import { useContext } from 'react';
import { DrawerContext } from '~/components/chat/drawer/ChatDrawerProvider';

export function useDrawer() {
    const context = useContext(DrawerContext);
    
    if (!context) {
        // Return no-op functions when outside provider context
        // This allows components to work even when not wrapped in ChatDrawerProvider
        console.log('[useDrawer] No drawer context - returning no-op functions');
        return {
            isOpen: false,
            content: null,
            visibleDrawerId: null,
            visibleDrawer: null,
            registerDrawer: () => {},
            unregisterDrawer: () => {},
            updateDrawer: () => {},
            hasContext: false,
        };
    }
    
    console.log('[useDrawer] Context found, isOpen:', context.isOpen, 'visibleDrawerId:', context.visibleDrawerId);
    
    return {
        isOpen: context.isOpen,
        content: context.content,
        visibleDrawerId: context.visibleDrawerId,
        visibleDrawer: context.visibleDrawer,
        registerDrawer: context.registerDrawer,
        unregisterDrawer: context.unregisterDrawer,
        updateDrawer: context.updateDrawer,
        hasContext: true,
    };
}