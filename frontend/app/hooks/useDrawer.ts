// Hook for accessing drawer controls from any component
// Provides registry-based drawer management with focus-based visibility

import { useContext } from 'react';
import { DrawerContext } from '~/components/chat/drawer/ChatDrawerProvider';

export function useDrawer() {
    const context = useContext(DrawerContext);
    
    if (!context) {
        throw new Error('useDrawer must be used within a ChatDrawerProvider');
    }
    
    return {
        isOpen: context.isOpen,
        content: context.content,
        visibleDrawerId: context.visibleDrawerId,
        visibleDrawer: context.visibleDrawer,
        registerDrawer: context.registerDrawer,
        unregisterDrawer: context.unregisterDrawer,
        updateDrawer: context.updateDrawer,
    };
}