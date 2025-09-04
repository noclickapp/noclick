// Drawing options drawer component for controlling drawing tools in ViteViewer
// Provides color selection, pen/eraser tools, and clear functionality
// Replaces the hover-based toolbar that was previously shown in the iframe

import { useState, useEffect, useCallback } from 'react';
import { Pen, Eraser, Trash2, Check } from 'lucide-react';
import { useDrawer } from '~/hooks/useDrawer';
import { Button } from '~/components/ui/button';

interface DrawingOptionsDrawerProps {
    isDrawing: boolean;
    currentTool?: 'pen' | 'eraser';
    currentColor?: string;
    onToolChange: (tool: 'pen' | 'eraser') => void;
    onColorChange: (color: string) => void;
    onClear: () => void;
    onClose: () => void;
}

const PRESET_COLORS = [
    '#ef4444', // Modern Red
    '#f97316', // Modern Orange  
    '#eab308', // Modern Yellow
    '#22c55e', // Modern Green
    '#06b6d4', // Modern Cyan
    '#3b82f6', // Modern Blue
    '#8b5cf6', // Modern Purple
    '#ec4899', // Modern Pink
    '#000000', // Black
    '#ffffff', // White
];

// Persistent state that survives drawer open/close cycles
let persistentState = {
    tool: 'pen' as 'pen' | 'eraser',
    color: '#ef4444'
};

// Separate component for drawer content to avoid re-registration issues
export function DrawingOptionsContent({ 
    currentTool: externalTool,
    currentColor: externalColor,
    onToolChange, 
    onColorChange, 
    onClear,
    onClose
}: Omit<DrawingOptionsDrawerProps, 'isDrawing'>) {
    // Initialize with external props, persistent state, or defaults in that order
    const [currentTool, setCurrentTool] = useState<'pen' | 'eraser'>(() => {
        return externalTool || persistentState.tool;
    });
    const [currentColor, setCurrentColor] = useState(() => {
        return externalColor || persistentState.color;
    });
    
    // Sync with external state when it changes
    useEffect(() => {
        if (externalTool) {
            setCurrentTool(externalTool);
            persistentState.tool = externalTool;
        }
    }, [externalTool]);
    
    useEffect(() => {
        if (externalColor) {
            setCurrentColor(externalColor);
            persistentState.color = externalColor;
        }
    }, [externalColor]);
    
    const handleToolChange = useCallback((tool: 'pen' | 'eraser', event?: React.MouseEvent) => {
        // Prevent event from bubbling up and potentially closing the drawer
        event?.stopPropagation();
        event?.preventDefault();

        setCurrentTool(tool);
        persistentState.tool = tool;
        onToolChange(tool);
    }, [onToolChange]);
    
    const handleColorChange = useCallback((color: string) => {
        setCurrentColor(color);
        persistentState.color = color;
        onColorChange(color);
        // When selecting a color, automatically switch to pen
        if (currentTool === 'eraser') {
            handleToolChange('pen');
        }
    }, [currentTool, onColorChange, handleToolChange]);
    
    return (
        <div className="p-3 space-y-2.5">
            {/* Header */}
            <div className="mb-1">
                <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Drawing Tools</h3>
            </div>
            
            {/* Tool Selection */}
            <div className="flex justify-end gap-1.5 px-2">
                <Button
                    size="sm"
                    onClick={(e) => handleToolChange('pen', e)}
                    className={`h-8 w-8 p-0 transition-all rounded-lg bg-zinc-800/80 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 ${
                        currentTool === 'pen' 
                            ? 'border-2 text-zinc-200' 
                            : 'border border-zinc-700'
                    }`}
                    style={{
                        borderColor: currentTool === 'pen' ? currentColor : undefined
                    }}
                    title="Pen Tool"
                >
                    <Pen className="h-3.5 w-3.5" />
                </Button>
                <Button
                    size="sm"
                    onClick={(e) => handleToolChange('eraser', e)}
                    className={`h-8 w-8 p-0 transition-all rounded-lg bg-zinc-800/80 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 ${
                        currentTool === 'eraser' 
                            ? 'border-2 border-red-400 text-red-300' 
                            : 'border border-zinc-700'
                    }`}
                    title="Eraser"
                >
                    <Eraser className="h-3.5 w-3.5" />
                </Button>
            </div>
            
            {/* Color Grid */}
            <div className="space-y-1">
                <div className="flex gap-1 px-2">
                    {PRESET_COLORS.slice(0, 5).map((color) => (
                        <button
                            key={color}
                            onClick={() => handleColorChange(color)}
                            className={`flex-1 h-6 rounded-sm border transition-all hover:scale-105 relative ${
                                currentColor === color && currentTool === 'pen'
                                    ? 'border-white shadow-md scale-105 ring-2 ring-white/30'
                                    : 'border-zinc-600 hover:border-zinc-400'
                            } ${currentTool === 'eraser' ? 'opacity-30 cursor-not-allowed' : ''} ${
                                color === '#ffffff' ? 'border-zinc-500' : ''
                            }`}
                            style={{ backgroundColor: color }}
                            title={`Color: ${color}`}
                            disabled={currentTool === 'eraser'}
                        >
                        </button>
                    ))}
                </div>
                <div className="flex gap-1 px-2">
                    {PRESET_COLORS.slice(5).map((color) => (
                        <button
                            key={color}
                            onClick={() => handleColorChange(color)}
                            className={`flex-1 h-6 rounded-sm border transition-all hover:scale-105 relative ${
                                currentColor === color && currentTool === 'pen'
                                    ? 'border-white shadow-md scale-105 ring-2 ring-white/30'
                                    : 'border-zinc-600 hover:border-zinc-400'
                            } ${currentTool === 'eraser' ? 'opacity-30 cursor-not-allowed' : ''} ${
                                color === '#ffffff' ? 'border-zinc-500' : ''
                            }`}
                            style={{ backgroundColor: color }}
                            title={`Color: ${color}`}
                            disabled={currentTool === 'eraser'}
                        >
                        </button>
                    ))}
                </div>
            </div>
            
            {/* Actions */}
            <div className="flex justify-between px-2">
                <Button
                    size="sm"
                    onClick={onClear}
                    className="h-8 px-3 bg-red-500/10 hover:bg-red-500/20 text-red-400 hover:text-red-300 border border-red-500/30 hover:border-red-500/50 transition-all flex items-center gap-1.5 rounded-md font-medium"
                    title="Clear Drawing"
                >
                    <Trash2 className="h-3.5 w-3.5" />
                    <span className="text-xs">Clear</span>
                </Button>
                <Button
                    size="sm"
                    onClick={onClose}
                    className="h-8 px-3 bg-white/10 hover:bg-white/20 text-white/70 hover:text-white/90 border border-white/30 hover:border-white/50 transition-all duration-200 flex items-center gap-1.5 rounded-md font-medium"
                    title="Finish Drawing"
                >
                    <Check className="h-3.5 w-3.5" />
                    <span className="text-xs">Done</span>
                </Button>
            </div>
        </div>
    );
}

