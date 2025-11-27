/**
 * Parser for n8n workflow JSON format.
 * Wraps the existing n8n-converter utility for clipboard parsing.
 */

import { ClipboardParser, ClipboardParseResult } from './types';
import { parseClipboardAsN8nWorkflow } from '~/utils/n8n-converter';

/**
 * Parses n8n workflow JSON format from clipboard.
 * Delegates to the existing n8n-converter utility.
 */
export const n8nParser: ClipboardParser = {
    name: 'n8n Workflow',
    priority: 80, // Secondary to NoClick format

    parse(text: string): ClipboardParseResult | null {
        const result = parseClipboardAsN8nWorkflow(text);
        if (!result) {
            return null;
        }

        return {
            nodes: result.nodes,
            edges: result.edges,
        };
    },
};
