/**
 * Parser for cURL commands. When a `curl ...` command is pasted onto the
 * canvas, create an HTTP Request node pre-configured with its method, URL,
 * query params, headers, and body — the same conversion the node's "Import
 * cURL" action uses.
 */

import { Node } from '@xyflow/react';
import { ClipboardParser, ClipboardParseResult } from './types';
import { generateNodeId } from '~/utils/nodeIdGenerator';
import { createWorkflowNode } from '~/lib/applyNodeUpdate';
import { parseCurl, methodToOperation, isCurlCommand } from '~/lib/curlParser';

export const curlCommandParser: ClipboardParser = {
    name: 'cURL command',
    priority: 85, // after Google Sheets URL (90), before n8n

    parse(text: string): ClipboardParseResult | null {
        if (!isCurlCommand(text)) return null;

        let parsed;
        try {
            parsed = parseCurl(text);
        } catch {
            // Starts with "curl" but isn't a usable command (e.g. prose) — skip.
            return null;
        }

        const rawConfig: Record<string, unknown> = {
            operation: methodToOperation(parsed.method),
            url: parsed.url,
            query_params: parsed.queryParams,
            headers: parsed.headers,
            body_type: parsed.bodyType,
            body: parsed.body,
            body_form: parsed.bodyForm,
        };
        if (parsed.verifySsl === false) rawConfig.verify_ssl = 'false';

        const nodeId = generateNodeId('automation-http-request');
        const node: Node = {
            ...createWorkflowNode(
                nodeId,
                'automation-http-request',
                { x: 0, y: 0 }, // repositioned at cursor by the paste handler
                rawConfig,
                { configValid: false },
            ),
            selected: false,
        };

        return { nodes: [node], edges: [] };
    },
};
