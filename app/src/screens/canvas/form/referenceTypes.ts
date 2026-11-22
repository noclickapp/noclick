// What a step's output offers a later step's fields: the JSON a step outputs, the references a field can take into it
// (`{{ $('step').path }}`), and how a step type says where they are (its display strategy). Integrations' own
// definitions name their strategies; the form reads them through `canvas.step.marks`.
import type { ComponentType } from 'react';

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
