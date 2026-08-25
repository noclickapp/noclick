/**
 * useWorkflowKeyboardShortcuts - Handles keyboard shortcuts for workflow canvas operations.
 *
 * Shortcuts:
 * - 'f' or 'F': Toggle the flow helper / config view (no selection needed)
 * - 'd' or 'D': Toggle disabled state on selected node
 * - 'm', 'M', 'p', or 'P': Toggle mock output on selected node (pin/mock current output)
 *
 * Only active when canvas tab is focused and user is not in an editable element.
 */

import { useEffect } from 'react';
import { Node } from '@xyflow/react';

interface UseWorkflowKeyboardShortcutsProps {
    nodes: Node[];
    activeTab: 'canvas' | 'logs' | 'interface' | 'setup' | 'resources';
    onNodeDataUpdate?: (nodeId: string, newData: Record<string, any>) => void;
    /** Toggle the flow helper / config view (bound to 'F'). */
    onToggleFlowHelper?: () => void;
    /** Open the flow helper to a specific tab (C=config, K=credentials, U=ux). */
    onOpenFlowHelperTab?: (tab: 'config' | 'credentials' | 'home') => void;
}

export const useWorkflowKeyboardShortcuts = ({
    nodes,
    activeTab,
    onNodeDataUpdate,
    onToggleFlowHelper,
    onOpenFlowHelperTab,
}: UseWorkflowKeyboardShortcutsProps): void => {
    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            // Only handle when canvas tab is active
            if (activeTab !== 'canvas') return;

            // Don't intercept if user is in an editable element
            const activeElement = document.activeElement;
            const isEditableElement = activeElement instanceof HTMLInputElement ||
                activeElement instanceof HTMLTextAreaElement ||
                activeElement?.getAttribute('contenteditable') === 'true';

            if (isEditableElement) return;

            // Bare-key shortcuts only — never hijack OS/browser combos. Without
            // this, Cmd/Ctrl+C matches the 'c' branch below and preventDefault()s
            // the keydown, which suppresses the browser's native `copy` event that
            // useWorkflowCopyPaste depends on (and the same for Cmd+D/F/etc).
            if (event.metaKey || event.ctrlKey || event.altKey) return;

            const key = event.key.toLowerCase();

            // 'f' toggles the flow helper view — works with or without a selection.
            if (key === 'f' && onToggleFlowHelper) {
                event.preventDefault();
                onToggleFlowHelper();
                return;
            }

            // C/K/U open the flow helper to a specific tab.
            if (onOpenFlowHelperTab && (key === 'c' || key === 'k' || key === 'u')) {
                event.preventDefault();
                onOpenFlowHelperTab(key === 'c' ? 'config' : key === 'k' ? 'credentials' : 'home');
                return;
            }

            // Get currently selected nodes (the remaining shortcuts act on them)
            const selectedNodes = nodes.filter(node => node.selected);
            if (selectedNodes.length === 0) return;

            // Handle 'd' for disable toggle
            if (key === 'd') {
                event.preventDefault();
                selectedNodes.forEach(node => {
                    if (onNodeDataUpdate) {
                        const isCurrentlyDisabled = node.data?.disabled || false;
                        onNodeDataUpdate(node.id, { disabled: !isCurrentlyDisabled });
                    }
                });
                return;
            }

            // Handle 'm' or 'p' for mock/pin toggle
            if (key === 'm' || key === 'p') {
                event.preventDefault();
                selectedNodes.forEach(node => {
                    if (onNodeDataUpdate) {
                        const mockedOutput = node.data?.mockedOutput;
                        const output = node.data?.output;
                        const isMocked = mockedOutput !== undefined;
                        const hasOutput = output !== undefined && output !== null;

                        if (isMocked) {
                            // Clear mock (null signals deletion)
                            onNodeDataUpdate(node.id, { mockedOutput: null });
                        } else if (hasOutput) {
                            // Set mock to current output
                            onNodeDataUpdate(node.id, { mockedOutput: output });
                        }
                        // If no output and not mocked, do nothing
                    }
                });
                return;
            }
        };

        window.addEventListener('keydown', handleKeyDown);

        return () => {
            window.removeEventListener('keydown', handleKeyDown);
        };
    }, [activeTab, nodes, onNodeDataUpdate, onToggleFlowHelper, onOpenFlowHelperTab]);
};
