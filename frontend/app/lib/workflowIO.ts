// Pure helpers for importing/exporting a workflow as a JSON file.
// Side-effecting browser bits (file download, FileReader) are wrapped here
// so FlowCanvas.tsx can stay focused on canvas state.

import type { Node, Edge } from '@xyflow/react';
import { parseClipboardContent } from '~/utils/clipboard-parsers';
import { buildSaveConfig } from '~/lib/applyNodeUpdate';

// ─── Export ───────────────────────────────────────────────────────────────────

// Serialize the current canvas state into the JSON shape that matches the
// backend's workflow_data storage format (nodes carry `config` instead of the
// live React-Flow `data`).
export function buildWorkflowExport(nodes: Node[], edges: Edge[], workflowTitle: string): string {
    const exportNodes = nodes.map((node) => ({
        id: node.id,
        type: node.type,
        position: node.position,
        config: buildSaveConfig(node),
    }));

    const exportEdges = edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
        type: edge.type,
    }));

    const workflowData = {
        name: workflowTitle || 'Untitled Workflow',
        description: '',
        workflow_data: {
            nodes: exportNodes,
            edges: exportEdges,
        },
    };

    return JSON.stringify(workflowData, null, 2);
}

// Trigger a browser download of the given JSON string. Creates a transient
// anchor element, clicks it, and revokes the object URL afterwards.
export function downloadWorkflowJson(jsonString: string, filename: string): void {
    const blob = new Blob([jsonString], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${filename || 'workflow'}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

// Convenience wrapper around buildWorkflowExport + downloadWorkflowJson.
// Throws on serialisation failure; caller should catch + alert the user.
export function exportWorkflowToFile(nodes: Node[], edges: Edge[], workflowTitle: string): void {
    const json = buildWorkflowExport(nodes, edges, workflowTitle);
    downloadWorkflowJson(json, workflowTitle);
}

// ─── Import ───────────────────────────────────────────────────────────────────

export interface ImportedWorkflow {
    nodes: Node[];
    edges: Edge[];
}

// Read a user-picked file and parse it through the clipboard parser system
// (handles all supported formats). Returns null on unsupported formats;
// throws on unreadable file / malformed JSON (caller catches + alerts).
export function readWorkflowFile(file: File): Promise<ImportedWorkflow | null> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const text = e.target?.result as string;
            if (!text) {
                reject(new Error('Failed to read file'));
                return;
            }
            try {
                const result = parseClipboardContent(text);
                resolve(result as ImportedWorkflow | null);
            } catch (err) {
                reject(err);
            }
        };
        reader.onerror = () => reject(reader.error ?? new Error('FileReader error'));
        reader.readAsText(file);
    });
}

// Compute the offset needed to re-anchor an imported node cluster at the
// centre of the current viewport. The `-200` on x nudges the cluster a bit
// left of centre so its bounding box doesn't start flush with the middle.
export function computeImportOffset(
    importedNodes: Node[],
    viewport: { x: number; y: number; zoom: number }
): { offsetX: number; offsetY: number } {
    let minX = Infinity;
    let minY = Infinity;
    importedNodes.forEach((node) => {
        minX = Math.min(minX, node.position.x);
        minY = Math.min(minY, node.position.y);
    });

    const centerX = -viewport.x / viewport.zoom + window.innerWidth / 2 / viewport.zoom;
    const centerY = -viewport.y / viewport.zoom + window.innerHeight / 2 / viewport.zoom;

    return {
        offsetX: centerX - minX - 200,
        offsetY: centerY - minY,
    };
}

// Reposition each imported node by (offsetX, offsetY). Returns a new array
// so the input is not mutated.
export function repositionImportedNodes(
    importedNodes: Node[],
    offsetX: number,
    offsetY: number
): Node[] {
    return importedNodes.map((node) => ({
        ...node,
        position: {
            x: node.position.x + offsetX,
            y: node.position.y + offsetY,
        },
    }));
}
