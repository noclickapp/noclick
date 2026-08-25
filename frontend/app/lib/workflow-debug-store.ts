/**
 * Simple store for workflow debug state.
 * Allows the WorkflowLLMDrawer to access workflow context without props,
 * enabling it to be opened via the global drawer system.
 */

import type { GeneratedNode } from '~/components/workflow/workflowGeneratorMock';
import type { RecordedEvent } from '~/lib/recordedEvent';

interface WorkflowDebugState {
    /** Current generation ID for filtering LLM calls */
    generationId: string | null;
    /** All generated nodes */
    nodes: GeneratedNode[];
    /** Currently selected node ID */
    selectedNodeId: string | null;
    // ========== Replay/Debug State ==========
    /** Events recorded during the current/last generation */
    recordedEvents: RecordedEvent[];
    /** Whether event recording is active */
    isRecording: boolean;
    /** Replay function reference (set by WorkflowCreator) */
    replayEvents: ((events: RecordedEvent[], speedMultiplier?: number) => Promise<void>) | null;
    /** Stop replay function reference */
    stopReplay: (() => void) | null;
    /** Clear recorded events function reference */
    clearRecordedEvents: (() => void) | null;
}

type Listener = () => void;

class WorkflowDebugStore {
    private state: WorkflowDebugState = {
        generationId: null,
        nodes: [],
        selectedNodeId: null,
        recordedEvents: [],
        isRecording: false,
        replayEvents: null,
        stopReplay: null,
        clearRecordedEvents: null,
    };
    private listeners: Set<Listener> = new Set();

    getState(): WorkflowDebugState {
        return this.state;
    }

    setGenerationId(generationId: string | null) {
        this.state = { ...this.state, generationId };
        this.notify();
    }

    setNodes(nodes: GeneratedNode[]) {
        this.state = { ...this.state, nodes };
        this.notify();
    }

    setSelectedNodeId(selectedNodeId: string | null) {
        this.state = { ...this.state, selectedNodeId };
        this.notify();
    }

    /** Update multiple values at once */
    update(updates: Partial<WorkflowDebugState>) {
        this.state = { ...this.state, ...updates };
        this.notify();
    }

    /** Reset to initial state (preserves function references) */
    reset() {
        this.state = {
            generationId: null,
            nodes: [],
            selectedNodeId: null,
            recordedEvents: [],
            isRecording: false,
            // Preserve function references across resets
            replayEvents: this.state.replayEvents,
            stopReplay: this.state.stopReplay,
            clearRecordedEvents: this.state.clearRecordedEvents,
        };
        this.notify();
    }

    /** Set recorded events */
    setRecordedEvents(events: RecordedEvent[]) {
        this.state = { ...this.state, recordedEvents: events };
        this.notify();
    }

    /** Set recording state */
    setIsRecording(isRecording: boolean) {
        this.state = { ...this.state, isRecording };
        this.notify();
    }

    /** Set replay function references (called once by WorkflowCreator) */
    setReplayFunctions(
        replayEvents: (events: RecordedEvent[], speedMultiplier?: number) => Promise<void>,
        stopReplay: () => void,
        clearRecordedEvents: () => void
    ) {
        this.state = {
            ...this.state,
            replayEvents,
            stopReplay,
            clearRecordedEvents,
        };
        // Don't notify - these are stable references
    }

    subscribe(listener: Listener): () => void {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    private notify() {
        this.listeners.forEach(listener => listener());
    }
}

export const workflowDebugStore = new WorkflowDebugStore();