export function DrawingOptionsDrawer({ 
    isDrawing,
    currentTool,
    currentColor,
    onToolChange, 
    onColorChange, 
    onClear,
    onClose
}: DrawingOptionsDrawerProps) {
    const { registerDrawer, unregisterDrawer } = useDrawer();
    
    // Reset persistent state to match iframe defaults when drawing is enabled
    useEffect(() => {
        if (isDrawing) {
            // Reset persistent state to match iframe's default state (pen mode)
            persistentState.tool = 'pen';
            console.log('[DrawingOptionsDrawer] Reset persistent state to pen mode to match iframe');
        }
    }, [isDrawing]);
    
    useEffect(() => {
        if (isDrawing) {
            console.log('[DrawingOptionsDrawer] Registering drawer');
            // Register with a stable component reference
            registerDrawer('drawing-options', 
                <DrawingOptionsContent 
                    currentTool={currentTool}
                    currentColor={currentColor}
                    onToolChange={onToolChange}
                    onColorChange={onColorChange}
                    onClear={onClear}
                    onClose={onClose}
                />
            );
        } else {
            console.log('[DrawingOptionsDrawer] Unregistering drawer');
            unregisterDrawer('drawing-options');
        }
        
        return () => {
            unregisterDrawer('drawing-options');
        };
    }, [isDrawing, currentTool, currentColor, onToolChange, onColorChange, onClear, onClose, registerDrawer, unregisterDrawer]);
    
    return null; // This component manages drawer state only
}