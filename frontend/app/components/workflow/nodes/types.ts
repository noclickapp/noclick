// Shared type definitions for workflow node metadata.
// All node files export a NodeDefinition object with this structure.
// Also provides factory functions to reduce boilerplate when creating automation nodes.

import { ComponentType, memo, createElement } from 'react';
import { NodeProps } from '@xyflow/react';
import { IconType } from 'react-icons';
import { LucideIcon } from 'lucide-react';
import AutomationNode from './base/AutomationNode';

export interface NodeDimensions {
    width: number;
    height: number;
    iconSize: number;
}

// JSON value types for workflow data
export type JsonPrimitive = string | number | boolean | null;
export type JsonArray = JsonValue[];
export type JsonObject = { [key: string]: JsonValue };
export type JsonValue = JsonPrimitive | JsonArray | JsonObject;

// Single autocomplete suggestion entry
export interface ReferenceSuggestion {
    // Full reference string without braces: "nodeId.path.to.field"
    reference: string;
    // Display label for the suggestion
    label: string;
    // Node ID this reference points to
    nodeId: string;
    // Path within the node's output
    path: string;
    // Type of the value at this path (for display hints)
    valueType: 'string' | 'number' | 'boolean' | 'object' | 'array' | 'null';
    // Actual value (for preview)
    value: JsonValue;
    // Depth in the object hierarchy (for sorting/grouping)
    depth: number;
}

// Props for custom panel content components
export interface OutputPanelContentProps {
    nodeId: string;
    output: JsonValue;
    draggable?: boolean;
    // For iteration nodes: which handle the connection comes from (loop vs done/output)
    // Used to auto-select the appropriate tab when showing as an input
    sourceHandle?: string;
    // Node configuration data — available even before execution so display strategies
    // can show fields/variables from the node's config (e.g., config form fields)
    nodeData?: Record<string, unknown>;
}

// Display strategy that nodes can define to customize how their output is displayed
// and how references to their output work in downstream nodes.
//
// The contract:
//   - buildSuggestions / validateReference are REQUIRED in the resolved strategy.
//     Node authors don't have to write them — the registry fills in defaults from
//     ./strategyDefaults when a node omits them. Consumers (e.g.
//     ReferenceAutocompleteContext) call them directly without optional-chaining.
//   - buildSuggestionsFromConfig is genuinely optional (only nodes whose config
//     exposes references provide it).
//   - OutputPanelContent is genuinely optional (UI override).
//
// Node authors should type their export as NodeDisplayStrategyOverrides (or rely
// on inference); the registry merges in defaults.
export interface NodeDisplayStrategy {
    buildSuggestions: (output: JsonValue, nodeId: string) => ReferenceSuggestion[];
    validateReference: (output: JsonValue, path: string) => { valid: boolean; error?: string };
    buildSuggestionsFromConfig?: (nodeData: Record<string, unknown>, nodeId: string) => ReferenceSuggestion[];
    OutputPanelContent?: ComponentType<OutputPanelContentProps>;
}

// What node authors write — overrides only. Anything omitted falls back to the
// defaults in ./strategyDefaults at registry-lookup time.
export type NodeDisplayStrategyOverrides = Partial<NodeDisplayStrategy>;

// Brand icons are implemented either as an image wrapper or an inline SVG.
// Keeping both DOM prop surfaces reflects what the registry actually accepts.
export type SvgIconComponent =
    | ComponentType<React.ImgHTMLAttributes<HTMLImageElement>>
    | ComponentType<React.SVGProps<SVGSVGElement>>;

export interface NodeDefinition {
    type: string;
    label: string;
    description: string;
    // Extra search aliases so a node surfaces in node search for terms that
    // aren't in its label/description (e.g. ["RAG", "vector search", "retrieval"]).
    keywords?: string[];
    Icon: IconType | LucideIcon | SvgIconComponent;
    iconColor: string;
    /** Optional background override for the node card (canvas + sidebar preview). Defaults to dark gradient. */
    bgGradient?: string;
    dimensions: NodeDimensions;
    // The raw component - will be auto-wrapped with memo() by the registry
    // Export raw components (no memo wrapper) for automatic optimization
    component: ComponentType<NodeProps>;
    // Optional display strategy overrides — anything omitted falls back to defaults
    // from ./strategyDefaults at registry-lookup time (see getDisplayStrategy).
    displayStrategy?: NodeDisplayStrategyOverrides;
    // Performance: Custom memo comparison function (defaults to nodePropsAreEqual)
    // Use this for nodes that need custom equality logic (e.g., AIAgentNode)
    memoCompare?: (prev: NodeProps, next: NodeProps) => boolean;
    // Performance: Set to true if component already handles its own memoization
    // When true, the registry will not wrap the component with memo()
    skipAutoMemo?: boolean;
}

/**
 * PERFORMANCE: Shared comparison function for node wrapper components.
 * Ignores position-related props (xPos, yPos, positionAbsoluteX, positionAbsoluteY, dragging)
 * which change on every frame during drag operations.
 * Use this with memo() to prevent unnecessary re-renders.
 */
export const nodePropsAreEqual = (prev: NodeProps, next: NodeProps): boolean => {
    return (
        prev.id === next.id &&
        prev.type === next.type &&
        prev.selected === next.selected &&
        prev.data === next.data &&
        prev.zIndex === next.zIndex &&
        prev.isConnectable === next.isConnectable &&
        prev.sourcePosition === next.sourcePosition &&
        prev.targetPosition === next.targetPosition
        // Intentionally ignoring: xPos, yPos, positionAbsoluteX, positionAbsoluteY, dragging
    );
};
