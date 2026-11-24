// The Automations page's slots: the places in it a host may fill (src/slots.ts), each with what stands there otherwise.
import type { ComponentType } from 'react';
import { slot } from '@/slots';
import { ForkStandard, NoPlanNotice, OpenOnItsPage, RefusalStandard, type ForkDialogProps, type PlanNoticeProps, type RefusalProps, type ShareDialogProps, type WorkflowCanvasProps } from './browser/slotStandards';

/** Where an open workflow is drawn, in place of the page's grid. The standard opens the workflow's own page. */
export const CANVAS = slot<ComponentType<WorkflowCanvasProps>>('workflows.canvas', OpenOnItsPage);

/** Sharing a workflow or a folder with people, copying one into a workspace, and leaving one shared with you. The
 *  standard shares nothing (no Share action shows), copies a workflow by name through the platform API, and says
 *  leaving is done on NoClick. */
export interface Sharing {
    ShareDialog: ComponentType<ShareDialogProps> | null;
    ForkDialog: ComponentType<ForkDialogProps>;
    /** Drops your own access to something shared with you; `removed` false when it's shared with your whole workspace.
     *  Null: not offered. */
    leave: ((resourceType: 'workflow' | 'workflow_folder', resourceId: string) => Promise<{ removed: boolean }>) | null;
}
export const SHARING = slot<Sharing>('workflows.sharing', { ShareDialog: null, ForkDialog: ForkStandard, leave: null });

/** The account's plan where it limits automations: the line above the grid when its limit hides some shared with you,
 *  and what a refusal for a limit shows. The standard says so in plain words. */
export interface PlanLimits {
    Notice: ComponentType<PlanNoticeProps>;
    Refusal: ComponentType<RefusalProps>;
    /** Whether a refusal's words are a plan's limit (the page shows `Refusal` for it). */
    isLimit: (message: string) => boolean;
}
export const PLAN_LIMITS = slot<PlanLimits>('workflows.planLimits', {
    Notice: NoPlanNotice,
    Refusal: RefusalStandard,
    isLimit: (message) => message.startsWith('Plan limit reached:'),
});

/** What the page does once it's showing with something handed to it from elsewhere (a link someone opened, a page
 *  that sent them here): its handles. */
export interface Arrival {
    scopeId: string;
    folderId: string | null;
    /** Makes a blank workflow and opens it. */
    createBlank: () => void;
    /** Opens a workflow just made, adding it to the page. */
    openNew: (workflow: { id: string; name: string; description: string }) => void;
    /** Opens a workflow by its id. */
    open: (workflowId: string) => void;
    /** While something is being made, the page waits. */
    setMaking: (making: boolean) => void;
    /** A refusal to show (a plan's limit). */
    refused: (message: string) => void;
    /** Shows what you own, where the page shows only what's shared with you. */
    showOwned: () => void;
    refreshShared: () => void;
}
/** A hook the page calls with its handles. The standard does nothing. */
export const ARRIVALS = slot<(arrival: Arrival) => void>('workflows.arrivals', () => undefined);
