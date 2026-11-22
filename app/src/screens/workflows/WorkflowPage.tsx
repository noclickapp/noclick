// One workflow's page: its canvas (the steps drawn, edited, run, with its run log and a run's results), the panel of
// the step selected on it, its Setup tab and its Test Run, over the platform API alone with the client its host hands
// it. The canvas stays drawn under the other two (it holds the workflow as read and saves each change as the edit it
// is), so a change made in Setup or a step's panel is the canvas's own. A key that may only look at the workflow gets
// the canvas read-only. The builder beside it is the frame's to draw (`builder`: the page only opens it).
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Eye, Sparkles } from 'lucide-react';
import { useSlot } from '@/slots';
import { StepContext } from '@/screens/canvas/form/reads';
import { SetupView } from '@/screens/canvas/setup/SetupView';
import { useSavedVariables, useWorkflowVariables, type WorkflowVariableDefinition } from '@/screens/canvas/setup/variables';
import { SETUP, SETUP_COVER } from '@/screens/canvas/slots';
import { TestRunScreen } from '@/screens/canvas/testRun/TestRunScreen';
import { WorkflowCanvas, type CanvasHandle } from '@/screens/canvas/WorkflowCanvas';
import { BUTTON_SECONDARY } from '@/ui/buttons';
import { cn } from '@/ui/utils';
import { StepPanel } from './StepPanel';

export type WorkflowTab = 'canvas' | 'setup' | 'test';

const TABS: readonly { id: WorkflowTab; label: string }[] = [
    { id: 'canvas', label: 'Canvas' },
    { id: 'setup', label: 'Setup' },
    { id: 'test', label: 'Test Run' },
];

export interface WorkflowPageProps {
    workflowId: string;
    /** The workflow's name, where the host has read it (the list it came from). */
    name?: string;
    /** The tab open; the canvas when none is named. */
    tab?: WorkflowTab;
    onTab: (tab: WorkflowTab) => void;
    /** Back to the list of workflows. */
    onBack: () => void;
    /** The builder beside the page, which the frame draws: whether it's open, and opening or closing it. Left out where
     *  the frame draws none. */
    builder?: { open: boolean; onOpenChange: (open: boolean) => void };
    /** Whether the page's client is a person's own: signed in to NoClick, or a key that names the
     *  `workflows:variables` scope. The page then reads the values of the workflow's variables, where that person owns
     *  the workflow or can edit it, and shows them in Setup and in a field bound to one. Left out (a page acting as one
     *  of the account's keys, as this app's own does: its key carries no such scope), it never asks, and a variable
     *  that has a value shows as saved and hidden. */
    asOwner?: boolean;
}

