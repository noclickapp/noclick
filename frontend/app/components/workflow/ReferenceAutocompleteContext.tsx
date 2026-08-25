// ReferenceAutocompleteContext provides input node data to DroppableTextField components.
// This enables autocomplete suggestions when users type {{}} references and validation
// of reference paths against actual available data from connected input nodes.
// Uses node-defined strategies from nodeRegistry for custom behavior, with default fallback.

import { createContext, useContext, useMemo, ReactNode } from 'react';
import type { Node } from '@xyflow/react';
import type { ReferenceSuggestion, JsonValue } from './nodes/nodeRegistry';
import type { NodeDisplayStrategy } from './nodes/types';
import { extractPathsFromData, validatePathDefault } from './nodes/strategyDefaults';
import { scanBlocks, isJsExpression, parsePureAccessor, normalizeAccessorRef } from './expressionSyntax';
import { isJsonValue } from '~/utils/jsonValue';

// Avoid a static import of the heavy nodeRegistry — it transitively re-enters this file
// (FieldRenderer → SchedulesWidget → DroppableTextField → here → registry) and triggers
// a TDZ on every lazy load of any node component file. Resolve dynamically: while the
// registry chunk is loading, fall back to the baseline default strategy so consumers
// can keep calling required methods (buildSuggestions / validateReference) without
// guarding. Once the registry resolves, subsequent calls go through the real lookup.
let _getDisplayStrategyImpl: ((type: string | undefined) => NodeDisplayStrategy) | null = null;
let _registryLoading: Promise<void> | null = null;
function ensureRegistryLoaded(): Promise<void> {
    if (_getDisplayStrategyImpl) return Promise.resolve();
    if (_registryLoading) return _registryLoading;
    _registryLoading = import('./nodes/nodeRegistry').then((m) => {
        _getDisplayStrategyImpl = m.getDisplayStrategy;
    });
    return _registryLoading;
}
function getDisplayStrategy(type: string | undefined): NodeDisplayStrategy {
    if (!_getDisplayStrategyImpl) {
        void ensureRegistryLoaded();
        // Registry chunk not loaded yet — return the baseline so callers can still
        // produce default suggestions/validation until the real strategy is available.
        return {
            buildSuggestions: extractPathsFromData,
            validateReference: validatePathDefault,
        };
    }
    return _getDisplayStrategyImpl(type);
}

// Re-export for backward compatibility
export type { ReferenceSuggestion } from './nodes/nodeRegistry';

interface ReferenceAutocompleteContextValue {
    // All available suggestions built from input nodes
    suggestions: ReferenceSuggestion[];
    // Input nodes data for validation
    inputNodes: Node[];
    // Validate if a reference path is valid
    validateReference: (reference: string) => { valid: boolean; error?: string };
    // Get suggestions matching a partial input (e.g., "node1.out" -> matches "node1.output.data")
    getSuggestions: (partial: string) => ReferenceSuggestion[];
    // Workflow-level variables ({{vars.key}}) — used by the expression editor to
    // supply $vars to the live preview.
    workflowVariables?: Record<string, JsonValue>;
    // nodeId -> a clipped sample of the node's output (from past runs / observed
    // schema). The live preview evaluates against this when a node hasn't produced
    // real output yet, so `$('node').field` resolves instead of erroring "no data".
    expectedSchemas?: Map<string, JsonValue>;
}

const ReferenceAutocompleteContext = createContext<ReferenceAutocompleteContextValue | null>(null);

// ============================================================================
// Build suggestions using node strategies
// ============================================================================

function buildSuggestions(
    inputNodes: Node[],
    expectedSchemas?: Map<string, JsonValue>,
    workflowVariables?: Record<string, JsonValue>
): ReferenceSuggestion[] {
    const suggestions: ReferenceSuggestion[] = [];

    for (const node of inputNodes) {
        const mockedOutput = node.data?.mockedOutput as JsonValue | undefined;
        const liveOutput = node.data?.output as JsonValue | undefined;
        const output = mockedOutput !== undefined ? mockedOutput : liveOutput;

        // Use actual output if available, otherwise use expected schema
        const dataToExtract = output !== undefined ? output : expectedSchemas?.get(node.id);
        const strategy = getDisplayStrategy(node.type);

        if (dataToExtract !== undefined) {
            suggestions.push(...strategy.buildSuggestions(dataToExtract, node.id));
        } else if (strategy.buildSuggestionsFromConfig) {
            // No output or expected schema — fall back to config-derived suggestions if the
            // node provides them (most nodes don't; only those whose config exposes references).
            const nodeData = (node.data || {}) as Record<string, unknown>;
            suggestions.push(...strategy.buildSuggestionsFromConfig(nodeData, node.id));
        }
    }

    // Add workflow variables as synthetic "vars" entries for {{vars.key}} references
    if (workflowVariables && Object.keys(workflowVariables).length > 0) {
        suggestions.push(...extractPathsFromData(workflowVariables as JsonValue, 'vars'));
    }

    // Sort by depth first (shallow first), then alphabetically
    suggestions.sort((a, b) => {
        if (a.depth !== b.depth) return a.depth - b.depth;
        return a.reference.localeCompare(b.reference);
    });

    return suggestions;
}

// ============================================================================
// Validate references using node strategies
// ============================================================================

