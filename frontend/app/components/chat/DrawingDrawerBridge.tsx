// Bridge component that connects ViteViewer drawing events to ChatDrawer
// Lives inside ChatDrawerProvider context to register drawing options drawer

import { useEffect, useState, useCallback } from 'react';
import { useDrawer } from '~/hooks/useDrawer';
import { DrawingOptionsContent } from './drawer/DrawingOptionsDrawer';

export function DrawingDrawerBridge() {
    const { registerDrawer, unregisterDrawer, updateDrawer } = useDrawer();
    const [isDrawing, setIsDrawing] = useState(false);
    const [drawingTool, setDrawingTool] = useState<'pen' | 'eraser' | 'text'>('pen');
    const [drawingColor, setDrawingColor] = useState('#ef4444');
    const [canUndo, setCanUndo] = useState(false);
    const [canRedo, setCanRedo] = useState(false);

    // Stable callbacks that won't cause re-renders
    const handleToolChange = useCallback((tool: 'pen' | 'eraser' | 'text') => {
        setDrawingTool(tool);
        // Notify ViteViewer of tool change
        document.dispatchEvent(new CustomEvent('noclick:drawing-tool-change', {
            detail: { tool }
        }));
    }, []);

    const handleColorChange = useCallback((color: string) => {
        setDrawingColor(color);
        // Notify ViteViewer of color change
        document.dispatchEvent(new CustomEvent('noclick:drawing-color-change', {
            detail: { color }
        }));
    }, []);

    const handleClear = useCallback(() => {
        // Notify ViteViewer to clear drawing
        document.dispatchEvent(new CustomEvent('noclick:drawing-clear'));
    }, []);

    const handleClose = useCallback(() => {
        // Notify ViteViewer to stop drawing
        document.dispatchEvent(new CustomEvent('noclick:drawing-close'));
        setIsDrawing(false);
    }, []);

    const handleUndo = useCallback(() => {
        // Notify ViteViewer to undo
        document.dispatchEvent(new CustomEvent('noclick:drawing-undo'));
    }, []);

    const handleRedo = useCallback(() => {
        // Notify ViteViewer to redo
        document.dispatchEvent(new CustomEvent('noclick:drawing-redo'));
    }, []);

    // Listen for drawing state changes from ViteViewer
    useEffect(() => {
        const handleDrawingStateChange = (event: CustomEvent) => {
            const { isDrawing: enabled, tool, color } = event.detail || {};
            console.log('[DrawingDrawerBridge] Drawing state changed:', { enabled, tool, color });
            setIsDrawing(enabled);

            // When drawing is enabled, reset to pen tool to match iframe's default
            if (enabled) {
                setDrawingTool(tool || 'pen');
                // If no color provided, keep current color
                if (color) setDrawingColor(color);
            } else {
                // When drawing is disabled, still update if tool/color provided
                if (tool) setDrawingTool(tool);
                if (color) setDrawingColor(color);
            }
        };

        document.addEventListener('noclick:drawing-state-changed', handleDrawingStateChange as EventListener);
        return () => {
            document.removeEventListener('noclick:drawing-state-changed', handleDrawingStateChange as EventListener);
        };
    }, []);

    // Listen for drawing history state changes from ViteViewer
    useEffect(() => {
        const handleHistoryStateChange = (event: CustomEvent) => {
            const { canUndo: undo, canRedo: redo } = event.detail || {};
            console.log('[DrawingDrawerBridge] History state changed:', { canUndo: undo, canRedo: redo });
            setCanUndo(undo || false);
            setCanRedo(redo || false);
        };

        document.addEventListener('noclick:drawing-history-state', handleHistoryStateChange as EventListener);
        return () => {
            document.removeEventListener('noclick:drawing-history-state', handleHistoryStateChange as EventListener);
        };
    }, []);

    // Register/unregister drawer when drawing state changes (only depends on isDrawing)
    useEffect(() => {
        if (isDrawing) {
            console.log('[DrawingDrawerBridge] Registering drawing options drawer');
            // Initial registration with current values
            registerDrawer('drawing-options',
                <DrawingOptionsContent
                    currentTool={drawingTool}
                    currentColor={drawingColor}
                    canUndo={canUndo}
                    canRedo={canRedo}
                    onToolChange={handleToolChange}
                    onColorChange={handleColorChange}
                    onClear={handleClear}
                    onClose={handleClose}
                    onUndo={handleUndo}
                    onRedo={handleRedo}
                />
            );
        } else {
            console.log('[DrawingDrawerBridge] Unregistering drawing options drawer');
            unregisterDrawer('drawing-options');
        }

        return () => {
            unregisterDrawer('drawing-options');
        };
        // Only depend on isDrawing state and stable callbacks
    }, [isDrawing, registerDrawer, unregisterDrawer, handleToolChange, handleColorChange, handleClear, handleClose, handleUndo, handleRedo]);

    // Update drawer content when tool, color, or history state changes (without re-registering)
    useEffect(() => {
        if (isDrawing) {
            console.log('[DrawingDrawerBridge] Updating drawing options drawer with tool:', drawingTool, 'color:', drawingColor, 'canUndo:', canUndo, 'canRedo:', canRedo);
            updateDrawer('drawing-options',
                <DrawingOptionsContent
                    currentTool={drawingTool}
                    currentColor={drawingColor}
                    canUndo={canUndo}
                    canRedo={canRedo}
                    onToolChange={handleToolChange}
                    onColorChange={handleColorChange}
                    onClear={handleClear}
                    onClose={handleClose}
                    onUndo={handleUndo}
                    onRedo={handleRedo}
                />
            );
        }
    }, [isDrawing, drawingTool, drawingColor, canUndo, canRedo, updateDrawer, handleToolChange, handleColorChange, handleClear, handleClose, handleUndo, handleRedo]);

    return null; // Bridge component renders nothing
}