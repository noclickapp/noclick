// What the canvas reads to show a workflow's runs and what each step did in them: a page of the run log and its
// counts, a step's stored outputs, and what a step of a type outputs before it has run. The shapes are the views' own;
// whoever renders the canvas answers them, through the `canvas.runs.reads` slot (declared in ../slots.ts): this app on
// /v1 (standards.tsx), NoClick's app on its own socket. Beside them, what only a host has: outputs saved under a name
// (`canvas.runs.saved`), what can be done about a failed step (`canvas.runs.fixes`) and a run's results drawn as a
// whole (`canvas.runs.results`).
import type { ComponentType, ReactNode } from 'react';
import type { JsonObject } from '../form/referenceTypes';
import type { ErrorAction } from './ErrorActionButton';
import type { ExecutionCounts, LogsFilters, WorkflowExecutionLog } from './RunLog';
import type { SuggestedRef } from './SuggestedRefsTab';

/** What the run log can be narrowed by, where the reads answer it. A narrowing the reads can't answer isn't offered:
 *  the log says so in its place. */
export interface RunLogNarrows {
    /** Runs waiting on an approval or a delay told apart from those running. */
    waiting: boolean;
    /** By how a run started. */
    source: boolean;
    /** By the text of a run's error. */
    search: boolean;
}

/** Every narrowing: what the log offers when nothing says otherwise. */
export const NARROWS_EVERYTHING: RunLogNarrows = { waiting: true, source: true, search: true };

/** A page of the run log: `cursor` is the last page's `next` (null for the first), whatever the reads made it. */
export interface RunLogQuery {
    limit: number;
    filters: LogsFilters;
    cursor: unknown | null;
}

export interface RunLogPage {
    logs: WorkflowExecutionLog[];
    /** What reads the page after this one; null on the last. */
    next: unknown | null;
}

/** One of a step's stored outputs: the run it's from, when it was stored and the output, whole. */
export interface OutputHistoryEntry {
    execution_id: string;
    created_at: string;
    output: unknown;
}

/** What a step of a type outputs, as runs have shown it: its shape (names and types, never values) and the fields
 *  worth offering first; `suggestedRefs` null while those aren't known yet. */
export interface OutputShape {
    schema: JsonObject | null;
    suggestedRefs: SuggestedRef[] | null;
}

export interface RunReads {
    narrows: RunLogNarrows;
    /** A page of the workflow's runs, newest first. */
    runs(workflowId: string, query: RunLogQuery): Promise<RunLogPage>;
    /** How many runs there are: in all, by status and by how they started. */
    counts(workflowId: string): Promise<ExecutionCounts>;
    /** A step's latest `limit` outputs, newest first. */
    history(workflowId: string, stepId: string, limit: number): Promise<OutputHistoryEntry[]>;
    /** What a step of `type` outputs for `operation`; null where nothing is known of it. */
    outputShape(type: string, operation: string): Promise<OutputShape | null>;
}

export interface RunReadsHost {
    /** The reads for the canvas around the component that asks. */
    useRunReads: () => RunReads;
}

/** An output saved under a name, to pin on a step as its mock. */
export interface SavedOutput {
    id: string;
    name: string;
    output: unknown;
}

export interface SavedOutputs {
    saved: SavedOutput[];
    /** Saves `output` under `name`, answering whether it was saved; null where nothing is saved under a name. */
    save: ((name: string, output: unknown) => Promise<boolean>) | null;
    remove: (id: string) => Promise<void>;
    /** Sharing a saved output with other people; null offers none. */
    share: ((saved: SavedOutput) => void) | null;
    /** The host's own dialogs (sharing one, a plan's limit), drawn with the panel. */
    dialogs: ReactNode;
}

export interface SavedOutputsHost {
    /** A step type's saved outputs, for the output panel of a step of it on the workflow `workflowId` (where they're
     *  read and saved; none while the panel names no workflow). */
    useSaved: (nodeType: string, workflowId?: string) => SavedOutputs;
}

/** What acting on a fix does: something done here, or a page opened in a new tab. */
export type FixAct = { onClick: () => void } | { href: string };

export interface RunFixes {
    /** Asks the builder beside the canvas about a failed step; null where none listens. */
    ask: ((message: string, nodeId: string) => void) | null;
    /** What each fix the API names for a failed step does here (adding funds, raising the spending cap, connecting the
     *  step's account again); null for one this host can't offer, which then isn't drawn. A fix that is a link
     *  (`open_url`) is always one. */
    useFix: () => (action: ErrorAction, nodeId: string) => FixAct | null;
}

export interface RunResultsProps {
    workflowId: string;
    /** The run shown; null while none is. */
    runId: string | null;
    /** The run as the log lists it, where the results were opened from its row: when it started and how long it took. */
    run?: WorkflowExecutionLog;
    onClose: () => void;
    /** Opens a step of the run on the canvas (its settings). */
    onOpenStep?: (stepId: string) => void;
}

export type RunResults = ComponentType<RunResultsProps>;
