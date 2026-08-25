// DraggableJsonField component renders JSON data with draggable leaf values.
// Used in Input/Output panels to allow users to drag field values into config fields.
// Creates references like {{nodeId.path.to.field}} when dropped.
// Supports highlight state when hovering over references in config fields.
// Auto-scrolls into view when a reference is clicked in config fields.

import { useState, useCallback, useEffect, useRef, type ReactNode } from 'react';
import { useDraggable } from '@dnd-kit/core';
import { ChevronRight, ChevronDown, GripVertical, Copy, Check, Type, Hash, ToggleLeft, CircleOff } from 'lucide-react';
import { useReferenceHover, isPathHighlighted, shouldScrollToPath, shouldExpandPath } from './ReferenceHoverContext';
import { AudioPlayer } from './AudioPlayer';

// Helper to detect and parse JSON strings
const tryParseJsonString = (value: string): { isJson: boolean; parsed: any } => {
    if (!value || typeof value !== 'string') return { isJson: false, parsed: null };
    const trimmed = value.trim();
    // Check if it looks like JSON (starts with { or [)
    if ((trimmed.startsWith('{') && trimmed.endsWith('}')) ||
        (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
        try {
            return { isJson: true, parsed: JSON.parse(trimmed) };
        } catch {
            return { isJson: false, parsed: null };
        }
    }
    return { isJson: false, parsed: null };
};

interface DraggableJsonFieldProps {
    data: any;
    nodeId: string;
    path?: string;
    label?: string;
    depth?: number;
    draggable?: boolean; // Whether leaf values can be dragged (default: true)
    isSchema?: boolean; // Schema mode: show type badges instead of literal type strings
    parentData?: any; // Parent object data (for accessing sibling fields like content_type)
}

// Schema type configuration - minimal styling with icons
const SCHEMA_TYPES: Record<string, {
    label: string;
    Icon: typeof Type;
    skeletonWidth: string;
}> = {
    string: { label: 'text', Icon: Type, skeletonWidth: 'w-12' },
    integer: { label: 'number', Icon: Hash, skeletonWidth: 'w-6' },
    float: { label: 'number', Icon: Hash, skeletonWidth: 'w-8' },
    boolean: { label: 'boolean', Icon: ToggleLeft, skeletonWidth: 'w-5' },
    null: { label: 'null', Icon: CircleOff, skeletonWidth: 'w-3' },
};

// Check if a value is a schema type string
const isSchemaType = (value: unknown): value is string => {
    return typeof value === 'string' && value in SCHEMA_TYPES;
};

// Drag data structure for JSON field references
export interface JsonFieldDragData {
    type: 'json-field-reference';
    nodeId: string;
    path: string;
    value: any;
    displayValue: string;
}

// Light: crisp charcoal ring (--primary) + near-white fill so it reads sharp, not
// as a muddy translucent-black smudge. Dark: keep the soft white glow.
const HIGHLIGHT_CLASSES = 'scale-105 bg-foreground/[0.05] dark:bg-foreground/20 shadow-[inset_0_0_0_2px_hsl(var(--primary))] dark:shadow-[inset_0_0_0_2px_hsl(var(--foreground)/0.6)]';

// Shared draggable expand/collapse header used by arrays, objects, and long strings.
// Renders a grip icon + chevron + children when draggable, or a plain button when not.
const DraggableExpandHeader = ({
    dragData,
    canDrag,
    isExpanded,
    onToggle,
    isHighlighted,
    shouldScrollTo,
    className: extraClass = '',
    children,
}: {
    dragData: JsonFieldDragData;
    canDrag: boolean;
    isExpanded: boolean;
    onToggle: () => void;
    isHighlighted: boolean;
    shouldScrollTo: boolean;
    className?: string;
    children: ReactNode;
}) => {
    const elementRef = useRef<HTMLElement>(null);
    const dragId = `json-expand-${dragData.nodeId}-${dragData.path}`;

    useEffect(() => {
        if (shouldScrollTo && elementRef.current) {
            elementRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, [shouldScrollTo]);

    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: dragId,
        data: dragData,
        disabled: !canDrag,
    });

    const combinedRef = useCallback((node: HTMLElement | null) => {
        setNodeRef(node);
        (elementRef as React.MutableRefObject<HTMLElement | null>).current = node;
    }, [setNodeRef]);

    const handleClick = useCallback((e: React.MouseEvent) => {
        e.stopPropagation();
        onToggle();
    }, [onToggle]);

    const highlightClasses = isHighlighted ? HIGHLIGHT_CLASSES : '';
    const chevron = isExpanded
        ? <ChevronDown className="h-3 w-3 text-muted-foreground flex-shrink-0" />
        : <ChevronRight className="h-3 w-3 text-muted-foreground flex-shrink-0" />;

    if (canDrag) {
        return (
            <span
                ref={combinedRef}
                {...attributes}
                {...listeners}
                onClick={handleClick}
                style={{ opacity: isDragging ? 0.5 : 1, cursor: isDragging ? 'grabbing' : 'grab' }}
                className={`inline-flex items-center gap-1 min-w-0 max-w-full px-1.5 py-0.5 rounded bg-foreground/[0.06] dark:bg-foreground/[0.03] hover:bg-foreground/[0.1] dark:hover:bg-foreground/[0.08] border border-transparent hover:border-border dark:hover:border-white/[0.1] transition-all group ${highlightClasses} ${extraClass}`}
            >
                <GripVertical className="h-3 w-3 text-muted-foreground/70 dark:text-zinc-600 group-hover:text-muted-foreground dark:group-hover:text-zinc-400 transition-colors flex-shrink-0" />
                {chevron}
                {children}
            </span>
        );
    }

    return (
        <button
            ref={elementRef as React.RefObject<HTMLButtonElement>}
            onClick={onToggle}
            className={`flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors min-w-0 ${highlightClasses} ${extraClass}`}
        >
            {chevron}
            {children}
        </button>
    );
};

// Draggable schema placeholder - matches DraggableValue styling exactly
const DraggableSchemaPlaceholder = ({
    type,
    nodeId,
    path,
    label,
    canDrag = true,
    isHighlighted = false,
    shouldScrollTo = false,
}: {
    type: string;
    nodeId: string;
    path: string;
    label?: string;
    canDrag?: boolean;
    isHighlighted?: boolean;
    shouldScrollTo?: boolean;
}) => {
    const config = SCHEMA_TYPES[type];
    if (!config) return null;

    const { Icon, skeletonWidth, label: typeLabel } = config;
    const dragId = `schema-field-${nodeId}-${path}`;
    const elementRef = useRef<HTMLSpanElement>(null);

    useEffect(() => {
        if (shouldScrollTo && elementRef.current) {
            elementRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, [shouldScrollTo]);

    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: dragId,
        data: {
            type: 'json-field-reference',
            nodeId,
            path,
            value: null,
            displayValue: `<${typeLabel}>`,
        } as JsonFieldDragData,
        disabled: !canDrag,
    });

    const combinedRef = useCallback((node: HTMLSpanElement | null) => {
        setNodeRef(node);
        (elementRef as React.MutableRefObject<HTMLSpanElement | null>).current = node;
    }, [setNodeRef]);

    const highlightClasses = isHighlighted ? HIGHLIGHT_CLASSES : '';

    // Non-draggable version
    if (!canDrag) {
        return (
            <div className="flex items-center gap-2 min-w-0 overflow-hidden">
                {label && (
                    <span className="text-muted-foreground dark:text-zinc-500 text-xs font-medium flex-shrink-0">{label}:</span>
                )}
                <span
                    ref={elementRef}
                    className={`inline-flex items-center gap-1.5 min-w-0 max-w-full px-1.5 py-0.5 rounded bg-foreground/[0.06] dark:bg-foreground/[0.03] transition-all ${highlightClasses}`}
                >
                    <Icon className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 flex-shrink-0" />
                    <span className={`${skeletonWidth} h-3 rounded bg-muted-foreground/40 dark:bg-zinc-600/80`} />
                </span>
            </div>
        );
    }

    // Draggable version
    return (
        <div className="flex items-center gap-2 min-w-0 overflow-hidden">
            {label && (
                <span className="text-muted-foreground dark:text-zinc-500 text-xs font-medium flex-shrink-0">{label}:</span>
            )}
            <span
                ref={combinedRef}
                style={{ opacity: isDragging ? 0.5 : 1, cursor: isDragging ? 'grabbing' : 'grab' }}
                {...attributes}
                {...listeners}
                className={`inline-flex items-center gap-1 min-w-0 max-w-full px-1.5 py-0.5 rounded bg-foreground/[0.06] dark:bg-foreground/[0.03] hover:bg-foreground/[0.1] dark:hover:bg-foreground/[0.08] border border-transparent hover:border-border dark:hover:border-white/[0.1] transition-all group ${highlightClasses}`}
            >
                <GripVertical className="h-3 w-3 text-muted-foreground/70 dark:text-zinc-600 group-hover:text-muted-foreground dark:group-hover:text-zinc-400 transition-colors flex-shrink-0" />
                <Icon className="h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 flex-shrink-0" />
                <span className={`${skeletonWidth} h-3 rounded bg-muted-foreground/40 dark:bg-zinc-600/80`} />
            </span>
        </div>
    );
};

// Individual leaf value - optionally draggable
const DraggableValue = ({
    nodeId,
    path,
    value,
    displayValue,
    canDrag = true,
    isHighlighted = false,
    shouldScrollTo = false,
    customColorClass
}: {
    nodeId: string;
    path: string;
    value: any;
    displayValue: string;
    canDrag?: boolean;
    isHighlighted?: boolean;
    shouldScrollTo?: boolean;
    customColorClass?: string;
}) => {
    const dragId = `json-field-${nodeId}-${path}`;
    const elementRef = useRef<HTMLSpanElement>(null);

    useEffect(() => {
        if (shouldScrollTo && elementRef.current) {
            elementRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, [shouldScrollTo]);

    const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
        id: dragId,
        data: {
            type: 'json-field-reference',
            nodeId,
            path,
            value,
            displayValue,
        } as JsonFieldDragData,
        disabled: !canDrag,
    });

    const getValueClass = () => {
        if (customColorClass) return customColorClass;
        if (value === null) return 'text-muted-foreground dark:text-zinc-500 italic';
        if (typeof value === 'string') return 'text-emerald-600 dark:text-emerald-400';
        if (typeof value === 'number') return 'text-blue-600 dark:text-blue-400';
        if (typeof value === 'boolean') return 'text-amber-600 dark:text-amber-400';
        return 'text-foreground/80';
    };

    const highlightClasses = isHighlighted ? HIGHLIGHT_CLASSES : '';

    const combinedRef = useCallback((node: HTMLSpanElement | null) => {
        setNodeRef(node);
        (elementRef as React.MutableRefObject<HTMLSpanElement | null>).current = node;
    }, [setNodeRef]);

    // Non-draggable: simple styled span
    if (!canDrag) {
        return (
            <span
                ref={elementRef}
                className={`inline-flex items-center min-w-0 max-w-full px-1.5 py-0.5 rounded bg-foreground/[0.06] dark:bg-foreground/[0.03] transition-all ${highlightClasses} ${getValueClass()}`}
            >
                <span className="font-mono text-xs truncate" title={displayValue}>
                    {displayValue}
                </span>
            </span>
        );
    }

    return (
        <span
            ref={combinedRef}
            style={{ opacity: isDragging ? 0.5 : 1, cursor: isDragging ? 'grabbing' : 'grab' }}
            {...attributes}
            {...listeners}
            className={`inline-flex items-center gap-1 min-w-0 max-w-full px-1.5 py-0.5 rounded bg-foreground/[0.06] dark:bg-foreground/[0.03] hover:bg-foreground/[0.1] dark:hover:bg-foreground/[0.08] border border-transparent hover:border-border dark:hover:border-white/[0.1] transition-all group ${highlightClasses} ${getValueClass()}`}
        >
            <GripVertical className="h-3 w-3 text-muted-foreground/70 dark:text-zinc-600 group-hover:text-muted-foreground dark:group-hover:text-zinc-400 transition-colors flex-shrink-0" />
            <span className="font-mono text-xs truncate" title={displayValue}>
                {displayValue}
            </span>
        </span>
    );
};

// Expandable string value - for long strings with copy functionality
const ExpandableStringValue = ({
    nodeId,
    path,
    value,
    label,
    canDrag = true,
    isHighlighted = false,
    shouldScrollTo = false
}: {
    nodeId: string;
    path: string;
    value: string;
    label?: string;
    canDrag?: boolean;
    isHighlighted?: boolean;
    shouldScrollTo?: boolean;
}) => {
    const [isExpanded, setIsExpanded] = useState(false);
    const [copied, setCopied] = useState(false);

    const handleCopy = useCallback(async (e: React.MouseEvent) => {
        e.stopPropagation();
        try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch (err) {
            console.error('Failed to copy:', err);
        }
    }, [value]);

    const toggleExpand = useCallback(() => {
        setIsExpanded(prev => !prev);
    }, []);

    const previewText = value.length > 50 ? `${value.slice(0, 50)}...` : value;

    const dragData: JsonFieldDragData = {
        type: 'json-field-reference',
        nodeId,
        path,
        value,
        displayValue: `"${previewText}"`,
    };

    return (
        <div className="space-y-1 min-w-0 overflow-hidden">
            <div className="flex items-center gap-2 min-w-0">
                {label && (
                    <span className="text-muted-foreground dark:text-zinc-500 text-xs font-medium flex-shrink-0">{label}:</span>
                )}
                <DraggableExpandHeader
                    dragData={dragData}
                    canDrag={canDrag}
                    isExpanded={isExpanded}
                    onToggle={toggleExpand}
                    isHighlighted={isHighlighted}
                    shouldScrollTo={shouldScrollTo}
                    className="text-emerald-600 dark:text-emerald-400"
                >
                    <span className="font-mono text-xs truncate">
                        "{previewText}"
                    </span>
                    <span className="text-[10px] text-muted-foreground dark:text-zinc-500 flex-shrink-0">
                        ({value.length} chars)
                    </span>
                </DraggableExpandHeader>
                <button
                    onClick={handleCopy}
                    className="p-1 rounded hover:bg-foreground/[0.08] transition-colors flex-shrink-0"
                    title="Copy to clipboard"
                >
                    {copied ? (
                        <Check className="h-3 w-3 text-green-600 dark:text-green-400" />
                    ) : (
                        <Copy className="h-3 w-3 text-muted-foreground dark:text-zinc-500 hover:text-foreground" />
                    )}
                </button>
            </div>

            {isExpanded && (
                <div className="ml-4 pl-2 border-l border-border/50 dark:border-zinc-800/50">
                    <pre className="text-xs text-emerald-600 dark:text-emerald-400 font-mono whitespace-pre-wrap break-all bg-muted dark:bg-black/20 p-2 rounded max-h-[300px] overflow-auto">
                        {value}
                    </pre>
                </div>
            )}
        </div>
    );
};

// Recursive JSON renderer with collapsible objects/arrays
export const DraggableJsonField = ({
    data,
    nodeId,
    path = '',
    label,
    depth = 0,
    draggable = true,
    isSchema = false,
    parentData
}: DraggableJsonFieldProps) => {
    const [isExpanded, setIsExpanded] = useState(depth < 2); // Auto-expand first 2 levels

    // Reference hover context - may not be available if not wrapped in provider
    let hoveredReference: { nodeId: string; path: string } | null = null;
    let scrollToReference: { nodeId: string; path: string } | null = null;
    let pathsToExpand: Set<string> = new Set();
    try {
        const context = useReferenceHover();
        if (context) {
            hoveredReference = context.hoveredReference;
            scrollToReference = context.scrollToReference;
            pathsToExpand = context.pathsToExpand;
        }
    } catch {
        // Context not available, highlighting/scrolling disabled
    }

    const isHighlighted = isPathHighlighted(hoveredReference, nodeId, path) ||
                          isPathHighlighted(scrollToReference, nodeId, path);
    const shouldScrollTo = shouldScrollToPath(scrollToReference, nodeId, path);
    const shouldExpand = shouldExpandPath(pathsToExpand, nodeId, path);

    useEffect(() => {
        if (shouldExpand && !isExpanded) {
            setIsExpanded(true);
        }
    }, [shouldExpand, isExpanded]);

    const toggleExpand = useCallback(() => {
        setIsExpanded(prev => !prev);
    }, []);

    // Handle null/undefined
    if (data === null || data === undefined) {
        return (
            <div className="flex items-center gap-2 min-w-0 overflow-hidden">
                {label && (
                    <span className="text-muted-foreground dark:text-zinc-500 text-xs font-medium flex-shrink-0">{label}:</span>
                )}
                <DraggableValue
                    nodeId={nodeId}
                    path={path || 'value'}
                    value={null}
                    displayValue="null"
                    canDrag={draggable}
                    isHighlighted={isHighlighted}
                    shouldScrollTo={shouldScrollTo}
                />
            </div>
        );
    }

    // Handle primitives (leaf values - optionally draggable)
    if (typeof data !== 'object') {
        // Check if string contains JSON - if so, parse and render as nested structure
        if (typeof data === 'string') {
            const { isJson, parsed } = tryParseJsonString(data);
            if (isJson && parsed !== null) {
                return (
                    <DraggableJsonField
                        data={parsed}
                        nodeId={nodeId}
                        path={path}
                        label={label}
                        depth={depth}
                        draggable={draggable}
                        isSchema={isSchema}
                    />
                );
            }
        }

        // Schema mode: render type placeholders instead of literal type strings
        if (isSchema && isSchemaType(data)) {
            return (
                <DraggableSchemaPlaceholder
                    type={data}
                    nodeId={nodeId}
                    path={path || 'value'}
                    label={label}
                    canDrag={draggable}
                    isHighlighted={isHighlighted}
                    shouldScrollTo={shouldScrollTo}
                />
            );
        }

        const displayValue = typeof data === 'string'
            ? `"${data}"`
            : String(data);

        // Special handling for audio_base64 fields - show inline audio player
        if (typeof data === 'string' && label === 'audio_base64' && data.length > 100) {
            // Try to get content_type from parent object (e.g., sibling field)
            const contentType = parentData?.content_type || 'audio/mpeg';

            return (
                <div className="space-y-2 min-w-0 overflow-hidden">
                    <div className="flex items-center gap-2 min-w-0 overflow-hidden">
                        <span className="text-muted-foreground dark:text-zinc-500 text-xs font-medium flex-shrink-0">{label}:</span>
                        <AudioPlayer audioBase64={data} contentType={contentType} />
                    </div>
                    {/* Also show the expandable base64 string for reference/dragging */}
                    <ExpandableStringValue
                        nodeId={nodeId}
                        path={path || 'value'}
                        value={data}
                        label="Raw data"
                        canDrag={draggable}
                        isHighlighted={isHighlighted}
                        shouldScrollTo={shouldScrollTo}
                    />
                </div>
            );
        }

        // For long strings, use a special expandable display
        if (typeof data === 'string' && data.length > 100) {
            return (
                <ExpandableStringValue
                    nodeId={nodeId}
                    path={path || 'value'}
                    value={data}
                    label={label}
                    canDrag={draggable}
                    isHighlighted={isHighlighted}
                    shouldScrollTo={shouldScrollTo}
                />
            );
        }

        return (
            <div className="flex items-center gap-2 min-w-0 overflow-hidden">
                {label && (
                    <span className="text-muted-foreground dark:text-zinc-500 text-xs font-medium flex-shrink-0">{label}:</span>
                )}
                <DraggableValue
                    nodeId={nodeId}
                    path={path || 'value'}
                    value={data}
                    displayValue={displayValue}
                    canDrag={draggable}
                    isHighlighted={isHighlighted}
                    shouldScrollTo={shouldScrollTo}
                />
            </div>
        );
    }

    // Handle arrays
    if (Array.isArray(data)) {
        if (data.length === 0) {
            return (
                <div className="flex items-center gap-2 min-w-0 overflow-hidden">
                    {label && (
                        <span className="text-muted-foreground dark:text-zinc-500 text-xs font-medium flex-shrink-0">{label}:</span>
                    )}
                    <span className="text-muted-foreground dark:text-zinc-500 text-xs italic">[ ]</span>
                </div>
            );
        }

        const arrayDragData: JsonFieldDragData = {
            type: 'json-field-reference',
            nodeId,
            path: path || 'value',
            value: data,
            displayValue: `[${data.length} item${data.length !== 1 ? 's' : ''}]`,
        };

        return (
            <div className="space-y-1 min-w-0 overflow-hidden">
                <DraggableExpandHeader
                    dragData={arrayDragData}
                    canDrag={draggable}
                    isExpanded={isExpanded}
                    onToggle={toggleExpand}
                    isHighlighted={isHighlighted}
                    shouldScrollTo={shouldScrollTo}
                >
                    {label && (
                        <span className="text-xs font-medium text-muted-foreground truncate">{label}</span>
                    )}
                    <span className="text-[10px] text-muted-foreground dark:text-zinc-500 flex-shrink-0">
                        [{data.length}]
                    </span>
                </DraggableExpandHeader>

                {isExpanded && (
                    <div className="ml-4 pl-2 border-l border-border/50 dark:border-zinc-800/50 space-y-1 min-w-0 overflow-hidden">
                        {data.map((item, index) => (
                            <DraggableJsonField
                                key={index}
                                data={item}
                                nodeId={nodeId}
                                path={path ? `${path}[${index}]` : `[${index}]`}
                                label={`[${index}]`}
                                depth={depth + 1}
                                draggable={draggable}
                                isSchema={isSchema}
                            />
                        ))}
                    </div>
                )}
            </div>
        );
    }

    // Handle objects
    const entries = Object.entries(data);
    if (entries.length === 0) {
        return (
            <div className="flex items-center gap-2 min-w-0 overflow-hidden">
                {label && (
                    <span className="text-muted-foreground dark:text-zinc-500 text-xs font-medium flex-shrink-0">{label}:</span>
                )}
                <span className="text-muted-foreground dark:text-zinc-500 text-xs italic">{ }</span>
            </div>
        );
    }

    const objectDragData: JsonFieldDragData = {
        type: 'json-field-reference',
        nodeId,
        path: path || 'value',
        value: data,
        displayValue: `{${entries.length} key${entries.length !== 1 ? 's' : ''}}`,
    };

    return (
        <div className="space-y-1 min-w-0 overflow-hidden">
            {label && (
                <DraggableExpandHeader
                    dragData={objectDragData}
                    canDrag={draggable}
                    isExpanded={isExpanded}
                    onToggle={toggleExpand}
                    isHighlighted={isHighlighted}
                    shouldScrollTo={shouldScrollTo}
                >
                    <span className="text-xs font-medium text-muted-foreground truncate">{label}</span>
                    <span className="text-[10px] text-muted-foreground dark:text-zinc-500 flex-shrink-0">
                        {`{${entries.length}}`}
                    </span>
                </DraggableExpandHeader>
            )}

            {(isExpanded || !label) && (
                <div className={label ? "ml-4 pl-2 border-l border-border/50 dark:border-zinc-800/50 space-y-1 min-w-0 overflow-hidden" : "space-y-1 min-w-0 overflow-hidden"}>
                    {entries.map(([key, value]) => (
                        <DraggableJsonField
                            key={key}
                            data={value}
                            nodeId={nodeId}
                            path={path ? `${path}.${key}` : key}
                            label={key}
                            depth={depth + 1}
                            draggable={draggable}
                            isSchema={isSchema}
                            parentData={data}
                        />
                    ))}
                </div>
            )}
        </div>
    );
};
