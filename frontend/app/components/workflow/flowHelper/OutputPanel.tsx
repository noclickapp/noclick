import { useEffect, useRef, useState } from 'react';
import { Node } from '@xyflow/react';
import {
    Check,
    ChevronDown,
    Pin,
    Save,
    Share2,
    Trash2,
    X,
} from 'lucide-react';
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { UpgradePopup } from '~/components/utils/UpgradePopup';
import { useNodeOutputHistory, resolveDisplayOutput } from '~/hooks/useNodeOutputHistory';
import { useNodeOutputSchema } from '~/hooks/useNodeOutputSchema';
import { useSavedOutputs } from '~/hooks/useSavedOutputs';
import type { SavedOutputInfo } from '~/types/socket-events.generated';
import { IODataDisplay } from '../IODataDisplay';
import { getDisplayStrategy, type JsonValue } from '../nodes/nodeRegistry';
import { HistoryCarousel } from './HistoryCarousel';
import { getNodeOperation } from './utils';

// Output panel showing the selected node's output.
// Uses custom OutputDisplay components from node registry when available.
// Note: Output is NOT draggable — you can't reference a node's output in its own config.
interface OutputPanelProps {
    selectedNode: Node | null;
    onMockToggle?: (nodeId: string, isMocked: boolean, output: unknown) => void;
    workflowId?: string;
    initialHistoryIndex?: number;
    onHistoryIndexChange?: (nodeId: string, historyIndex: number, output: unknown | undefined) => void;
}

