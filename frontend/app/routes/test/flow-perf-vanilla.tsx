// Vanilla React Flow performance test - minimal setup to find the performance ceiling.
// This uses raw ReactFlow with default nodes to establish the best-case performance baseline.
// Access at /test/flow-perf-vanilla?nodes=25

import { useSearchParams } from 'react-router';
import { useEffect, useState, useCallback } from 'react';
import {
    ReactFlow,
    Node,
    Edge,
    Background,
    BackgroundVariant,
    applyNodeChanges,
    applyEdgeChanges,
    NodeChange,
    EdgeChange,
    ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

// Generate simple default nodes in a grid
function generateSimpleNodes(count: number): Node[] {
    const nodes: Node[] = [];
    const gridCols = Math.ceil(Math.sqrt(count));

    for (let i = 0; i < count; i++) {
        const col = i % gridCols;
        const row = Math.floor(i / gridCols);
        nodes.push({
            id: `perf-node-${i}`,
            type: 'default', // Use ReactFlow's built-in default node
            position: { x: 150 + col * 200, y: 150 + row * 200 },
            data: { label: `Node ${i}` },
        });
    }

    return nodes;
}

// Generate simple edges
function generateSimpleEdges(nodes: Node[]): Edge[] {
    const edges: Edge[] = [];
    const gridCols = Math.ceil(Math.sqrt(nodes.length));

    for (let i = 0; i < nodes.length - 1; i++) {
        if ((i + 1) % gridCols !== 0) {
            edges.push({
                id: `edge-${i}-${i + 1}`,
                source: nodes[i].id,
                target: nodes[i + 1].id,
            });
        }
    }
    return edges;
}

function VanillaFlowCanvas({ initialNodeCount }: { initialNodeCount: number }) {
    const [nodes, setNodes] = useState<Node[]>([]);
    const [edges, setEdges] = useState<Edge[]>([]);
    const [isReady, setIsReady] = useState(false);

    // Initialize nodes
    useEffect(() => {
        const timer = setTimeout(() => {
            const mockNodes = generateSimpleNodes(initialNodeCount);
            const mockEdges = generateSimpleEdges(mockNodes);
            setNodes(mockNodes);
            setEdges(mockEdges);
            setIsReady(true);
            console.log(`[VanillaPerfTest] Injected ${mockNodes.length} nodes`);
        }, 300);

        return () => clearTimeout(timer);
    }, [initialNodeCount]);

    // Expose test API
    useEffect(() => {
        const testAPI = {
            getNodeCount: () => nodes.length,
            injectNodes: (count: number) => {
                const newNodes = generateSimpleNodes(count);
                const newEdges = generateSimpleEdges(newNodes);
                setNodes(newNodes);
                setEdges(newEdges);
                return { nodes: newNodes.length, edges: newEdges.length };
            },
            clearNodes: () => {
                setNodes([]);
                setEdges([]);
            },
            isReady: () => isReady && nodes.length > 0,
        };

        (window as any).__perfTest = testAPI;

        return () => {
            delete (window as any).__perfTest;
        };
    }, [nodes, edges, isReady]);

    // Minimal handlers - just apply changes
    const onNodesChange = useCallback((changes: NodeChange[]) => {
        setNodes((nds) => applyNodeChanges(changes, nds));
    }, []);

    const onEdgesChange = useCallback((changes: EdgeChange[]) => {
        setEdges((eds) => applyEdgeChanges(changes, eds));
    }, []);

    return (
        <div className="w-full h-screen bg-black">
            <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                fitView={false}
                minZoom={0.15}
                maxZoom={1.25}
            >
                <Background
                    gap={10}
                    color="#222"
                    variant={BackgroundVariant.Cross}
                />
            </ReactFlow>
        </div>
    );
}

export default function FlowPerfVanillaRoute() {
    const [searchParams] = useSearchParams();
    const nodeCount = parseInt(searchParams.get('nodes') || '25', 10);
    const [isClient, setIsClient] = useState(false);

    useEffect(() => {
        (window as any).__PERF_TEST_MODE__ = true;
        setIsClient(true);

        return () => {
            delete (window as any).__PERF_TEST_MODE__;
        };
    }, []);

    if (!isClient) {
        return (
            <div className="flex items-center justify-center h-screen bg-background dark:bg-zinc-950 text-foreground">
                <p className="text-muted-foreground">
                    Loading vanilla performance test...
                </p>
            </div>
        );
    }

    return (
        <ReactFlowProvider>
            <VanillaFlowCanvas initialNodeCount={nodeCount} />
        </ReactFlowProvider>
    );
}
