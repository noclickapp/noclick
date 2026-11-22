// Copy and paste on the canvas: the selected steps and the connections between them written to the clipboard as text
// (the canvas's own format, clipboard/noclickFormat.ts), and a paste read back as new steps where the pointer is. What
// a copied step's settings carry is the host's to say (`canvas.clipboard`: this app writes them without their secrets),
// as is what else a paste may be (a link, a command). The keys act while the canvas is in front and nobody is typing or
// selecting text; the same copy and paste serve the right-click menu.
import { useCallback, useEffect, useRef } from 'react';
import type { Edge, Node } from '@xyflow/react';
import { toast } from 'sonner';
import { useSlot } from '@/slots';
import { CLIPBOARD } from '../slots';
import { parseClipboardContent, type ClipboardParseResult } from './clipboard/parse';

export interface CopyPasteListeners {
    /** More to write beside the copied steps (a host's own layout of them), by the key it's written under. */
    copying?: (nodeIds: Set<string>) => Record<string, unknown>;
    /** What a paste added, once it's in the graph: the steps where they landed, their connections, and what the format
     *  read (a page's grid among it). */
    pasted?: (nodes: Node[], edges: Edge[], read: ClipboardParseResult) => void;
}

export interface CopyPasteOptions {
    nodes: Node[];
    edges: Edge[];
    /** Whether the canvas is what's in front (not another tab of the workflow's page): the keys act only then. */
    active: boolean;
    setNodes: (update: (nodes: Node[]) => Node[]) => void;
    setEdges: (update: (edges: Edge[]) => Edge[]) => void;
    screenToFlowPosition?: (position: { x: number; y: number }) => { x: number; y: number };
    /** The graph after a paste: one step back. */
    captureState: (nodes: Node[], edges: Edge[]) => void;
    /** A paste the host takes itself (text it turns into steps its own way), even while a field is typed in: true once
     *  it has. */
    claim?: (text: string) => boolean;
    on?: CopyPasteListeners;
}

export interface CopyPaste {
    /** Writes steps to the clipboard: the selected ones, or exactly `nodeIds` (a menu's Copy on one step). */
    copySelection: (nodeIds?: string[]) => Promise<void>;
    /** Reads the clipboard onto the canvas, at `position` on screen (a menu's click) or where the pointer was last seen. */
    pasteFromClipboard: (position?: { x: number; y: number }) => Promise<void>;
}

/** Whether a person is typing in a field. */
function typing(): boolean {
    const active = document.activeElement;
    return active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement || active?.getAttribute('contenteditable') === 'true';
}

export function useWorkflowCopyPaste({ nodes, edges, active, setNodes, setEdges, screenToFlowPosition, captureState, claim, on }: CopyPasteOptions): CopyPaste {
    const settingsOf = useSlot(CLIPBOARD).useSettingsOf();
    const listeners = useRef(on);
    listeners.current = on;
    const claims = useRef(claim);
    claims.current = claim;

    // Where the pointer was last seen: a paste lands there.
    const pointer = useRef<{ x: number; y: number } | null>(null);
    useEffect(() => {
        const onMove = (event: MouseEvent) => {
            pointer.current = { x: event.clientX, y: event.clientY };
        };
        window.addEventListener('mousemove', onMove);
        return () => window.removeEventListener('mousemove', onMove);
    }, []);

    const copySelection = useCallback(
        async (nodeIds?: string[]) => {
            const copied = nodeIds ? nodes.filter((node) => nodeIds.includes(node.id)) : nodes.filter((node) => node.selected);
            if (copied.length === 0) return;
            const ids = new Set(copied.map((n) => n.id));
            const between = edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));

            const data: Record<string, unknown> = {
                type: 'noclick-workflow',
                version: '1.0',
                nodes: copied.map((node) => {
                    // A step that was resized (a block of a page, a note) carries its size.
                    const width = node.width ?? (node.style as { width?: number } | undefined)?.width;
                    const height = node.height ?? (node.style as { height?: number } | undefined)?.height;
                    return {
                        id: node.id,
                        type: node.type,
                        position: node.position,
                        config: settingsOf(node),
                        ...(width ? { width } : {}),
                        ...(height ? { height } : {}),
                    };
                }),
                edges: between.map((edge) => ({
                    id: edge.id,
                    source: edge.source,
                    target: edge.target,
                    sourceHandle: edge.sourceHandle,
                    targetHandle: edge.targetHandle,
                    type: edge.type,
                })),
                ...listeners.current?.copying?.(ids),
            };

            try {
                await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
                const steps = `${copied.length} node${copied.length === 1 ? '' : 's'}`;
                const connections = between.length > 0 ? ` and ${between.length} edge${between.length === 1 ? '' : 's'}` : '';
                toast.success(`Copied ${steps}${connections}`);
            } catch (error) {
                console.error('Failed to copy to clipboard:', error);
                toast.error('Failed to copy to clipboard');
            }
        },
        [nodes, edges, settingsOf]
    );

    /** Adds what `text` stands for to the canvas; nothing when no format reads it. */
    const applyText = useCallback(
        (text: string, position?: { x: number; y: number }) => {
            const read = parseClipboardContent(text);
            if (!read) return;

            let minX = Infinity;
            let minY = Infinity;
            for (const node of read.nodes) {
                minX = Math.min(minX, node.position.x);
                minY = Math.min(minY, node.position.y);
            }
            const from = position ?? pointer.current;
            const target = from && screenToFlowPosition ? screenToFlowPosition(from) : { x: 100, y: 100 };
            const offsetX = target.x - minX;
            const offsetY = target.y - minY;
            const placed = read.nodes.map((node) => ({ ...node, position: { x: node.position.x + offsetX, y: node.position.y + offsetY } }));

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
            listeners.current?.pasted?.(placed, read.edges, read);
        },
        [setNodes, setEdges, screenToFlowPosition, captureState]
    );

    const pasteFromClipboard = useCallback(
        async (position?: { x: number; y: number }) => {
            let text = '';
            try {
                text = await navigator.clipboard.readText();
            } catch (error) {
                console.error('Failed to read clipboard:', error);
                toast.error('Failed to read clipboard');
                return;
            }
            if (!text) return;
            if (claims.current?.(text)) return;
            applyText(text, position);
        },
        [applyText]
    );

    // Cmd/Ctrl+C. Typing in a field and selected text keep their own copy; a menu's Copy has no such doubt.
    useEffect(() => {
        const onCopy = async (event: ClipboardEvent) => {
            if (!active) return;
            const selection = window.getSelection();
            if (typing() || (selection && selection.toString().length > 0)) return;
            if (!nodes.some((node) => node.selected)) return;
            event.preventDefault();
            await copySelection();
        };
        window.addEventListener('copy', onCopy);
        return () => window.removeEventListener('copy', onCopy);
    }, [active, nodes, copySelection]);

    // Cmd/Ctrl+V. Heard before a field's own paste, so text the host claims never lands in the field as it is.
    useEffect(() => {
        const onPaste = (event: ClipboardEvent) => {
            if (!active) return;
            const text = event.clipboardData?.getData('text/plain');
            if (!text) return;
            if (claims.current?.(text)) {
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            if (typing()) return;
            if (!parseClipboardContent(text)) return;
            event.preventDefault();
            applyText(text);
        };
        window.addEventListener('paste', onPaste, true);
        return () => window.removeEventListener('paste', onPaste, true);
    }, [active, applyText]);

    return { copySelection, pasteFromClipboard };
}
