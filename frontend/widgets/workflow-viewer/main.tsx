// MCP Apps widget entry point for the workflow viewer.
// Uses @modelcontextprotocol/ext-apps App class for host communication
// and renders the workflow using real ReactFlow components.

import '~/tailwind.css';

import { createRoot, Root } from 'react-dom/client';
import { App, PostMessageTransport } from '@modelcontextprotocol/ext-apps';
import { WorkflowViewer } from './WorkflowViewer';
import { parseWorkflowXml, toReactFlowData } from './xmlToReactFlow';
import type { Node, Edge } from '@xyflow/react';

// Rewrite /icons/*.svg src attributes to absolute CDN URLs.
// ChatGPT's CSP blocks <base href>, so we use a MutationObserver instead.
const CDN_ORIGIN = 'https://noclick.com';
function rewriteIconSrc(img: HTMLImageElement) {
    const src = img.getAttribute('src');
    if (src && src.startsWith('/icons/')) {
        img.src = CDN_ORIGIN + src;
    }
}
// Rewrite existing and future <img> elements
const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
        for (const node of m.addedNodes) {
            if (node instanceof HTMLImageElement) rewriteIconSrc(node);
            if (node instanceof HTMLElement) {
                node.querySelectorAll<HTMLImageElement>('img[src^="/icons/"]').forEach(rewriteIconSrc);
            }
        }
    }
});
observer.observe(document.documentElement, { childList: true, subtree: true });

// State
let root: Root | null = null;
let currentNodes: Node[] = [];
let currentEdges: Edge[] = [];
let currentName: string | undefined;
let hasData = false;
let fallbackTimer: ReturnType<typeof setTimeout> | null = null;

function render() {
    if (!root) {
        const el = document.getElementById('root');
        if (!el) return;
        root = createRoot(el);
    }
    root.render(
        <WorkflowViewer
            nodes={currentNodes}
            edges={currentEdges}
            workflowName={currentName}
            loading={!hasData}
        />,
    );
}

function handleData(data: Record<string, unknown>) {
    const xml = (data.workflow_xml as string) || '';
    const name = (data.name as string) || undefined;
    if (!xml) {
        console.warn('[NoClick Widget] handleData called but no workflow_xml found in:', Object.keys(data));
        return;
    }

    console.log('[NoClick Widget] Rendering workflow:', name, `(${xml.length} chars XML)`);
    const parsed = parseWorkflowXml(xml);
    const { nodes, edges } = toReactFlowData(parsed);
    currentNodes = nodes;
    currentEdges = edges;
    currentName = name;
    hasData = true;
    if (fallbackTimer) { clearTimeout(fallbackTimer); fallbackTimer = null; }
    render();

    // Tell host we need more space now that we have content.
    // The auto-resize fires during connect() when the widget is still tiny,
    // so we send an explicit size after rendering the workflow.
    requestAnimationFrame(() => {
        app.sendSizeChanged({ width: 800, height: 500 });
    });
}

/**
 * Extract workflow data from a tool result.
 *
 * MCP hosts forward data via different paths:
 * 1. structuredContent — the standard MCP field (FastMCP sets this from ToolResult.structured_content)
 * 2. _meta — the backend copies structuredContent into _meta for hosts that only forward _meta (e.g. ChatGPT)
 * 3. content[0].text — fallback: parse the JSON text content
 */
function extractData(params: Record<string, unknown>): Record<string, unknown> | null {
    // Path 1: structuredContent (standard MCP)
    if (params.structuredContent && typeof params.structuredContent === 'object') {
        console.log('[NoClick Widget] Data source: structuredContent');
        return params.structuredContent as Record<string, unknown>;
    }

    // Path 2: _meta (injected by _patch_call_tool_meta for ChatGPT compatibility)
    if (params._meta && typeof params._meta === 'object') {
        console.log('[NoClick Widget] Data source: _meta');
        return params._meta as Record<string, unknown>;
    }

    // Path 3: Parse JSON from content[0].text
    if (Array.isArray(params.content)) {
        for (const item of params.content) {
            if (item && typeof item === 'object' && (item as Record<string, unknown>).type === 'text') {
                const text = (item as Record<string, unknown>).text as string;
                if (text) {
                    try {
                        const parsed = JSON.parse(text);
                        if (parsed && typeof parsed === 'object') {
                            console.log('[NoClick Widget] Data source: content[0].text (parsed JSON)');
                            return parsed;
                        }
                    } catch {
                        // not JSON, skip
                    }
                }
            }
        }
    }

    console.warn('[NoClick Widget] No data found in params. Keys:', Object.keys(params));
    return null;
}

/**
 * Fallback: re-fetch workflow data via callServerTool when the host doesn't
 * forward the tool result (e.g. MCP Inspector v0.20.0 bug).
 */
async function fetchViaServerTool(workflowId: string) {
    if (hasData) return;
    try {
        console.log('[NoClick Widget] Fallback: calling get_workflow via callServerTool');
        const result = await app.callServerTool({
            name: 'get_workflow',
            arguments: { workflow_id: workflowId },
        });
        if (hasData) return; // ontoolresult arrived while we were fetching
        const data = extractData(result as unknown as Record<string, unknown>);
        if (data) handleData(data);
    } catch (err) {
        console.warn('[NoClick Widget] callServerTool fallback failed:', err);
    }
}

// --- MCP Apps bridge ---
const app = new App({ name: 'noclick-workflow-viewer', version: '1.0.0' });

// Listen for tool result (primary data delivery path)
app.ontoolresult = (params) => {
    console.log('[NoClick Widget] ontoolresult received. Keys:', Object.keys(params));
    const data = extractData(params as unknown as Record<string, unknown>);
    if (data) {
        handleData(data);
    }
};

// Also handle tool input — if the host doesn't send tool-result (MCP Inspector bug),
// fall back to calling the tool directly via callServerTool after a short delay.
app.ontoolinput = (params) => {
    console.log('[NoClick Widget] ontoolinput received. Keys:', Object.keys(params));
    const args = (params.arguments as Record<string, unknown>) || {};

    // If the input already contains workflow_xml, render immediately
    if (args.workflow_xml) {
        handleData(args);
        return;
    }

    // Schedule fallback fetch if we have a workflow_id but no data yet
    const workflowId = args.workflow_id as string | undefined;
    if (workflowId && !hasData) {
        if (fallbackTimer) clearTimeout(fallbackTimer);
        fallbackTimer = setTimeout(() => fetchViaServerTool(workflowId), 500);
    }
};

// Connect to host via postMessage
app.connect(new PostMessageTransport(window.parent, window.parent)).catch((err) => {
    console.warn('[NoClick Widget] MCP Apps connect failed, running standalone:', err);
});

// Show loading state initially
render();
