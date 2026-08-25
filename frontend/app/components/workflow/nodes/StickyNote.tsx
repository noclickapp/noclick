/**
 * StickyNote component for rendering sticky notes in the workflow canvas.
 * Semi-transparent colored notes for annotating the graph.
 * Features resizable functionality, semi-transparent backgrounds, double-click editing, and markdown rendering.
 */
import { memo, useState, useRef, useEffect } from 'react';
import { NodeProps, NodeResizer } from '@xyflow/react';
import { MarkdownRenderer } from '~/components/chat/MarkdownRenderer';
import { Edit2, Trash2 } from 'lucide-react';
import { stickyColors, stickyScheme } from '~/lib/stickyColors';
import { useIsDark } from '~/hooks/useIsDark';
import './css/StickyNote.css';

interface StickyNoteData {
    label?: string;
    content?: string;
    color?: number;
    isSticky?: boolean;
    isEditing?: boolean;
    onContentChange?: (content: string) => void;
    onEditingChange?: (isEditing: boolean) => void;
    onColorChange?: (color: number) => void;
    onDelete?: () => void;
    metadata?: {
        source?: string;
        originalType?: string;
        originalName?: string;
    };
}

// Palette lives in ~/lib/stickyColors (a leaf module) so light surfaces can use
// it without importing this editor-heavy component graph; re-exported for
// existing importers.
export { stickyColors };

