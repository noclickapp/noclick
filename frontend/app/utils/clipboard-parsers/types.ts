/**
 * Common types and interfaces for clipboard parsers.
 * Provides a unified interface for parsing different clipboard formats
 * (NoClick JSON, n8n JSON, Google Sheets URLs, etc.) into workflow nodes/edges.
 */

import { Node, Edge } from 'reactflow';

/**
 * Result of a successful clipboard parse operation.
 * Contains nodes and edges ready to be added to the canvas.
 */
export interface ClipboardParseResult {
    nodes: Node[];
    edges: Edge[];
}

/**
 * Interface that all clipboard parsers must implement.
 * Parsers are tried in order of priority (highest first) until one succeeds.
 */
export interface ClipboardParser {
    /** Human-readable name for logging/debugging */
    name: string;

    /** Higher priority parsers are tried first. Use 100 for primary formats, 50 for secondary, etc. */
    priority: number;

    /**
     * Attempt to parse clipboard text into nodes/edges.
     * @param text - Raw clipboard text
     * @returns ParseResult if successful, null if this parser doesn't handle this format
     */
    parse(text: string): ClipboardParseResult | null;
}
