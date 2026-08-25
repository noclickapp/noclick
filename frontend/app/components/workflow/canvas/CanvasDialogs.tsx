import type { Node } from '@xyflow/react';
import { Confetti } from '~/components/ui/Confetti';
import { ShareDialog } from '~/components/shared/popups/ShareDialog';
import { WorkflowSettingsDialog } from '../WorkflowSettingsDialog';
import { MobileErrorBanner } from './MobileCanvasChrome';

interface CanvasDialogsProps {
    // Workflow identity
    workflowId?: string;
    workflowTitle?: string;
    nodes: Node[];

    // Share dialog
    isShareDialogOpen: boolean;
    onShareDialogChange: (open: boolean) => void;

    // Settings dialog
    isSettingsDialogOpen: boolean;
    onSettingsDialogChange: (open: boolean) => void;
    workflowSettings: Record<string, unknown>;
    onWorkflowSettingsChange: (settings: Record<string, unknown>) => void;
    settingsInitialSection?: 'general' | 'variables';

    // Confetti celebration
    confettiTrigger: number;

    // Mobile error queue
    isMobile: boolean;
    mobileErrors: Array<{ id: string; title: string; description: string }>;
}

// All top-level dialogs + confetti for the canvas, grouped
// so the main FlowCanvas render stays focused on the canvas itself. Each
// dialog has its own open/close state kept by the parent — this component
// is purely presentational glue.
export function CanvasDialogs({
    workflowId,
    workflowTitle,
    nodes,
    isShareDialogOpen,
    onShareDialogChange,
    isSettingsDialogOpen,
    onSettingsDialogChange,
    workflowSettings,
    onWorkflowSettingsChange,
    settingsInitialSection,
    confettiTrigger,
    isMobile,
    mobileErrors,
}: CanvasDialogsProps) {
    return (
        <>
            <ShareDialog
                isOpen={isShareDialogOpen}
                onOpenChange={onShareDialogChange}
                resource={workflowId && workflowTitle ? { id: workflowId, name: workflowTitle } : null}
                resourceType="workflow"
            />

            {workflowId && (
                <WorkflowSettingsDialog
                    isOpen={isSettingsDialogOpen}
                    onOpenChange={onSettingsDialogChange}
                    workflowId={workflowId}
                    currentSettings={workflowSettings}
                    onSettingsChange={onWorkflowSettingsChange}
                    nodes={nodes}
                    initialSection={settingsInitialSection}
                />
            )}


            {/* Fires on first-workflow-created welcome experience */}
            <Confetti
                trigger={confettiTrigger}
                particleCount={150}
                spread={45}
                angle={225}
                velocity={{ min: 20, max: 32 }}
                origin={{ x: 0.9, y: 0.85 }}
                duration={4000}
            />

            {isMobile && <MobileErrorBanner errors={mobileErrors} />}
        </>
    );
}
