// Default reference-suggestion + reference-validation behavior for workflow nodes.
//
// These are the baseline implementations of NodeDisplayStrategy's required methods,
// applied by the registry's getDisplayStrategy() whenever a node doesn't override
// them. Lifting them out of any individual consumer means consumers can call
// `strategy.buildSuggestions(...)` / `strategy.validateReference(...)` without
// guards — every strategy returned by the registry has both methods.
//
// This module is intentionally pure (no React, no nodeRegistry import) so that
// nodeRegistry.ts and ReferenceAutocompleteContext.tsx can both import it
// without re-entering the lazy nodeRegistry TDZ chain.

import type { JsonValue, JsonObject, ReferenceSuggestion } from './types';

function getValueType(value: JsonValue): ReferenceSuggestion['valueType'] {
    if (value === null) return 'null';
    if (Array.isArray(value)) return 'array';
    if (typeof value === 'object') return 'object';
    if (typeof value === 'string') return 'string';
    if (typeof value === 'number') return 'number';
    if (typeof value === 'boolean') return 'boolean';
    return 'string';
}

// Recursively extract all paths from a data object as reference suggestions.
// Default buildSuggestions for any strategy that doesn't customize it.
export function extractPathsFromData(
    data: JsonValue,
    nodeId: string,
    basePath: string = '',
    depth: number = 0,
    maxDepth: number = 6
): ReferenceSuggestion[] {
    const suggestions: ReferenceSuggestion[] = [];
    if (depth > maxDepth) return suggestions;

    const valueType = getValueType(data);
    const fullReference = basePath ? `${nodeId}.${basePath}` : nodeId;

    let label = basePath || '(root)';
    if (valueType === 'object' && data !== null && typeof data === 'object' && !Array.isArray(data)) {
        label = `${label} {${Object.keys(data).length} keys}`;
    } else if (valueType === 'array' && Array.isArray(data)) {
        label = `${label} [${data.length} items]`;
    } else if (valueType === 'string') {
        const preview = String(data).slice(0, 30);
        label = `${label}: "${preview}${String(data).length > 30 ? '...' : ''}"`;
    } else if (valueType !== 'null') {
        label = `${label}: ${String(data)}`;
    } else {
        label = `${label}: null`;
    }

    suggestions.push({ reference: fullReference, label, nodeId, path: basePath, valueType, value: data, depth });

    if (data !== null && typeof data === 'object' && !Array.isArray(data)) {
        for (const [key, value] of Object.entries(data)) {
            const newPath = basePath ? `${basePath}.${key}` : key;
            suggestions.push(...extractPathsFromData(value, nodeId, newPath, depth + 1, maxDepth));
        }
    }

    if (Array.isArray(data)) {
        data.slice(0, 3).forEach((item, index) => {
            const newPath = basePath ? `${basePath}[${index}]` : `[${index}]`;
            suggestions.push(...extractPathsFromData(item, nodeId, newPath, depth + 1, maxDepth));
        });
    }

    return suggestions;
}

// Default path validation: walks the path against the output data and reports
// whether each segment resolves. Default validateReference for any strategy
// that doesn't customize it.
export function validatePathDefault(output: JsonValue, path: string): { valid: boolean; error?: string } {
    if (!path) return { valid: true };

    const pathParts = path.split(/\.|\[/).map(p => p.replace(/\]$/, ''));
    let current: JsonValue = output;

    for (const part of pathParts) {
        if (current === null || current === undefined) {
            return { valid: false, error: `Path "${path}" - "${part}" not found` };
        }

        if (/^\d+$/.test(part)) {
            const index = parseInt(part, 10);
            if (!Array.isArray(current) || index >= current.length) {
                return { valid: false, error: `Array index [${part}] out of bounds` };
            }
            current = current[index];
        } else {
            if (typeof current !== 'object' || current === null || Array.isArray(current)) {
                return { valid: false, error: `Property "${part}" not found - not an object` };
            }
            if (!(part in current)) {
                return { valid: false, error: `Property "${part}" not found` };
            }
            current = (current as JsonObject)[part];
        }
    }

    return { valid: true };
}
