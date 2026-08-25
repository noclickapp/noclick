/**
 * ReadOnlyFlowHelperView - Read-only version of FlowHelperView for public workflow viewing.
 * Matches the visual appearance and layout of FlowHelperView but without editing capabilities.
 * Shows Nodes (browse available nodes), Config (view selected node configuration), and
 * Credentials (view which credentials the selected node uses — values stay hidden) tabs.
 */

import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { X, Boxes, Settings, Key, ArrowDownToLine, ArrowUpFromLine, Maximize2, Minimize2 } from 'lucide-react';
import type { Node, Edge } from '@xyflow/react';
import { getNodeMetadata, getDisplayStrategy, type JsonValue } from './nodes/nodeRegistry';
import { BrandIcon } from '~/components/shared/BrandIcon';
import { IODataDisplay } from './IODataDisplay';
import { NodeConfig } from './NodeConfig';
import { NodesTabContent } from './flowHelper/NodesTabContent';
import { CredentialsTabContent } from './flowHelper/CredentialsTabContent';
import { AgentToolOperationsPicker } from './AgentToolOperationsPicker';
import { getToolProviderConsumerTypes } from '~/utils/nodeSchemas';
import { hasUnconnectedCredentials, providerCredentialsMissing } from './NodeCredentials';

type TabType = 'nodes' | 'config' | 'credentials';

interface ReadOnlyFlowHelperViewProps {
    selectedNode: Node | null;
    nodes: Node[];
    edges: Edge[];
    onClose: () => void;
    height: number;
    onHeightChange: (height: number) => void;
    containerRef: React.RefObject<HTMLDivElement | null>;
    activeTab: TabType;
    onActiveTabChange: (tab: TabType) => void;
    onForkPrompt?: () => void;
}


// Vertical resize handle component
const VerticalResizeHandle = ({ onMouseDown }: { onMouseDown: (e: React.MouseEvent) => void }) => (
    <button
        type="button"
        aria-label="Resize panel height"
        className="absolute top-0 left-0 right-0 h-2 bg-transparent hover:bg-accent/50 dark:hover:bg-zinc-500/10 transition-all cursor-ns-resize z-30 group border-none outline-none"
        onMouseDown={onMouseDown}
    >
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-16 h-1 rounded-full bg-muted-foreground/30 dark:bg-zinc-600/30 group-hover:bg-muted-foreground/50 transition-colors" />
    </button>
);

// Horizontal resize handle component
const ResizeHandle = ({ onMouseDown, position }: { onMouseDown: (e: React.MouseEvent) => void; position: 'left' | 'right' }) => (
    <div
        className="absolute top-0 bottom-0 w-1 hover:w-1.5 bg-transparent hover:bg-blue-500/30 transition-all cursor-col-resize z-20 group"
        style={{ [position === 'left' ? 'left' : 'right']: 0 }}
        onMouseDown={onMouseDown}
    >
        <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-0.5 bg-border dark:bg-zinc-700/50 group-hover:bg-blue-500/50 transition-colors" />
    </div>
);

// Input panel showing outputs from connected source nodes
const InputPanel = ({ inputNodes }: { inputNodes: Node[] }) => {
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
            {inputNodes.map((node) => {
                const mockedOutput = node.data?.mockedOutput;
                const liveOutput = node.data?.output;
                const displayOutput = mockedOutput !== undefined ? mockedOutput : liveOutput;
                const isMocked = mockedOutput !== undefined;
                const OutputPanelContent = getDisplayStrategy(node.type).OutputPanelContent;
                const nodeDef = getNodeMetadata(node.type || 'default');

                return (
                    <div key={node.id} className="space-y-2">
                        <div className="flex items-center gap-2">
                            {nodeDef && (
                                <BrandIcon Icon={nodeDef.Icon} iconColor={nodeDef.iconColor} className="w-3.5 h-3.5" />
                            )}
                            <div className="text-xs text-foreground/80 font-medium">{nodeDef?.label || node.type}</div>
                            <div className="text-[10px] text-muted-foreground dark:text-zinc-500 font-mono">{node.id}</div>
                            {isMocked && (
                                <span className="text-[9px] font-bold tracking-widest text-foreground/80 bg-secondary dark:bg-zinc-700/50 px-1.5 py-0.5 rounded">
                                    MOCK
                                </span>
                            )}
                        </div>
                        {OutputPanelContent ? (
                            <OutputPanelContent nodeId={node.id} output={(displayOutput ?? null) as JsonValue} draggable={false} nodeData={node.data as Record<string, unknown>} />
                        ) : (
                            <IODataDisplay
                                data={displayOutput}
                                label=""
                                nodeId={node.id}
                                draggable={false}
                            />
                        )}
                    </div>
                );
            })}
        </div>
    );
};