/** What draws over the canvas, with the canvas's own hold on the workflow. */
function OverCanvas({
    canvas,
    workflowId,
    tab,
    onTab,
    variables,
}: {
    canvas: CanvasHandle;
    workflowId: string;
    tab: WorkflowTab;
    onTab: (tab: WorkflowTab) => void;
    variables: { definitions: WorkflowVariableDefinition[]; persisted: Record<string, unknown>; change: (definitions: WorkflowVariableDefinition[]) => void };
}) {
    const icons = useSlot(SETUP).useIcons();
    const Cover = useSlot(SETUP_COVER);
    const resolved = useWorkflowVariables(canvas.nodes, variables.persisted, variables.definitions).resolved;
    const setVariable = useCallback(
        (name: string, value: string) => {
            const held = variables.definitions;
            variables.change(held.some((d) => d.name === name) ? held.map((d) => (d.name === name ? { ...d, value } : d)) : [...held, { name, value }]);
        },
        [variables]
    );
    // The canvas saves what Setup's own pickers choose (the workflow's edits): they save nothing themselves.
    const scope = useMemo(() => ({ workflowId, hostSaves: true }), [workflowId]);
    return (
        <>
            {tab === 'canvas' && canvas.selected && (
                <StepPanel
                    workflowId={workflowId}
                    node={canvas.selected}
                    nodes={canvas.nodes}
                    edges={canvas.edges}
                    readOnly={canvas.readOnly}
                    variables={resolved}
                    onVariableValueChange={canvas.readOnly ? undefined : setVariable}
                    onChange={canvas.updateStep}
                    onClose={() => canvas.select(null)}
                />
            )}
            {tab === 'setup' && (
                <div className="absolute inset-0 z-40 flex bg-background" data-testid="workflow-setup">
                    {canvas.loaded ? (
                        <fieldset disabled={canvas.readOnly} className="flex min-h-0 min-w-0 flex-1">
                            <StepContext.Provider value={scope}>
                                <SetupView
                                    nodes={canvas.nodes}
                                    edges={canvas.edges}
                                    workflowId={workflowId}
                                    onConfigChange={(nodeId, config) => canvas.updateStep(nodeId, { config })}
                                    onOperationChange={(nodeId, operation) => canvas.updateStep(nodeId, { operation })}
                                    onCredentialIdsChange={(nodeId, credentialIds) => canvas.updateStep(nodeId, { credentialIds })}
                                    onOpenTestRun={() => onTab('test')}
                                    variableDefinitions={variables.definitions}
                                    onVariableDefinitionsChange={canvas.readOnly ? undefined : variables.change}
                                />
                            </StepContext.Provider>
                        </fieldset>
                    ) : (
                        <Cover />
                    )}
                </div>
            )}
            {tab === 'test' && (
                <div className="absolute inset-0 z-40 overflow-y-auto bg-background" data-testid="workflow-test-run">
                    <TestRunScreen icons={icons} live={{ workflowId }} onClose={() => onTab('canvas')} />
                </div>
            )}
        </>
    );
}

export function WorkflowPage({ workflowId, name, tab = 'canvas', onTab, onBack, builder, asOwner = false }: WorkflowPageProps) {
    const variables = useSavedVariables(workflowId, { asOwner });
    const [readOnly, setReadOnly] = useState(false);
    // Another workflow starts as its own read says.
    useEffect(() => setReadOnly(false), [workflowId]);
    return (
        <div className="flex h-full min-h-0 flex-col" data-testid="workflow-page">
            <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-3">
                <button type="button" onClick={onBack} className="inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[13px] text-muted-foreground transition-colors hover:bg-foreground/[0.05] hover:text-foreground">
                    <ArrowLeft className="h-3.5 w-3.5" /> Automations
                </button>
                <h1 className="min-w-0 truncate text-[14px] font-semibold text-foreground">{name ?? 'Workflow'}</h1>
                {readOnly && (
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[11px] font-medium text-muted-foreground" data-testid="workflow-view-only">
                        <Eye className="h-3 w-3" /> View only
                    </span>
                )}
                <div role="tablist" aria-label="The workflow’s parts" className="ml-auto flex items-center gap-1">
                    {TABS.map((t) => (
                        <button
                            key={t.id}
                            type="button"
                            role="tab"
                            aria-selected={tab === t.id}
                            onClick={() => onTab(t.id)}
                            className={cn('rounded-full px-3 py-1 text-[13px] font-medium transition-colors', tab === t.id ? 'bg-accent text-foreground' : 'text-muted-foreground hover:text-foreground')}
                        >
                            {t.label}
                        </button>
                    ))}
                </div>
                {builder && !readOnly && (
                    <button type="button" className={BUTTON_SECONDARY} aria-pressed={builder.open} onClick={() => builder.onOpenChange(!builder.open)}>
                        <Sparkles className="h-4 w-4" /> Build
                    </button>
                )}
            </header>
            {variables.error && (
                <p role="alert" className="shrink-0 border-b border-border px-4 py-2 text-[13px] text-red-600 dark:text-red-400">
                    {variables.error}
                </p>
            )}
            <div className="relative min-h-0 flex-1">
                <WorkflowCanvas workflowId={workflowId} name={name} onAccess={setReadOnly}>
                    {(canvas) => <OverCanvas canvas={canvas} workflowId={workflowId} tab={tab} onTab={onTab} variables={variables} />}
                </WorkflowCanvas>
            </div>
        </div>
    );
}
