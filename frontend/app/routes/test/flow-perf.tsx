// Performance test route for React Flow drag operations with full dashboard UI.
// Uses the ACTUAL FlowCanvas component for 1:1 production parity.
// Only available in development mode. Access at /test/flow-perf?nodes=10

import { useSearchParams } from 'react-router';
import { useEffect, useState, useCallback, useRef } from 'react';
import { Node, Edge } from '@xyflow/react';
import FlowCanvas from '~/components/workflow/FlowCanvas';
import { DndProvider } from '~/providers/DndProvider';
import { ChatDrawerProvider } from '~/components/chat/drawer/ChatDrawerProvider';
import { NoClick } from '~/components/chat/NoClick';
import { NavBar } from '~/components/nav/NavBar';
import { useValtioState } from '~/hooks/useValtioState';
import { getDefaultPanelWidth } from '~/lib/constants';
import { graphRecords, recordGraphSnapshot } from '~/lib/liveGraphStore';
import { OnboardingProvider } from '~/hooks/useOnboarding';

// Must match the workflowId passed to <FlowCanvas>; useLiveGraph keys
// graphRecords by it.
const PERF_WORKFLOW_ID = '00000000-0000-0000-0000-000000000000';

// Generate mock nodes in a grid pattern using real node types
function generateMockNodes(count: number): Node[] {
    const nodes: Node[] = [];
    const gridCols = Math.ceil(Math.sqrt(count));
    const nodeTypes = [
        'automation-http-request',
        'automation-telegram',
        'automation-gmail',
        'automation-google-sheets',
        'automation-linear',
        'automation-slack',
        'automation-notion',
        'automation-github',
    ];

    for (let i = 0; i < count; i++) {
        const col = i % gridCols;
        const row = Math.floor(i / gridCols);
        nodes.push({
            id: `perf-node-${i}`,
            type: nodeTypes[i % nodeTypes.length],
            position: { x: 150 + col * 200, y: 150 + row * 200 },
            data: {
                label: `Node ${i}`,
                config: {},
            },
        });
    }

    return nodes;
}

// Generate edges connecting sequential nodes in rows
function generateMockEdges(nodes: Node[]): Edge[] {
    const edges: Edge[] = [];
    const gridCols = Math.ceil(Math.sqrt(nodes.length));

    for (let i = 0; i < nodes.length - 1; i++) {
        if ((i + 1) % gridCols !== 0) {
            edges.push({
                id: `edge-${i}-${i + 1}`,
                source: nodes[i].id,
                target: nodes[i + 1].id,
                // Match FlowCanvas edge styling exactly
                type: 'animated',
                style: { stroke: '#ffffff', strokeWidth: 3, opacity: 0.8 },
                data: { isAnimating: false },
            });
        }
    }
    return edges;
}

// Mock user for NavBar (matches production structure)
const mockUser = {
    email: 'perf-test@noclick.com',
    avatar_url: undefined,
    subscription_tier: 'pro' as const,
    created_at: new Date().toISOString(),
};