// Output panel showing the selected node's output
const OutputPanel = ({ selectedNode }: { selectedNode: Node | null }) => {
    if (!selectedNode) {
        return (
            <div className="flex items-center justify-center h-full text-muted-foreground dark:text-zinc-500 text-sm">
                No node selected
            </div>
        );
    }

    const output = selectedNode.data?.output;
    const mockedOutput = selectedNode.data?.mockedOutput;
    const isMocked = mockedOutput !== undefined;
    const displayOutput = isMocked ? mockedOutput : output;
    const hasDisplayOutput = displayOutput !== undefined && displayOutput !== null;
    const OutputPanelContent = getDisplayStrategy(selectedNode.type).OutputPanelContent;

    if (!hasDisplayOutput) {
        return (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground dark:text-zinc-500 text-sm gap-2">
                <span>No output yet</span>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                    Output
                </div>
                {isMocked && (
                    <span className="text-[9px] font-bold tracking-widest text-foreground/80 bg-secondary dark:bg-zinc-700/50 px-1.5 py-0.5 rounded">
                        MOCK
                    </span>
                )}
            </div>

            {OutputPanelContent && (
                <OutputPanelContent nodeId={selectedNode.id} output={displayOutput as JsonValue} draggable={false} />
            )}

            {hasDisplayOutput && (
                <details open={!OutputPanelContent}>
                    <summary className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider cursor-pointer hover:text-foreground/80 transition-colors mb-2">
                        {OutputPanelContent ? 'Raw Output Data' : 'Data'}
                    </summary>
                    <IODataDisplay
                        data={displayOutput}
                        label=""
                        nodeId={selectedNode.id}
                        draggable={false}
                    />
                </details>
            )}
        </div>
    );
};

export function ReadOnlyFlowHelperView({
    selectedNode,
    nodes,
    edges,
    onClose,
    height,
    onHeightChange,
    containerRef,
    activeTab,
    onActiveTabChange,
    onForkPrompt,
}: ReadOnlyFlowHelperViewProps) {
    const [showInput, setShowInput] = useState(false);
    const [showOutput, setShowOutput] = useState(false);
    const [inputPanelWidth, setInputPanelWidth] = useState(320);
    const [outputPanelWidth, setOutputPanelWidth] = useState(320);
    const [isFullScreen, setIsFullScreen] = useState(false);

    // Refs for direct DOM manipulation during resize
    const inputPanelRef = useRef<HTMLDivElement>(null);
    const outputPanelRef = useRef<HTMLDivElement>(null);
    const configCageRef = useRef<HTMLDivElement>(null);
    const credentialsCageRef = useRef<HTMLDivElement>(null);

    // Native DOM capture beats React's synthetic events and any third-party
    // listeners. Stops OAuth-button window.open and similar before they run.
    // Same cage applied to both Config (inputs/buttons) and Credentials (OAuth
    // "Connect" buttons) tabs — the credentials picker is interactive even when
    // we pass a no-op onChange, so without this cage clicking "Connect Google"
    // would open an OAuth popup from a replay/preview surface.
    useEffect(() => {
        const els = [configCageRef.current, credentialsCageRef.current].filter(Boolean) as HTMLElement[];
        if (els.length === 0) return;
        const interactiveSelector = 'button, input, textarea, select, [role="button"], a, [contenteditable="true"]';
        const intercept = (e: Event) => {
            const target = e.target as HTMLElement | null;
            if (target?.closest(interactiveSelector)) {
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();
                if (onForkPrompt && (e.type === 'click' || e.type === 'keydown')) onForkPrompt();
            }
        };
        for (const el of els) {
            el.addEventListener('mousedown', intercept, true);
            el.addEventListener('click', intercept, true);
            el.addEventListener('keydown', intercept, true);
        }
        return () => {
            for (const el of els) {
                el.removeEventListener('mousedown', intercept, true);
                el.removeEventListener('click', intercept, true);
                el.removeEventListener('keydown', intercept, true);
            }
        };
    }, [onForkPrompt]);
    const resizeStateRef = useRef<{
        startX: number;
        startWidth: number;
        panel: 'input' | 'output';
    } | null>(null);
    const verticalResizeStateRef = useRef<{
        startY: number;
        startHeight: number;
    } | null>(null);

    // Get input nodes (nodes that connect to the selected node)
    const inputNodes = useMemo(() => {
        if (!selectedNode) return [];
        const incomingEdges = edges.filter(edge => edge.target === selectedNode.id);
        return incomingEdges.map(edge => {
            const sourceNode = nodes.find(n => n.id === edge.source);
            return sourceNode;
        }).filter(Boolean) as Node[];
    }, [selectedNode, nodes, edges]);

    // Get node metadata for display
    const nodeDefinition = useMemo(() => {
        return selectedNode?.type ? getNodeMetadata(selectedNode.type) : undefined;
    }, [selectedNode?.type]);

    // NodeConfig wants the nested config blob, not the whole data object.
    const nodeConfig = useMemo(() => {
        const data = selectedNode?.data as Record<string, any> | undefined;
        return (data?.config as Record<string, any>) || {};
    }, [selectedNode?.data]);
    const nodeOperation = useMemo(() => {
        const data = selectedNode?.data as Record<string, any> | undefined;
        return typeof data?.operation === 'string' ? data.operation : undefined;
    }, [selectedNode?.data]);
    const nodeCredentialIds = useMemo(() => {
        const data = selectedNode?.data as Record<string, any> | undefined;
        return (data?.credentialIds as Record<string, string>) || {};
    }, [selectedNode?.data]);

    // Detect if selected node is wired as a tool provider to an agent
    const toolProviderConsumerTypes = useMemo(
        () => (selectedNode ? getToolProviderConsumerTypes(selectedNode.id, nodes, edges) : []),
        [selectedNode, nodes, edges]
    );
    const agentToolProviderMode = toolProviderConsumerTypes.length > 0;

    // Auto-toggle panels based on availability
    useEffect(() => {
        if (selectedNode) {
            setShowInput(inputNodes.length > 0);
            setShowOutput(true);
        } else {
            setShowInput(false);
            setShowOutput(false);
        }
    }, [selectedNode, inputNodes.length]);

    // Horizontal resize handler
    const startResize = useCallback((e: React.MouseEvent, panel: 'input' | 'output') => {
        e.preventDefault();
        const startWidth = panel === 'input' ? inputPanelWidth : outputPanelWidth;
        resizeStateRef.current = { startX: e.clientX, startWidth, panel };

        const handleMouseMove = (e: MouseEvent) => {
            if (!resizeStateRef.current) return;
            const { startX, startWidth, panel } = resizeStateRef.current;
            const deltaX = panel === 'input' ? e.clientX - startX : startX - e.clientX;
            const newWidth = Math.max(200, Math.min(600, startWidth + deltaX));
            const ref = panel === 'input' ? inputPanelRef : outputPanelRef;
            if (ref.current) ref.current.style.width = `${newWidth}px`;
        };

        const handleMouseUp = (e: MouseEvent) => {
            if (resizeStateRef.current) {
                const { startX, startWidth, panel } = resizeStateRef.current;
                const deltaX = panel === 'input' ? e.clientX - startX : startX - e.clientX;
                const finalWidth = Math.max(200, Math.min(600, startWidth + deltaX));
                if (panel === 'input') setInputPanelWidth(finalWidth);
                else setOutputPanelWidth(finalWidth);
                resizeStateRef.current = null;
            }
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        };

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    }, [inputPanelWidth, outputPanelWidth]);

    // Vertical resize handler
    const startVerticalResize = useCallback((e: React.MouseEvent) => {
        e.preventDefault();

        let startHeight = height;
        if (isFullScreen) {
            const currentHeight = containerRef.current?.getBoundingClientRect().height ?? height;
            setIsFullScreen(false);
            onHeightChange(currentHeight);
            startHeight = currentHeight;
            if (containerRef.current) {
                containerRef.current.style.height = `${currentHeight}px`;
            }
        }

        verticalResizeStateRef.current = { startY: e.clientY, startHeight };

        const handleMouseMove = (e: MouseEvent) => {
            if (!verticalResizeStateRef.current) return;
            const { startY, startHeight } = verticalResizeStateRef.current;
            const deltaY = startY - e.clientY;
            const maxHeight = window.innerHeight * 0.9;
            const newHeight = Math.max(150, Math.min(maxHeight, startHeight + deltaY));
            if (containerRef.current) containerRef.current.style.height = `${newHeight}px`;
        };

        const handleMouseUp = (e: MouseEvent) => {
            if (verticalResizeStateRef.current) {
                const { startY, startHeight } = verticalResizeStateRef.current;
                const deltaY = startY - e.clientY;
                const maxHeight = window.innerHeight * 0.9;
                const finalHeight = Math.max(150, Math.min(maxHeight, startHeight + deltaY));
                onHeightChange(finalHeight);
                verticalResizeStateRef.current = null;
            }
            document.removeEventListener('mousemove', handleMouseMove);
            document.removeEventListener('mouseup', handleMouseUp);
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        };

        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', handleMouseUp);
        document.body.style.cursor = 'ns-resize';
        document.body.style.userSelect = 'none';
    }, [height, onHeightChange, containerRef, isFullScreen]);

    return (
        <div
            className="h-full flex flex-col rounded-2xl animate-slide-up overflow-hidden relative border border-border dark:border-zinc-700/40 bg-background dark:bg-[radial-gradient(circle_at_30%_30%,rgb(18,18,22),rgb(0,0,0))] shadow-[0_-8px_32px_rgba(0,0,0,0.12)] dark:shadow-[0_-8px_32px_rgba(0,0,0,0.5),0_0_0_1px_rgba(255,255,255,0.08)]"
            style={{
                contain: 'layout paint',
                transform: 'translateZ(0)',
            }}
        >
            {/* Vertical resize handle */}
            <VerticalResizeHandle onMouseDown={startVerticalResize} />

            {/* Background gradient mesh */}
            <div
                className="absolute inset-0 opacity-40 pointer-events-none"
                style={{ background: 'radial-gradient(circle at 70% 70%, rgba(120, 113, 108, 0.15), transparent 50%)' }}
            />

            {/* Glass overlay */}
            <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-white/[0.08] via-transparent to-transparent backdrop-blur-[2px] pointer-events-none" />

            {/* Inner soft glow */}
            <div className="absolute inset-[1px] rounded-2xl bg-gradient-radial from-white/[0.03] to-transparent opacity-70 pointer-events-none" />

            {/* Header */}
            <div className="flex items-center justify-between gap-3 px-3 py-3 border-b border-border dark:border-zinc-700/60 relative z-10 select-none">
                {/* Left: Input toggle */}
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => setShowInput(!showInput)}
                        disabled={!selectedNode || inputNodes.length === 0}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${
                            showInput
                                ? 'bg-foreground/[0.08] text-foreground border border-border dark:border-white/[0.1]'
                                : selectedNode && inputNodes.length > 0
                                ? 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.02] border border-transparent'
                                : 'text-muted-foreground/50 dark:text-zinc-700 cursor-not-allowed border border-transparent'
                        }`}
                        title={!selectedNode ? 'Select a node first' : inputNodes.length === 0 ? 'No input connections' : 'Toggle input panel'}
                    >
                        <ArrowDownToLine className="h-3.5 w-3.5" />
                        <span>Input</span>
                        {selectedNode && inputNodes.length > 0 && (
                            <span className="opacity-60">{inputNodes.length}</span>
                        )}
                    </button>
                </div>

                {/* Center: Tabs */}
                <div className="absolute left-1/2 -translate-x-1/2 flex items-center gap-1">
                    <button
                        onClick={() => onActiveTabChange('nodes')}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                            activeTab === 'nodes'
                                ? 'bg-foreground/[0.08] text-foreground'
                                : 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.02]'
                        }`}
                        title="Nodes"
                    >
                        <Boxes className="h-3.5 w-3.5" />
                        <span>Nodes</span>
                    </button>
                    <button
                        onClick={() => onActiveTabChange('config')}
                        disabled={!selectedNode}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                            activeTab === 'config'
                                ? 'bg-foreground/[0.08] text-foreground'
                                : selectedNode
                                ? 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.02]'
                                : 'text-muted-foreground/50 dark:text-zinc-700 cursor-not-allowed'
                        }`}
                        title="Config"
                    >
                        <Settings className="h-3.5 w-3.5" />
                        <span>Config</span>
                        {selectedNode && nodeDefinition && (
                            <div className="flex items-center gap-1.5 ml-1 pl-2 border-l border-border dark:border-zinc-600/50">
                                <BrandIcon Icon={nodeDefinition.Icon} iconColor={nodeDefinition.iconColor} className="w-3 h-3" />
                                <span className="text-muted-foreground">{nodeDefinition.label}</span>
                            </div>
                        )}
                    </button>
                    <button
                        onClick={() => onActiveTabChange('credentials')}
                        disabled={!selectedNode}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                            activeTab === 'credentials'
                                ? 'bg-foreground/[0.08] text-foreground'
                                : selectedNode
                                ? 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.02]'
                                : 'text-muted-foreground/50 dark:text-zinc-700 cursor-not-allowed'
                        }`}
                        title="Credentials"
                    >
                        <Key className="h-3.5 w-3.5" />
                        <span>Credentials</span>
                    </button>
                </div>

                {/* Right: Output toggle + controls */}
                <div className="flex items-center gap-2 ml-auto">
                    <button
                        onClick={() => setShowOutput(!showOutput)}
                        disabled={!selectedNode}
                        className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium ${
                            showOutput
                                ? 'bg-foreground/[0.08] text-foreground border border-border dark:border-white/[0.1]'
                                : selectedNode
                                ? 'text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-foreground/[0.02] border border-transparent'
                                : 'text-muted-foreground/50 dark:text-zinc-700 cursor-not-allowed border border-transparent'
                        }`}
                        title={!selectedNode ? 'Select a node first' : 'Toggle output panel'}
                    >
                        <ArrowUpFromLine className="h-3.5 w-3.5" />
                        <span>Output</span>
                    </button>

                    {/* Full screen toggle */}
                    <button
                        onClick={() => setIsFullScreen(!isFullScreen)}
                        className="h-7 w-7 rounded-full text-muted-foreground dark:text-zinc-500 hover:text-foreground hover:bg-foreground/[0.1] transition-all flex items-center justify-center flex-shrink-0"
                        title={isFullScreen ? 'Exit full screen' : 'Enter full screen'}
                    >
                        {isFullScreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                    </button>

                    {/* Close button */}
                    <button
                        onClick={onClose}
                        className="h-7 w-7 rounded-full text-muted-foreground dark:text-zinc-500 hover:text-foreground hover:bg-foreground/[0.1] transition-all flex items-center justify-center flex-shrink-0"
                    >
                        <X className="h-3.5 w-3.5" />
                    </button>
                </div>
            </div>

            {/* Content - Three-column layout */}
            <div className="flex-1 relative z-10 flex overflow-hidden">
                {/* Input Panel */}
                {showInput && (
                    <div
                        ref={inputPanelRef}
                        className="relative border-r border-border/50 dark:border-zinc-800/50"
                        style={{ width: `${inputPanelWidth}px` }}
                    >
                        <div className="h-full overflow-y-auto scrollbar-subtle py-3 pl-4 pr-3 mr-[3px]">
                            <InputPanel inputNodes={inputNodes} />
                        </div>
                        <ResizeHandle position="right" onMouseDown={(e) => startResize(e, 'input')} />
                    </div>
                )}

                {/* Main Content */}
                <div className="flex-1 overflow-y-auto scrollbar-subtle py-3 px-6">
                    {activeTab === 'nodes' && (
                        // Tile clicks dispatch `noclick:add-connected-node`;
                        // ReadOnlyFlowCanvas routes that to the fork prompt.
                        <NodesTabContent
                            searchQuery=""
                        />
                    )}

                    {activeTab === 'config' && (
                        selectedNode ? (
                            <div className="space-y-4">
                                {/* Node Type Header */}
                                <div className="flex items-center gap-3">
                                    {nodeDefinition && (
                                        <BrandIcon Icon={nodeDefinition.Icon} iconColor={nodeDefinition.iconColor} className="w-5 h-5" />
                                    )}
                                    <div>
                                        <div className="text-sm text-foreground font-medium">
                                            {nodeDefinition?.label || selectedNode.type || 'Node'}
                                        </div>
                                        <div className="text-[10px] text-muted-foreground dark:text-zinc-500 font-mono">
                                            {selectedNode.id}
                                        </div>
                                    </div>
                                </div>

                                {/* Tool-provider mode: show operation allowlist instead of config form */}
                                {agentToolProviderMode ? (
                                    <AgentToolOperationsPicker
                                        key={selectedNode.id}
                                        nodeType={selectedNode.type || 'default'}
                                        consumerTypes={toolProviderConsumerTypes}
                                        selectedOperations={
                                            Array.isArray(nodeConfig.agent_tool_operations)
                                                ? (nodeConfig.agent_tool_operations as string[])
                                                : []
                                        }
                                        onChange={() => {}}
                                        sandboxMounts={
                                            Array.isArray(nodeConfig.agent_sandbox_repos)
                                                ? (nodeConfig.agent_sandbox_repos as { repo?: string; branch?: string }[]).map(m => ({
                                                      repo: typeof m?.repo === 'string' ? m.repo : '',
                                                      branch: typeof m?.branch === 'string' ? m.branch : '',
                                                  }))
                                                : []
                                        }
                                        onSandboxMountsChange={() => {}}
                                        mountCredentialId={Object.entries(nodeCredentialIds).find(([k]) => k !== 'credential_type')?.[1]}
                                        credentialsMissing={providerCredentialsMissing(
                                            selectedNode.type || '',
                                            nodeCredentialIds,
                                            selectedNode.data as Record<string, any>,
                                        )}
                                        onConnectCredentials={() => {}}
                                    />
                                ) : (
                                    <>
                                        {/* Intercept any mutative interaction
                                            (button click, input edit, dropdown
                                            open) and route to the fork prompt
                                            instead of letting it run inert. */}
                                        <div ref={configCageRef} className="select-text">
                                            <NodeConfig
                                                nodeType={selectedNode.type || 'default'}
                                                config={nodeConfig}
                                                operation={nodeOperation}
                                                credentialIds={nodeCredentialIds}
                                                onChange={() => {}}
                                            />
                                        </div>
                                    </>
                                )}
                            </div>
                        ) : (
                            <div className="flex items-center justify-center h-full">
                                <div className="text-center text-muted-foreground dark:text-zinc-500 text-sm">
                                    Click on a node to view its configuration
                                </div>
                            </div>
                        )
                    )}

                    {activeTab === 'credentials' && (
                        // Same cage as Config: NodeCredentials renders OAuth
                        // "Connect" buttons that open popups even with a no-op
                        // onChange, so we block clicks at the DOM-capture layer.
                        <div ref={credentialsCageRef} className="select-text">
                            <CredentialsTabContent
                                selectedNode={selectedNode}
                                nodeConfig={nodeConfig}
                                rawCredentialIds={nodeCredentialIds}
                                onCredentialChange={() => {}}
                            />
                        </div>
                    )}
                </div>

                {/* Output Panel */}
                {showOutput && (
                    <div
                        ref={outputPanelRef}
                        className="relative border-l border-border/50 dark:border-zinc-800/50"
                        style={{ width: `${outputPanelWidth}px` }}
                    >
                        <ResizeHandle position="left" onMouseDown={(e) => startResize(e, 'output')} />
                        <div className="h-full overflow-y-auto scrollbar-subtle py-3 px-4">
                            <OutputPanel selectedNode={selectedNode} />
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
