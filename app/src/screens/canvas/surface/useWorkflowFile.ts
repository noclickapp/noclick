// A workflow saved to a file and read from one, as the canvas does both (workflowFile.ts holds the format): saving
// writes every step and connection the canvas holds, each step's settings as a copy carries them (`canvas.clipboard`);
// reading adds the file's steps as new ones in the middle of what's in view, one step back in the undo history. What
// goes wrong is said through `refuse`, in the canvas's own way.
import { useCallback, type ChangeEvent } from 'react';
import type { Edge, Node } from '@xyflow/react';
import { useSlot } from '@/slots';
import { CLIPBOARD } from '../slots';
import { computeImportOffset, exportWorkflowToFile, readWorkflowFile, repositionImportedNodes } from './workflowFile';

export interface WorkflowFileOptions {
    nodes: Node[];
    edges: Edge[];
    /** The workflow's name, which names the file. */
    title: string;
    setNodes: (update: (nodes: Node[]) => Node[]) => void;
    setEdges: (update: (edges: Edge[]) => Edge[]) => void;
    /** The graph after a file is read: one step back. */
    captureState: (nodes: Node[], edges: Edge[]) => void;
    getViewport: () => { x: number; y: number; zoom: number };
    /** Says why a file wasn't read or written. */
    refuse: (message: string) => void;
    /** The steps a file added, once they're in the graph. */
    onImported?: (nodes: Node[]) => void;
}

export interface WorkflowFile {
    /** Saves the workflow to a file. */
    exportFile: () => void;
    /** Reads the file a file input was given. */
    importFile: (event: ChangeEvent<HTMLInputElement>) => Promise<void>;
}

export function useWorkflowFile({ nodes, edges, title, setNodes, setEdges, captureState, getViewport, refuse, onImported }: WorkflowFileOptions): WorkflowFile {
    const settingsOf = useSlot(CLIPBOARD).useSettingsOf();

    const exportFile = useCallback(() => {
        try {
            exportWorkflowToFile(nodes, edges, title || 'workflow', settingsOf);
        } catch (error) {
            console.error('[Export] Error exporting workflow:', error);
            refuse('Error exporting workflow. Please try again.');
        }
    }, [nodes, edges, title, settingsOf, refuse]);

    const importFile = useCallback(
        async (event: ChangeEvent<HTMLInputElement>) => {
            const file = event.target.files?.[0];
            if (!file) return;
            // So the same file can be picked again.
            event.target.value = '';

            try {
                const read = await readWorkflowFile(file);
                if (!read) {
                    refuse('Unsupported workflow format. Please use a valid NoClick workflow JSON file.');
                    return;
                }
                const { offsetX, offsetY } = computeImportOffset(read.nodes, getViewport());
                const placed = repositionImportedNodes(read.nodes, offsetX, offsetY);

                let newNodes: Node[] = [];
                let newEdges: Edge[] = [];
                setNodes((existing) => {
                    newNodes = [...existing, ...placed];
                    return newNodes;
                });
                setEdges((existing) => {
                    newEdges = [...existing, ...read.edges];
                    return newEdges;
                });
                setTimeout(() => captureState(newNodes, newEdges), 0);
                onImported?.(placed);
            } catch (error) {
                console.error('[Import] Error importing workflow file:', error);
                refuse('Error importing workflow. Please check that the file is valid JSON.');
            }
        },
        [setNodes, setEdges, captureState, getViewport, refuse, onImported]
    );

    return { exportFile, importFile };
}
