/**
 * Parser for Google Sheets URLs.
 * Extracts spreadsheet ID from URLs like:
 * https://docs.google.com/spreadsheets/d/1DuAfjHb8IloS-MihaL1J5H-XFXdfOBJNKrZ86_09ew8/edit
 * and creates a Google Sheets automation node with the spreadsheet_id pre-populated.
 */

import { Node } from '@xyflow/react';
import { ClipboardParser, ClipboardParseResult } from './types';
import { generateNodeId } from '~/utils/nodeIdGenerator';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';

/** Regex to match Google Sheets URLs and extract the spreadsheet ID */
const GOOGLE_SHEETS_URL_REGEX =
    /^https?:\/\/docs\.google\.com\/spreadsheets\/d\/([a-zA-Z0-9_-]+)/;

/**
 * Extracts the spreadsheet ID from a Google Sheets URL.
 * @param url - The Google Sheets URL
 * @returns The spreadsheet ID or null if not a valid Google Sheets URL
 */
export function extractSpreadsheetId(url: string): string | null {
    const trimmed = url.trim();
    const match = trimmed.match(GOOGLE_SHEETS_URL_REGEX);
    return match ? match[1] : null;
}

/**
 * Parses Google Sheets URLs and creates a pre-configured Google Sheets node.
 * The node will have the spreadsheet_id populated and operation set to 'read'.
 */
export const googleSheetsUrlParser: ClipboardParser = {
    name: 'Google Sheets URL',
    priority: 90, // Check before n8n but after NoClick native format

    parse(text: string): ClipboardParseResult | null {
        const spreadsheetId = extractSpreadsheetId(text);
        if (!spreadsheetId) {
            return null;
        }

        const nodeId = generateNodeId('automation-google-sheets');

        const node: Node = {
            ...createWorkflowNode(
                nodeId,
                'automation-google-sheets',
                { x: 0, y: 0 }, // Will be repositioned at cursor by the paste handler
                { operation: 'read', spreadsheet_id: spreadsheetId },
                { configValid: false },
            ),
            selected: false,
        };

        return {
            nodes: [node],
            edges: [],
        };
    },
};
