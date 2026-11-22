// A step type's drawing on the canvas: every node definition (a host's, or the canvas's own) is a NodeDefinition, which
// lazyNodeTypes.tsx wraps (nodeTypeComponent.ts) and hands React Flow.

import type { ComponentType } from 'react';
import type { NodeProps } from '@xyflow/react';
import type { IconType } from 'react-icons';
import type { LucideIcon } from 'lucide-react';
import type { NodeDisplayStrategyOverrides } from '@/screens/canvas/form/referenceTypes';

export interface NodeDimensions {
    width: number;
    height: number;
    iconSize: number;
}

// What a step's output offers a later step's fields (JSON values, reference suggestions, display strategies) is the open
// step form's (`@/screens/canvas/form/referenceTypes`).
export type {
    JsonArray,
    JsonObject,
    JsonPrimitive,
    JsonValue,
    NodeDisplayStrategy,
    NodeDisplayStrategyOverrides,
    OutputPanelContentProps,
    ReferenceSuggestion,
} from '@/screens/canvas/form/referenceTypes';

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
    /** The section an integration lists under on a deployment's integrations page (e.g. 'crm-sales'). A plain string, so
     *  this type names no deployment's list. */
    category?: string;
    Icon: IconType | LucideIcon | SvgIconComponent;
    iconColor: string;
    /** Optional background override for the node card (canvas + sidebar preview). Defaults to dark gradient. */
    bgGradient?: string;
    dimensions: NodeDimensions;
    // The raw component - will be auto-wrapped with memo() by the registry
    // Export raw components (no memo wrapper) for automatic optimization
    component: ComponentType<NodeProps>;
    // Optional display strategy overrides — anything omitted falls back to the defaults
    // in form/strategyDefaults when the strategy is looked up.
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