export const OutputPanel = ({
    selectedNode,
    onMockToggle,
    workflowId,
    initialHistoryIndex,
    onHistoryIndexChange,
}: OutputPanelProps) => {
    const nodeType = selectedNode?.type || '';
    const nodeConfig = selectedNode?.data || {};
    const nodeOperation = getNodeOperation(nodeConfig);

    const { savedOutputs, create, remove, planLimitError, clearPlanLimitError } = useSavedOutputs({
        nodeType,
        autoFetch: !!nodeType,
    });

    // Fetch expected schema + curated suggested refs (cache-keyed by
    // node type+operation; cache hits skip the network round trip).
    const {
        schema: expectedSchema,
        suggestedRefs,
        isLoading: isLoadingSchema,
    } = useNodeOutputSchema({
        nodeType: nodeType || undefined,
        // Triggers (and other operation-less nodes) record their output schema under the
        // 'default' operation key (see track_node_schema), so fetch with that fallback —
        // otherwise the curated fields view never loads for a node without an operation.
        nodeOperation: nodeOperation || 'default',
        enabled: !!nodeType,
    });

    // Save form state
    const [showSaveForm, setShowSaveForm] = useState(false);
    const [saveName, setSaveName] = useState('');
    const [isSaving, setIsSaving] = useState(false);

    // Dropdown state
    const [showDropdown, setShowDropdown] = useState(false);
    const dropdownRef = useRef<HTMLDivElement>(null);

    // Share dialog state
    const [shareSavedOutput, setShareSavedOutput] = useState<{ id: string; name: string } | null>(null);

    // Output history carousel
    const { historyEntries, historyIndex, setHistoryIndex } = useNodeOutputHistory({
        workflowId,
        nodeId: selectedNode?.id,
        refetchTrigger: selectedNode?.data?.output,
        initialHistoryIndex,
        onIndexChange: onHistoryIndexChange,
    });

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as HTMLElement)) {
                setShowDropdown(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    if (!selectedNode) {
        return (
            <div className="flex items-center justify-center h-full text-muted-foreground dark:text-zinc-500 text-sm">
                No node selected
            </div>
        );
    }

    const { displayOutput, isMocked, hasDisplayOutput } = resolveDisplayOutput({
        mockedOutput: selectedNode.data?.mockedOutput,
        liveOutput: selectedNode.data?.output,
        historyEntries,
        historyIndex,
    });

    // Live in-flight progress from a running node (streaming agent text and/or
    // one-shot self.emit({...}) snapshots). Lives in node.data.progress,
    // separate from the canonical node.data.output — see
    // WorkflowNodeProgressEvent for why. When either text or snapshot is
    // present during 'running', the panel renders progress instead of the
    // stale prior-run canonical; the moment the new canonical lands it
    // clears node.data.progress and we fall back to the normal rendering.
    const progressSlot =
        selectedNode.data?.executionState === 'running'
            ? (selectedNode.data?.progress as { text?: string; snapshot?: unknown } | undefined)
            : undefined;
    const progressText =
        typeof progressSlot?.text === 'string' && progressSlot.text.length > 0
            ? progressSlot.text
            : null;
    const progressSnapshot =
        progressSlot?.snapshot !== undefined && progressSlot.snapshot !== null
            ? progressSlot.snapshot
            : null;
    const hasLiveProgress = progressText !== null || progressSnapshot !== null;

    const handleMockToggle = () => {
        if (onMockToggle) {
            if (isMocked) {
                // Clear mock: remove mocked output
                onMockToggle(selectedNode.id, false, undefined);
            } else if (hasDisplayOutput) {
                // Set mock: pin currently displayed output (live or historical)
                onMockToggle(selectedNode.id, true, displayOutput);
            }
        }
    };

    const handleSaveOutput = async () => {
        if (!saveName.trim() || !hasDisplayOutput) return;

        setIsSaving(true);
        const result = await create(saveName.trim(), displayOutput);
        setIsSaving(false);

        if (result) {
            setShowSaveForm(false);
            setSaveName('');
        }
    };

    const handleSelectSavedOutput = (saved: SavedOutputInfo) => {
        if (onMockToggle) {
            onMockToggle(selectedNode.id, true, saved.output);
        }
        setShowDropdown(false);
    };

    const handleDeleteSavedOutput = async (e: React.MouseEvent, id: string) => {
        e.stopPropagation();
        await remove(id);
    };

    // Live progress takes over the panel — render the structured snapshot
    // (if any) and the accumulating text (if any), hide everything else.
    // As soon as the canonical output lands, node.data.progress is cleared
    // and this branch falls through to the normal rendering below.
    if (hasLiveProgress) {
        return (
            <div className="space-y-2">
                <div className="flex items-center gap-2">
                    <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                        Output
                    </div>
                    <div className="text-[10px] text-blue-600 dark:text-blue-400 animate-pulse">
                        Live…
                    </div>
                </div>
                {progressSnapshot !== null && (
                    <pre className="text-xs text-foreground/80 font-mono whitespace-pre-wrap break-words bg-card dark:bg-muted/50 border border-border dark:border-border/50 rounded-lg p-3 max-h-[40vh] overflow-y-auto">
                        {JSON.stringify(progressSnapshot, null, 2)}
                    </pre>
                )}
                {progressText !== null && (
                    <pre className="text-xs text-foreground/80 font-mono whitespace-pre-wrap break-words bg-card dark:bg-muted/50 border border-border dark:border-border/50 rounded-lg p-3 max-h-[60vh] overflow-y-auto">
                        {progressText}
                    </pre>
                )}
            </div>
        );
    }

    // Get display strategy early so we can skip the empty state for nodes with custom output panels
    const OutputPanelContent = getDisplayStrategy(selectedNode.type).OutputPanelContent;

    // Show empty state only when there's no output, no mocked data, no saved outputs, no expected schema,
    // and no custom OutputPanelContent (which can derive display from node config even without output)
    if (!hasDisplayOutput && savedOutputs.length === 0 && !expectedSchema && !isLoadingSchema && !OutputPanelContent) {
        return (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground dark:text-zinc-500 text-sm gap-2">
                <span>No output yet</span>
                <span className="text-[10px] text-muted-foreground/70 dark:text-zinc-600">Run the node or load saved mock data</span>
            </div>
        );
    }

    // Show expected schema when no output but schema is available.
    // Skip if the node has a custom OutputPanelContent (it handles the no-output case itself).
    if (!hasDisplayOutput && savedOutputs.length === 0 && (expectedSchema || isLoadingSchema) && !OutputPanelContent) {
        return (
            <div className="space-y-3">
                <div className="flex items-center gap-2">
                    <div className="text-[11px] text-muted-foreground dark:text-zinc-500 uppercase tracking-wider">
                        Expected Output
                    </div>
                </div>
                {isLoadingSchema ? (
                    <div className="text-xs text-muted-foreground dark:text-zinc-500">Loading schema...</div>
                ) : (
                    <IODataDisplay
                        data={expectedSchema}
                        label=""
                        nodeId={selectedNode.id}
                        draggable={false}
                        isSchema={true}
                        suggestedRefs={suggestedRefs}
                    />
                )}
            </div>
        );
    }

    // Find the name of the currently selected mock data (if any)
    const nodeMockedOutput = selectedNode.data?.mockedOutput;
    const selectedMockName = isMocked && nodeMockedOutput
        ? savedOutputs.find((s) => JSON.stringify(s.output) === JSON.stringify(nodeMockedOutput))?.name
        : null;

    // Header with mock data button and save button
    const headerContent = (
        <div className="space-y-1.5 mb-2">
            {/* Row 1: Title and action buttons */}
            <div className="flex items-center justify-between">
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
                <div className="flex items-center gap-1.5">
                    {/* Save Output Button */}
                    <button
                        onClick={() => setShowSaveForm(!showSaveForm)}
                        disabled={!hasDisplayOutput}
                        className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-medium transition-all ${
                            hasDisplayOutput
                                ? 'bg-card dark:bg-foreground/[0.02] text-muted-foreground hover:text-foreground hover:bg-muted dark:hover:bg-foreground/[0.05] border border-border/50 dark:border-white/[0.05]'
                                : 'text-muted-foreground/50 dark:text-zinc-700 cursor-not-allowed border border-transparent'
                        }`}
                        title="Save this output for later use"
                    >
                        <Save className="h-3 w-3" />
                        Save
                    </button>

                    {/* Use as Mock / Clear Mock Button */}
                    <button
                        onClick={handleMockToggle}
                        disabled={!hasDisplayOutput && !isMocked}
                        className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-medium transition-all ${
                            isMocked
                                ? 'bg-secondary dark:bg-zinc-600/30 text-foreground/80 hover:bg-accent dark:hover:bg-zinc-600/50 border border-border dark:border-zinc-500/40'
                                : hasDisplayOutput
                                ? 'bg-card dark:bg-foreground/[0.02] text-muted-foreground hover:text-foreground hover:bg-muted dark:hover:bg-foreground/[0.05] border border-border/50 dark:border-white/[0.05]'
                                : 'text-muted-foreground/50 dark:text-zinc-700 cursor-not-allowed border border-transparent'
                        }`}
                        title={isMocked ? 'Clear mock data and use live output' : 'Use this output as mock data'}
                    >
                        {isMocked ? (
                            <>
                                <X className="h-3 w-3" />
                                Clear Mock
                            </>
                        ) : (
                            <>
                                <Pin className="h-3 w-3" />
                                Mock
                            </>
                        )}
                    </button>
                </div>
            </div>

            {/* Save Form (compact inline) - appears above dropdown */}
            {showSaveForm && (
                <div className="flex items-center gap-2">
                    <input
                        type="text"
                        placeholder="Name..."
                        value={saveName}
                        onChange={(e) => setSaveName(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter' && saveName.trim()) handleSaveOutput();
                            if (e.key === 'Escape') { setShowSaveForm(false); setSaveName(''); }
                        }}
                        className="flex-1 px-2.5 py-1.5 bg-background dark:bg-zinc-800/50 border border-input dark:border-zinc-700/50 rounded-md text-xs text-foreground placeholder:text-[hsl(var(--placeholder))] focus:outline-none focus:border-muted-foreground/50 dark:focus:border-zinc-600"
                        autoFocus
                    />
                    <button
                        onClick={handleSaveOutput}
                        disabled={!saveName.trim() || isSaving}
                        className={`flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[10px] font-medium transition-all ${
                            saveName.trim() && !isSaving
                                ? 'bg-foreground/10 text-foreground hover:bg-foreground/15'
                                : 'text-muted-foreground/70 dark:text-zinc-600 cursor-not-allowed'
                        }`}
                    >
                        <Check className="h-3 w-3" />
                    </button>
                    <button
                        onClick={() => { setShowSaveForm(false); setSaveName(''); }}
                        className="p-1.5 rounded-md text-muted-foreground dark:text-zinc-500 hover:text-foreground/80 hover:bg-accent dark:hover:bg-zinc-700/30 transition-colors"
                    >
                        <X className="h-3 w-3" />
                    </button>
                </div>
            )}

            {/* Saved outputs dropdown (only if there are saved outputs) */}
            {savedOutputs.length > 0 && (
                <div ref={dropdownRef} className="relative">
                    <button
                        onClick={() => setShowDropdown(!showDropdown)}
                        className="w-full flex items-center justify-between gap-2 px-3 py-2 rounded-md bg-muted dark:bg-zinc-800/40 border border-border dark:border-zinc-700/40 hover:border-muted-foreground/40 dark:hover:border-zinc-600/50 text-xs transition-colors"
                    >
                        <span className={`truncate ${selectedMockName ? 'text-foreground' : 'text-muted-foreground dark:text-zinc-500'}`}>
                            {selectedMockName || 'Load from saved outputs...'}
                        </span>
                        <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground dark:text-zinc-500 flex-shrink-0 transition-transform ${showDropdown ? 'rotate-180' : ''}`} />
                    </button>

                    {showDropdown && (
                        <div className="absolute top-full left-0 right-0 mt-1 bg-card border border-border dark:border-zinc-700/50 rounded-md shadow-xl z-50 max-h-48 overflow-y-auto">
                            {savedOutputs.map((saved) => (
                                <div
                                    key={saved.id}
                                    onClick={() => handleSelectSavedOutput(saved)}
                                    className={`flex items-center justify-between gap-2 px-3 py-2 hover:bg-accent dark:hover:bg-zinc-800/50 cursor-pointer group ${
                                        selectedMockName === saved.name ? 'bg-muted dark:bg-zinc-800/40' : ''
                                    }`}
                                >
                                    <span className="text-xs text-foreground/80 truncate">{saved.name}</span>
                                    <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-all">
                                        <button
                                            onClick={(e) => { e.stopPropagation(); setShareSavedOutput({ id: saved.id, name: saved.name }); }}
                                            className="p-1 hover:bg-blue-500/20 rounded transition-all"
                                            title="Share saved output"
                                        >
                                            <Share2 className="h-3 w-3 text-blue-600 dark:text-blue-400" />
                                        </button>
                                        <button
                                            onClick={(e) => handleDeleteSavedOutput(e, saved.id)}
                                            className="p-1 hover:bg-red-500/20 rounded transition-all"
                                            title="Delete saved output"
                                        >
                                            <Trash2 className="h-3 w-3 text-red-600 dark:text-red-400" />
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {!isMocked && (
                <HistoryCarousel
                    historyEntries={historyEntries}
                    historyIndex={historyIndex}
                    setHistoryIndex={setHistoryIndex}
                    size="md"
                />
            )}
        </div>
    );

    // Default: use IODataDisplay for nodes without custom output display.
    // Not draggable — can't reference a node's own output in its config.
    const nodeData = selectedNode.data as Record<string, unknown> | undefined;

    return (
        <div className="space-y-4">
            {headerContent}

            {/* For nodes with custom panel content: show it prominently.
                Render even without output — the component can derive display from nodeData
                (e.g., form fields from config) */}
            {OutputPanelContent && (
                <OutputPanelContent
                    nodeId={selectedNode.id}
                    output={(displayOutput ?? null) as JsonValue}
                    draggable={false}
                    nodeData={nodeData}
                />
            )}

            {/* Show raw output data (collapsed for custom display since custom content is shown above) */}
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
                        suggestedRefs={suggestedRefs}
                    />
                </details>
            )}

            {/* Share Dialog for Saved Outputs */}
            <ShareDialog
                isOpen={!!shareSavedOutput}
                onOpenChange={(open) => !open && setShareSavedOutput(null)}
                resource={shareSavedOutput}
                resourceType="saved_output"
            />

            <UpgradePopup
                isOpen={!!planLimitError}
                onOpenChange={(open) => { if (!open) clearPlanLimitError(); }}
                errorMessage={planLimitError || ''}
            />
        </div>
    );
};
