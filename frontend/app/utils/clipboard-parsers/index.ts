/**
 * Clipboard parser registry.
 * Provides a unified entry point for parsing various clipboard formats into workflow nodes/edges.
 * Parsers are tried in priority order (highest first) until one succeeds.
 *
 * To add a new clipboard format:
 * 1. Create a new parser file implementing ClipboardParser interface
 * 2. Import and add it to CLIPBOARD_PARSERS array below
 */

import { ClipboardParser, ClipboardParseResult } from './types';
import { noClickParser } from './noclick-parser';
import { n8nParser } from './n8n-parser';
import { googleSheetsUrlParser } from './google-sheets-url-parser';

// Re-export types for convenience
export type { ClipboardParser, ClipboardParseResult } from './types';

/**
 * All registered clipboard parsers.
 * Add new parsers here - they will be automatically sorted by priority.
 */
const CLIPBOARD_PARSERS: ClipboardParser[] = [
    noClickParser,
    googleSheetsUrlParser,
    n8nParser,
];

// Sort parsers by priority (highest first)
const sortedParsers = [...CLIPBOARD_PARSERS].sort((a, b) => b.priority - a.priority);

/**
 * Attempts to parse clipboard text using all registered parsers.
 * Parsers are tried in priority order; first successful parse wins.
 *
 * @param text - Raw clipboard text
 * @returns ParseResult with nodes/edges if a parser succeeded, null otherwise
 */
export function parseClipboardContent(text: string): ClipboardParseResult | null {
    if (!text || !text.trim()) {
        return null;
    }

    for (const parser of sortedParsers) {
        const result = parser.parse(text);
        if (result) {
            console.log(`Clipboard parsed by: ${parser.name}`);
            return result;
        }
    }

    return null;
}

/**
 * Gets the list of registered parser names (for debugging/logging).
 */
export function getRegisteredParserNames(): string[] {
    return sortedParsers.map((p) => p.name);
}
