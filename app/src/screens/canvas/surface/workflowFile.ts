// A workflow as a file: saved as JSON in the shape the platform stores a workflow's graph in (each step's settings under
// `config`), and read back as new steps through the clipboard's formats, so a file and a paste are read alike. What a
// step's settings carry into the file is the caller's to say, as for a copy (`canvas.clipboard`).
import type { Edge, Node } from '@xyflow/react';
import { downloadText } from '@/lib/download';
import { parseClipboardContent } from './clipboard/parse';

/** The workflow as the text of its file. `settingsOf` gives each step's settings as they're written. */
export function buildWorkflowExport(nodes: Node[], edges: Edge[], workflowTitle: string, settingsOf: (node: Node) => Record<string, unknown>): string {
    return JSON.stringify(
        {
            name: workflowTitle || 'Untitled Workflow',
            description: '',
            workflow_data: {
                nodes: nodes.map((node) => ({ id: node.id, type: node.type, position: node.position, config: settingsOf(node) })),
                edges: edges.map((edge) => ({
                    id: edge.id,
                    source: edge.source,
                    target: edge.target,
                    sourceHandle: edge.sourceHandle,
                    targetHandle: edge.targetHandle,
                    type: edge.type,
                })),
            },
        },
        null,
        2
    );
}

/** Hands the browser the file to save. */
export function downloadWorkflowJson(json: string, filename: string): void {
    downloadText(json, `${filename || 'workflow'}.json`, 'application/json');
}

/** Saves the workflow to a file named after it. Throws where it can't be written as JSON: the caller says so. */
export function exportWorkflowToFile(nodes: Node[], edges: Edge[], workflowTitle: string, settingsOf: (node: Node) => Record<string, unknown>): void {
    downloadWorkflowJson(buildWorkflowExport(nodes, edges, workflowTitle, settingsOf), workflowTitle);
}

export interface ImportedWorkflow {
    nodes: Node[];
    edges: Edge[];
}

/** The steps a picked file holds, in any format a paste is read in; null for a file in none of them. Rejects when the
 *  file can't be read. */
export function readWorkflowFile(file: File): Promise<ImportedWorkflow | null> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (event) => {
            const text = event.target?.result as string;
            if (!text) {
                reject(new Error('Failed to read file'));
                return;
            }
            try {
                resolve(parseClipboardContent(text) as ImportedWorkflow | null);
            } catch (error) {
                reject(error);
            }
        };
        reader.onerror = () => reject(reader.error ?? new Error('FileReader error'));
        reader.readAsText(file);
    });
}

/** How far to move the steps read from a file so they land in the middle of what's in view (a little left of it, so
 *  their box doesn't start at the centre line). */
export function computeImportOffset(importedNodes: Node[], viewport: { x: number; y: number; zoom: number }): { offsetX: number; offsetY: number } {
    let minX = Infinity;
    let minY = Infinity;
    for (const node of importedNodes) {
        minX = Math.min(minX, node.position.x);
        minY = Math.min(minY, node.position.y);
    }
    const centerX = -viewport.x / viewport.zoom + window.innerWidth / 2 / viewport.zoom;
    const centerY = -viewport.y / viewport.zoom + window.innerHeight / 2 / viewport.zoom;
    return { offsetX: centerX - minX - 200, offsetY: centerY - minY };
}

/** The steps moved by the offset, as new objects. */
export function repositionImportedNodes(importedNodes: Node[], offsetX: number, offsetY: number): Node[] {
    return importedNodes.map((node) => ({ ...node, position: { x: node.position.x + offsetX, y: node.position.y + offsetY } }));
}