// Full Dashboard Layout with real NoClick, NavBar, and FlowCanvas
function FullDashboardLayout({
    initialNodeCount,
}: {
    initialNodeCount: number;
}) {
    const valtioPath = '/perf-test';

    // Use the same state management as real Dashboard
    const [isChatExpanded, setIsChatExpanded] = useValtioState<boolean>(
        valtioPath,
        'isChatExpanded',
        true
    );
    const [chatWidth, setChatWidth] = useValtioState<number>(
        valtioPath,
        'chatWidth',
        getDefaultPanelWidth()
    );
    const [isDragging, setIsDragging] = useValtioState<boolean>(
        valtioPath,
        'isDragging',
        false
    );
    const [selectedTab, setSelectedTab] = useValtioState<string>(
        valtioPath,
        'selectedTab',
        'flow'
    );

    // Use refs to avoid subscribing to flow state (which causes re-renders during drag)
    // This is critical for performance testing - parent subscribing to flow state
    // causes cascade re-renders when FlowCanvas updates nodes
    const nodesInjectedRef = useRef(false);
    const [isReady, setIsReady] = useState(false);

    const handleTabChange = useCallback(
        (tab: string) => {
            setSelectedTab(tab);
        },
        [setSelectedTab]
    );

    // Inject nodes via liveGraphStore. recordGraphSnapshot writes
    // straight into graphRecords[workflowId] which is what FlowCanvas
    // reads through useLiveGraph. The 300 ms delay matches the
    // pre-Phase-2 timing (FlowCanvas needs a tick to mount before its
    // useSnapshot picks up the seeded state).
    useEffect(() => {
        if (nodesInjectedRef.current) return;
        const timer = setTimeout(() => {
            const mockNodes = generateMockNodes(initialNodeCount);
            const mockEdges = generateMockEdges(mockNodes);
            recordGraphSnapshot(
                PERF_WORKFLOW_ID,
                false,
                {
                    nodes: mockNodes,
                    edges: mockEdges,
                },
                false /* don't fire a save — placeholder workflow id */
            );
            nodesInjectedRef.current = true;
            setIsReady(true);
            console.log(
                `[PerfTest] Injected ${mockNodes.length} nodes and ${mockEdges.length} edges via liveGraphStore`
            );
        }, 300);

        return () => clearTimeout(timer);
    }, [initialNodeCount]);

    // Expose test utilities on window for Playwright
    useEffect(() => {
        (window as any).__perfTest = {
            getNodeCount: () =>
                graphRecords[PERF_WORKFLOW_ID]?.nodes.length ?? 0,
            injectNodes: (count: number) => {
                const newNodes = generateMockNodes(count);
                const newEdges = generateMockEdges(newNodes);
                recordGraphSnapshot(
                    PERF_WORKFLOW_ID,
                    false,
                    {
                        nodes: newNodes,
                        edges: newEdges,
                    },
                    false
                );
                return { nodes: newNodes.length, edges: newEdges.length };
            },
            clearNodes: () => {
                recordGraphSnapshot(
                    PERF_WORKFLOW_ID,
                    false,
                    {
                        nodes: [],
                        edges: [],
                    },
                    false
                );
            },
            isReady: () => isReady,
        };
        console.log(`[PerfTest] Test API ready, isReady: ${isReady}`);

        return () => {
            delete (window as any).__perfTest;
        };
    }, [isReady]);

    return (
        <OnboardingProvider>
            <ChatDrawerProvider>
                <DndProvider>
                    <div
                        className="min-h-screen flex"
                        data-testid="flow-perf-container"
                    >
                        {/* Real NoClick Sidebar */}
                        <NoClick
                            isExpanded={isChatExpanded}
                            onExpandChange={setIsChatExpanded}
                            onWidthChange={setChatWidth}
                            onDragChange={setIsDragging}
                            isMobileMode={false}
                        />

                        {/* Main Content */}
                        <div
                            className="flex-1"
                            style={{
                                marginLeft: isChatExpanded
                                    ? `${chatWidth}px`
                                    : '50px',
                                transition: isDragging
                                    ? 'none'
                                    : 'all 300ms ease-in-out',
                            }}
                        >
                            {/* Real NavBar */}
                            <div
                                className="fixed top-0 right-0 z-10"
                                style={{
                                    width: `calc(100% - ${isChatExpanded ? chatWidth : 50}px)`,
                                    transition: isDragging
                                        ? 'none'
                                        : 'all 300ms ease-in-out',
                                }}
                            >
                                <NavBar
                                    user={mockUser}
                                    selectedTab={selectedTab}
                                    onTabChange={handleTabChange}
                                />
                            </div>

                            {/* Main content area */}
                            <main
                                className="pt-14 w-full overflow-hidden"
                                style={{ height: 'calc(100vh - 0px)' }}
                            >
                                <div
                                    className="h-full"
                                    data-testid="flow-canvas"
                                >
                                    {/* ACTUAL FlowCanvas component - 1:1 with production */}
                                    {/* Use a valid UUID format for test workflow to avoid backend errors */}
                                    <FlowCanvas
                                        workflowTitle="Performance Test Workflow"
                                        workflowId={PERF_WORKFLOW_ID}
                                        onBack={() => {}}
                                    />
                                </div>
                            </main>
                        </div>
                    </div>
                </DndProvider>
            </ChatDrawerProvider>
        </OnboardingProvider>
    );
}

export default function FlowPerfRoute() {
    const [searchParams] = useSearchParams();
    const nodeCount = parseInt(searchParams.get('nodes') || '5', 10);

    // Client-only rendering to avoid SSR issues with NoClick (uses window)
    const [isClient, setIsClient] = useState(false);

    useEffect(() => {
        // Set test mode flag to disable auth redirect
        (window as any).__PERF_TEST_MODE__ = true;
        setIsClient(true);

        return () => {
            delete (window as any).__PERF_TEST_MODE__;
        };
    }, []);

    // Show loading state during SSR
    if (!isClient) {
        return (
            <div className="flex items-center justify-center h-screen bg-background dark:bg-zinc-950 text-foreground">
                <p className="text-muted-foreground">
                    Loading performance test...
                </p>
            </div>
        );
    }

    return <FullDashboardLayout initialNodeCount={nodeCount} />;
}
