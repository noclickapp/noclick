import { useState } from 'react';
import { Node, Edge } from '@xyflow/react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useNodeOutputHistory, resolveDisplayOutput } from '~/hooks/useNodeOutputHistory';
import { useNodeOutputSchema } from '~/hooks/useNodeOutputSchema';
import { navigateToNode } from '~/utils/workflowNavigation';
import { IODataDisplay } from '../IODataDisplay';
import { getDefaultLabelFromType } from '../nodes/base/NodeLabel';
import { getDisplayStrategy, getNodeMetadata, type JsonValue } from '../nodes/nodeRegistry';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { HistoryCarousel } from './HistoryCarousel';
import { getNodeOperation } from './utils';

// Single input node display component — handles schema fallback when no output.
// Separated so hooks (output history, schema fetch) are scoped per input node.
interface InputNodeDisplayProps {
    node: Node;
    workflowId: string;
    selectedNodeId?: string;
    allEdges: Edge[];
    initialHistoryIndex?: number;
    onHistoryIndexChange?: (nodeId: string, historyIndex: number, output: unknown | undefined) => void;
}

const InputNodeDisplay = ({
    node,
    workflowId,
    selectedNodeId,
    allEdges,
    initialHistoryIndex,
    onHistoryIndexChange,
}: InputNodeDisplayProps) => {
    const nodeType = node.type || '';
    const nodeConfig = node.data || {};
    const nodeOperation = getNodeOperation(nodeConfig);

    // Fetch expected schema + curated suggested refs. Suggestions live on
    // the same socket round trip as the schema and are cache-shared with
    // the OutputPanel.
    const {
        schema: expectedSchema,
        suggestedRefs,
        isLoading: isLoadingSchema,
    } = useNodeOutputSchema({
        nodeType: nodeType || undefined,
        nodeOperation: nodeOperation || undefined,
        enabled: !!nodeType && !!nodeOperation,
    });

    // Fetch output history for carousel navigation
    const { historyEntries, historyIndex, setHistoryIndex } = useNodeOutputHistory({
        workflowId,
        nodeId: node.id,
        refetchTrigger: node.data?.output,
        initialHistoryIndex,
        onIndexChange: onHistoryIndexChange,
    });

    const { displayOutput, isMocked, hasDisplayOutput } = resolveDisplayOutput({
        mockedOutput: node.data?.mockedOutput,
        liveOutput: node.data?.output,
        historyEntries,
        historyIndex,
    });

    // Get display strategy from the source node's type. OutputPanelContent is the only
    // genuinely-optional method consumed here (UI override).
    const OutputPanelContent = getDisplayStrategy(node.type).OutputPanelContent;

    // Find the edge connecting this input node to the selected node to get the source handle.
    // Used by nodes with multiple output handles (like iteration) to show the right tab.
    const connectingEdge = selectedNodeId
        ? allEdges.find((e) => e.source === node.id && e.target === selectedNodeId)
        : undefined;
    const sourceHandle = connectingEdge?.sourceHandle;

    // Get node metadata for icon
    const nodeMetadata = node.type ? getNodeMetadata(node.type) : undefined;

    // Default label from node type
    const defaultLabel = getDefaultLabelFromType(node.type || '');

    // Input data starts expanded; the caret in the header toggles it.
    const [isExpanded, setIsExpanded] = useState(true);

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-1.5">
                {nodeMetadata && workflowId ? (
                    <button
                        onClick={() => navigateToNode(workflowId, node.id)}
                        className="p-1 -m-1 rounded hover:bg-foreground/10 transition-colors flex-shrink-0"
                        title="Go to node"
                    >
                        <BrandIcon Icon={nodeMetadata.Icon} iconColor={nodeMetadata.iconColor} className="w-4 h-4 flex-shrink-0" />
                    </button>
                ) : nodeMetadata ? (
                    <BrandIcon Icon={nodeMetadata.Icon} iconColor={nodeMetadata.iconColor} className="w-4 h-4 flex-shrink-0" />
                ) : null}
                <button
                    onClick={() => setIsExpanded((v) => !v)}
                    aria-expanded={isExpanded}
                    title={isExpanded ? 'Collapse input data' : 'Expand input data'}
                    className="group inline-flex items-center gap-1.5 min-w-0 -ml-1 px-1 py-0.5 rounded cursor-pointer hover:bg-foreground/5 transition-colors"
                >
                    <span className="min-w-0 text-xs text-foreground/80 font-medium truncate group-hover:text-foreground transition-colors">
                        {String(node.data?.label || defaultLabel)}
                    </span>
                    {isExpanded ? (
                        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground group-hover:text-foreground transition-colors flex-shrink-0" />
                    ) : (
                        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground group-hover:text-foreground transition-colors flex-shrink-0" />
                    )}
                </button>
                {isMocked && (
                    <span className="text-[9px] font-bold tracking-widest text-foreground/80 bg-secondary dark:bg-zinc-700/50 px-1.5 py-0.5 rounded flex-shrink-0">
                        MOCK
                    </span>
                )}
            </div>
            {isExpanded && (
                <>
                    {!isMocked && (
                        <HistoryCarousel
                            historyEntries={historyEntries}
                            historyIndex={historyIndex}
                            setHistoryIndex={setHistoryIndex}
                            size="sm"
                        />
                    )}
                    {isLoadingSchema && !hasDisplayOutput ? (
                        <div className="text-xs text-muted-foreground dark:text-zinc-500">Loading schema...</div>
                    ) : OutputPanelContent ? (
                        <OutputPanelContent
                            nodeId={node.id}
                            output={(displayOutput ?? null) as JsonValue}
                            draggable={true}
                            sourceHandle={sourceHandle ?? undefined}
                            nodeData={nodeConfig as Record<string, unknown>}
                        />
                    ) : hasDisplayOutput ? (
                        <IODataDisplay
                            data={displayOutput}
                            label=""
                            nodeId={node.id}
                            draggable={true}
                            suggestedRefs={suggestedRefs}
                        />
                    ) : expectedSchema ? (
                        <IODataDisplay
                            data={expectedSchema}
                            label=""
                            nodeId={node.id}
                            draggable={true}
                            isSchema={true}
                            suggestedRefs={suggestedRefs}
                        />
                    ) : (
                        <div className="text-xs text-muted-foreground/70 dark:text-zinc-600 italic">No output yet</div>
                    )}
                </>
            )}
        </div>
    );
};