const StickyNote = ({ data, selected, id }: NodeProps) => {
    const nodeData = data as unknown as StickyNoteData;
    const {
        content = '',
        color = 8,
        label = 'Sticky Note',
        onContentChange,
        onColorChange,
        onDelete,
    } = nodeData;

    const [isEditing, setIsEditing] = useState(false);
    const [editContent, setEditContent] = useState(content);
    const [isColorPickerExpanded, setIsColorPickerExpanded] = useState(false);
    const [isColorPickerClosing, setIsColorPickerClosing] = useState(false);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    // Color scheme flips with the rendered theme (pastel-on-dark-text in light,
    // near-black-on-pastel-text in dark). Swatch accents stay theme-independent.
    const isDark = useIsDark();
    const colorScheme = stickyScheme(color, isDark);

    // Focus textarea when entering edit mode
    useEffect(() => {
        if (isEditing && textareaRef.current) {
            textareaRef.current.focus();
            // Move cursor to end
            textareaRef.current.setSelectionRange(
                textareaRef.current.value.length,
                textareaRef.current.value.length
            );
        }
    }, [isEditing]);

    const handleDoubleClick = () => {
        setIsEditing(true);
        setEditContent(content);
        // Notify parent that we're entering edit mode (for z-index)
        if (nodeData.onEditingChange) {
            nodeData.onEditingChange(true);
        }
    };

    const handleBlur = () => {
        setIsEditing(false);
        // Update content through callback if provided
        if (onContentChange && editContent !== content) {
            onContentChange(editContent);
        }
        // Notify parent that we're exiting edit mode
        if (nodeData.onEditingChange) {
            nodeData.onEditingChange(false);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        // Exit edit mode on Escape
        if (e.key === 'Escape') {
            setIsEditing(false);
            setEditContent(content); // Revert changes
            // Notify parent that we're exiting edit mode
            if (nodeData.onEditingChange) {
                nodeData.onEditingChange(false);
            }
        }
        // Don't propagate keyboard events to ReactFlow
        e.stopPropagation();
    };

    const handleEditClick = (e: React.MouseEvent) => {
        e.stopPropagation();
        setIsEditing(true);
        setEditContent(content);
        if (nodeData.onEditingChange) {
            nodeData.onEditingChange(true);
        }
    };

    const handleDeleteClick = (e: React.MouseEvent) => {
        e.stopPropagation();
        if (onDelete) {
            onDelete();
        }
    };

    const handleColorChange = (newColor: number, e: React.MouseEvent) => {
        e.stopPropagation();
        if (onColorChange) {
            onColorChange(newColor);
        }
        // Don't close the color picker - let users try multiple colors
    };

    const handleColorPickerMouseLeave = () => {
        // Trigger closing animation
        setIsColorPickerClosing(true);
        // Wait for animation to finish before actually closing
        setTimeout(() => {
            setIsColorPickerExpanded(false);
            setIsColorPickerClosing(false);
        }, 250); // Match animation duration
    };

    return (
        <>
            {/* NodeResizer - invisible handles but functional with resize cursors */}
            <NodeResizer
                color={colorScheme.accent}
                isVisible={true}
                minWidth={200}
                minHeight={150}
                handleStyle={{
                    width: '20px',
                    height: '20px',
                    border: 'none',
                    backgroundColor: 'transparent',
                    borderRadius: '0',
                    opacity: 0,
                }}
                lineStyle={{
                    border: 'none',
                    opacity: 0,
                }}
            />

            <div className="group sticky-note-wrapper">
                <div
                    className="rounded-lg shadow-lg relative overflow-hidden"
                    style={{
                        backgroundColor: colorScheme.bg,
                        border: `2px solid ${colorScheme.border}`,
                        width: '100%',
                        height: '100%',
                    }}
                    onDoubleClick={handleDoubleClick}
                >
                    {/* Content area */}
                    {isEditing ? (
                        <textarea
                            ref={textareaRef}
                            value={editContent}
                            onChange={(e) => setEditContent(e.target.value)}
                            onBlur={handleBlur}
                            onKeyDown={handleKeyDown}
                            className="nodrag p-4 text-sm whitespace-pre-wrap font-normal leading-relaxed w-full h-full resize-none outline-none bg-black/45 text-white/85"
                            placeholder="Add your notes here (markdown supported)..."
                        />
                    ) : (
                        <div
                            className="sticky-note-content p-4 text-sm overflow-hidden h-full"
                            style={{
                                // Override markdown renderer colors to match sticky note theme
                                ['--sticky-text-color' as string]:
                                    colorScheme.text,
                                ['--sticky-bg-color' as string]: colorScheme.bg,
                                ['--sticky-border-color' as string]:
                                    colorScheme.border,
                            }}
                        >
                            {content ? (
                                <MarkdownRenderer
                                    content={content}
                                    className="sticky-markdown"
                                    variant="sticky-note"
                                />
                            ) : (
                                <div
                                    className="font-normal leading-relaxed"
                                    style={{
                                        color: colorScheme.text,
                                        opacity: 0.6,
                                    }}
                                >
                                    Add your notes here (markdown supported)...
                                </div>
                            )}
                        </div>
                    )}

                    {/* Corner fold effect (top-right) */}
                    <div
                        className="absolute top-0 right-0 w-0 h-0 pointer-events-none"
                        style={{
                            borderStyle: 'solid',
                            borderWidth: '0 20px 20px 0',
                            borderColor: `transparent ${colorScheme.accent} transparent transparent`,
                            opacity: 0.4,
                        }}
                    />
                </div>

                {/* Action buttons - bottom left, visible on hover */}
                <div className="sticky-note-actions group-hover:opacity-100 opacity-0 transition-opacity duration-200">
                    {/* Edit button */}
                    <button
                        className="sticky-note-action-btn"
                        onClick={handleEditClick}
                        title="Edit note"
                    >
                        <Edit2 size={14} />
                    </button>

                    {/* Delete button */}
                    <button
                        className="sticky-note-action-btn delete-btn"
                        onClick={handleDeleteClick}
                        title="Delete note"
                    >
                        <Trash2 size={14} />
                    </button>

                    {/* Color picker */}
                    <div
                        className="sticky-note-color-picker"
                        onMouseEnter={() => setIsColorPickerExpanded(true)}
                        onMouseLeave={handleColorPickerMouseLeave}
                    >
                        {/* Rainbow circle (always rendered to maintain space) */}
                        <button
                            className="sticky-note-action-btn rainbow-btn"
                            onClick={(e) => e.stopPropagation()}
                            title="Change color"
                            style={{
                                opacity: isColorPickerExpanded ? 0 : 1,
                                transition: 'opacity 0.15s ease',
                            }}
                        >
                            <div className="rainbow-circle" />
                        </button>

                        {/* Expanded color options (absolutely positioned overlay) */}
                        {isColorPickerExpanded && (
                            <div
                                className={`color-picker-expanded ${isColorPickerClosing ? 'closing' : ''}`}
                            >
                                {Object.entries(stickyColors).map(
                                    ([colorKey, colorValue]) => (
                                        <button
                                            key={colorKey}
                                            className="color-option"
                                            style={{
                                                // Preview the note's theme color: the saturated accent
                                                // reads as the dark-note look, so in light show the
                                                // pastel border the light note actually uses.
                                                backgroundColor: isDark
                                                    ? colorValue.accent
                                                    : colorValue.light.border,
                                            }}
                                            onClick={(e) =>
                                                handleColorChange(
                                                    Number(colorKey),
                                                    e
                                                )
                                            }
                                            title={`Color ${colorKey}`}
                                        />
                                    )
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </>
    );
};

// Custom comparison function to prevent rerenders on position/dragging changes
// Only rerender if data content, color, or selected state changes
// Explicitly ignore: id, dragging, width, height, position, callbacks (onContentChange), and other props that don't affect visual output
const arePropsEqual = (prevProps: NodeProps, nextProps: NodeProps): boolean => {
    const prevData = prevProps.data as unknown as StickyNoteData;
    const nextData = nextProps.data as unknown as StickyNoteData;
    return (
        prevProps.selected === nextProps.selected &&
        prevData.content === nextData.content &&
        prevData.color === nextData.color
        // Deliberately ignore onContentChange callback - it's just a function reference
    );
};

export default memo(StickyNote, arePropsEqual);