export function createValidator(inputNodes: Node[], expectedSchemas?: Map<string, JsonValue>, workflowVariables?: Record<string, JsonValue>) {
    return (rawReference: string): { valid: boolean; error?: string } => {
        const accessor = parsePureAccessor(rawReference);
        const reference = normalizeAccessorRef(rawReference);
        const dotIndex = reference.indexOf('.');

        // A `$('id').path` / `$vars.path` accessor is JavaScript: its property chain
        // (`.length`, `.toUpperCase()`, ...) is evaluated server-side, and a JS property
        // is indistinguishable from a data key here — so only validate that the data
        // SOURCE exists. The live preview is the real signal for a wrong path. (Legacy
        // `{{node.field}}` refs are pure data navigation and still get full path checks.)
        if (accessor) {
            const head = dotIndex === -1 ? reference : reference.slice(0, dotIndex);
            if (head === 'vars') {
                return workflowVariables && Object.keys(workflowVariables).length > 0
                    ? { valid: true }
                    : { valid: false, error: 'No workflow variables defined' };
            }
            return inputNodes.find(n => n.id === head)
                ? { valid: true }
                : { valid: false, error: `Node "${head}" not found in inputs` };
        }

        if (dotIndex === -1) {
            // Just a node ID or "vars" - check if it exists
            if (reference === 'vars') {
                return workflowVariables && Object.keys(workflowVariables).length > 0
                    ? { valid: true }
                    : { valid: false, error: 'No workflow variables defined' };
            }
            const node = inputNodes.find(n => n.id === reference);
            if (!node) {
                return { valid: false, error: `Node "${reference}" not found in inputs` };
            }
            // Node exists - reference is valid
            return { valid: true };
        }

        const nodeId = reference.slice(0, dotIndex);
        const path = reference.slice(dotIndex + 1);

        // Handle {{vars.key}} references
        if (nodeId === 'vars') {
            if (!workflowVariables) {
                return { valid: false, error: 'No workflow variables defined' };
            }
            return validatePathDefault(workflowVariables as JsonValue, path);
        }

        const node = inputNodes.find(n => n.id === nodeId);
        if (!node) {
            return { valid: false, error: `Node "${nodeId}" not found in inputs` };
        }

        // Use actual output if available, otherwise use expected schema
        const output = node.data?.mockedOutput ?? node.data?.output;
        const dataToValidate = output !== undefined ? output : expectedSchemas?.get(nodeId);

        if (dataToValidate === undefined) {
            // No output and no expected schema - can't validate, assume valid
            return { valid: true };
        }

        return isJsonValue(dataToValidate)
            ? getDisplayStrategy(node.type).validateReference(dataToValidate, path)
            : { valid: true };
    };
}

// ============================================================================
// Filter suggestions
// ============================================================================

function createSuggestionGetter(suggestions: ReferenceSuggestion[]) {
    return (partial: string): ReferenceSuggestion[] => {
        if (!partial) {
            return suggestions.filter(s => s.depth <= 1);
        }

        const lowerPartial = partial.toLowerCase();
        const matching = suggestions.filter(s =>
            s.reference.toLowerCase().includes(lowerPartial) ||
            s.label.toLowerCase().includes(lowerPartial)
        );

        matching.sort((a, b) => {
            const aStarts = a.reference.toLowerCase().startsWith(lowerPartial);
            const bStarts = b.reference.toLowerCase().startsWith(lowerPartial);
            if (aStarts && !bStarts) return -1;
            if (bStarts && !aStarts) return 1;
            return a.reference.localeCompare(b.reference);
        });

        return matching.slice(0, 20);
    };
}

// ============================================================================
// Provider and Hooks
// ============================================================================

interface ReferenceAutocompleteProviderProps {
    children: ReactNode;
    inputNodes: Node[];
    expectedSchemas?: Map<string, JsonValue>; // Map of nodeId -> expected output schema
    workflowVariables?: Record<string, JsonValue>; // Workflow-level variables for {{vars.key}} references
}

export function ReferenceAutocompleteProvider({ children, inputNodes, expectedSchemas, workflowVariables }: ReferenceAutocompleteProviderProps) {
    const suggestions = useMemo(() => buildSuggestions(inputNodes, expectedSchemas, workflowVariables), [inputNodes, expectedSchemas, workflowVariables]);
    const validateReference = useMemo(() => createValidator(inputNodes, expectedSchemas, workflowVariables), [inputNodes, expectedSchemas, workflowVariables]);
    const getSuggestions = useMemo(() => createSuggestionGetter(suggestions), [suggestions]);

    const contextValue = useMemo(() => ({
        suggestions,
        inputNodes,
        validateReference,
        getSuggestions,
        workflowVariables,
        expectedSchemas,
    }), [suggestions, inputNodes, validateReference, getSuggestions, workflowVariables, expectedSchemas]);

    return (
        <ReferenceAutocompleteContext.Provider value={contextValue}>
            {children}
        </ReferenceAutocompleteContext.Provider>
    );
}

export function useReferenceAutocomplete() {
    const context = useContext(ReferenceAutocompleteContext);
    if (!context) {
        return null;
    }
    return context;
}

// Parse a reference from text (e.g., "{{node1.output.data}}" -> "node1.output.data")
export function parseReferenceContent(refString: string): string | null {
    const match = refString.match(/^\{\{(.+)\}\}$/);
    return match ? match[1] : null;
}

// Extract all references from text
export function extractAllReferences(text: string): string[] {
    // Validate legacy refs and pure `$()`/`$vars` accessors (transform-free references).
    // Skip real expressions (with a transform) — those are evaluated server-side and
    // can't be validated as a static path.
    return scanBlocks(text)
        .map((b) => b.inner)
        .filter((inner) => !isJsExpression(inner) || parsePureAccessor(inner) !== null);
}