// Input panel showing outputs from connected source nodes.
// Enables draggable JSON fields so users can drag values into config fields.
// Uses mockedOutput (mock data) if available, otherwise shows live output.
// Uses node's display strategy for custom rendering (e.g., iteration nodes show simplified variables).
interface InputPanelProps {
    inputNodes: Node[];
    workflowId: string;
    selectedNodeId?: string;
    allEdges: Edge[];
    nodeOutputSelectionsRef?: React.RefObject<Record<string, { historyIndex: number; output: unknown }>>;
    onNodeOutputSelection?: (nodeId: string, historyIndex: number, output: unknown | undefined) => void;
}

export const InputPanel = ({
    inputNodes,
    workflowId,
    selectedNodeId,
    allEdges,
    nodeOutputSelectionsRef,
    onNodeOutputSelection,
}: InputPanelProps) => {
    if (inputNodes.length === 0) {
        return (
            <div className="flex items-center justify-center h-full text-muted-foreground dark:text-zinc-500 text-sm">
                No input connections
            </div>
        );
    }

    return (
        <div className="space-y-4">
            <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                Inputs <span className="text-muted-foreground">({inputNodes.length})</span>
            </div>
            {inputNodes.map((node) => (
                <InputNodeDisplay
                    key={node.id}
                    node={node}
                    workflowId={workflowId}
                    selectedNodeId={selectedNodeId}
                    allEdges={allEdges}
                    initialHistoryIndex={nodeOutputSelectionsRef?.current?.[node.id]?.historyIndex}
                    onHistoryIndexChange={onNodeOutputSelection}
                />
            ))}
        </div>
    );
};
