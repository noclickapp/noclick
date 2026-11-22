// The panel of the step selected on the canvas: its settings form and its accounts, each change handed to the canvas,
// which saves it as the edit it is. A viewer's panel shows the step and changes nothing.
import { useMemo, useState } from 'react';
import type { Edge, Node } from '@xyflow/react';
import { X } from 'lucide-react';
import { NodeConfig } from '@/screens/canvas/form/NodeConfig';
import { NodeCredentials } from '@/screens/canvas/form/NodeCredentials';
import { getDefaultLabelFromType } from '@/screens/canvas/nodes/NodeLabel';
import { StepContext } from '@/screens/canvas/form/reads';
import { ReferenceAutocompleteProvider } from '@/screens/canvas/form/ReferenceAutocompleteContext';
import { ReferenceHoverProvider } from '@/screens/canvas/form/ReferenceHoverContext';
import { TAP_AREA } from '@/ui/buttons';
import { cn } from '@/ui/utils';

export interface StepPanelProps {
    workflowId: string;
    /** The step open. */
    node: Node;
    nodes: Node[];
    edges: Edge[];
    /** Nothing here changes the step. */
    readOnly: boolean;
    /** What `{{vars.x}}` resolves to, and writing one from a field bound to it. */
    variables: Record<string, any>;
    onVariableValueChange?: (name: string, value: string) => void;
    /** Changes the step, as the canvas takes it: its settings (`config`), `operation` or `credentialIds`. */
    onChange: (nodeId: string, change: Record<string, unknown>) => void;
    onClose: () => void;
}

/** The steps whose output reaches `nodeId`: every one upstream of it along the workflow's connections (a step wired to
 *  an agent as its tools feeds it nothing). */
export function stepsBefore(nodeId: string, nodes: readonly Node[], edges: readonly Edge[]): Node[] {
    const before = new Set<string>();
    const frontier = [nodeId];
    while (frontier.length) {
        const at = frontier.pop()!;
        for (const edge of edges) {
            if (edge.target !== at || edge.targetHandle === 'bottom' || before.has(edge.source) || edge.source === nodeId) continue;
            before.add(edge.source);
            frontier.push(edge.source);
        }
    }
    return nodes.filter((node) => before.has(node.id));
}

type Tab = 'settings' | 'accounts';

export function StepPanel({ workflowId, node, nodes, edges, readOnly, variables, onVariableValueChange, onChange, onClose }: StepPanelProps) {
    const [tab, setTab] = useState<Tab>('settings');
    const data = (node.data ?? {}) as { label?: string; operation?: string; config?: Record<string, any>; credentialIds?: Record<string, string>; withheld?: string[] };
    const config = data.config ?? {};
    const credentialIds = data.credentialIds ?? {};
    const upstream = useMemo(() => stepsBefore(node.id, nodes, edges), [node.id, nodes, edges]);
    // The canvas saves what the panel changes (its graph's own edits): the form saves nothing itself.
    const scope = useMemo(() => ({ workflowId, nodeId: node.id, hostSaves: true }), [workflowId, node.id]);

    return (
        // Under the canvas's own buttons (adding a step, running), which stay in reach while a step is open.
        <aside aria-label="Step" data-testid="step-panel" className="absolute bottom-0 right-0 top-[68px] z-30 flex w-[400px] max-w-full flex-col rounded-tl-2xl border-l border-t border-border bg-background shadow-xl">
            <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
                <h2 className="min-w-0 flex-1 truncate text-[14px] font-semibold text-foreground">{data.label || getDefaultLabelFromType(node.type as string)}</h2>
                <button type="button" aria-label="Close the step" onClick={onClose} className={cn('relative grid h-8 w-8 place-items-center rounded-full text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground', TAP_AREA)}>
                    <X className="h-4 w-4" />
                </button>
            </header>
            <div role="tablist" aria-label="The step’s parts" className="flex shrink-0 gap-1 border-b border-border px-3 py-1.5">
                {(['settings', 'accounts'] as const).map((id) => (
                    <button
                        key={id}
                        type="button"
                        role="tab"
                        aria-selected={tab === id}
                        onClick={() => setTab(id)}
                        className={cn('rounded-full px-3 py-1 text-[13px] font-medium transition-colors', tab === id ? 'bg-accent text-foreground' : 'text-muted-foreground hover:text-foreground')}
                    >
                        {id === 'settings' ? 'Settings' : 'Account'}
                    </button>
                ))}
            </div>
            {readOnly && <p className="shrink-0 border-b border-border px-4 py-2 text-[12.5px] text-muted-foreground">You can look at this step. Changing it takes edit access to the workflow.</p>}
            {/* A viewer's fields take no input: the form draws as it stands. */}
            <fieldset disabled={readOnly} className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4">
                <StepContext.Provider value={scope}>
                    {tab === 'accounts' ? (
                        <NodeCredentials
                            key={node.id}
                            nodeType={node.type as string}
                            nodeData={{ operation: data.operation, config }}
                            credentialIds={credentialIds}
                            onChange={(ids) => onChange(node.id, { credentialIds: ids })}
                        />
                    ) : (
                        <ReferenceHoverProvider>
                            <ReferenceAutocompleteProvider inputNodes={upstream} workflowVariables={variables}>
                                <NodeConfig
                                    key={node.id}
                                    nodeType={node.type as string}
                                    nodeId={node.id}
                                    workflowId={workflowId}
                                    config={config}
                                    operation={data.operation}
                                    credentialIds={credentialIds}
                                    withheld={data.withheld}
                                    onChange={(next) => onChange(node.id, { config: next })}
                                    onOperationChange={(operation) => onChange(node.id, { operation })}
                                    onSwitchToCredentials={() => setTab('accounts')}
                                    workflowVariables={variables}
                                    onVariableValueChange={onVariableValueChange}
                                />
                            </ReferenceAutocompleteProvider>
                        </ReferenceHoverProvider>
                    )}
                </StepContext.Provider>
            </fieldset>
        </aside>
    );
}
