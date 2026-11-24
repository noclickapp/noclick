// What the step form reads beside a step's settings: a dropdown's options, a widget's value (a trigger's address, an
// alarm list), the server's verdict on the settings, an expression's preview, and clearing what a step keeps between
// runs. The shapes are the form's own (the fields it reads); whoever renders the form answers them, through the
// `canvas.step.reads` slot: this app on /v1 (slotStandards.tsx), and a host its own way.
import { createContext, useContext } from 'react';

/** One choice a dropdown lists: the value it stores, its label, and what the service says beside it (an icon, a
 *  count). */
export interface FieldOption {
    value: string;
    label: string;
    metadata?: Record<string, unknown> | null;
}

/** A page of a dropdown's choices: `field_name` is the loader's field, `context` the step's settings as the form holds
 *  them. */
export type StepOptionsRequest = {
    request_id?: string;
    node_type: string;
    /** The setting whose choices these are (its path in the step's settings). */
    field_key?: string;
    /** The field its loader is asked for (`x-dynamic-options.field_name`, else the setting's own name). */
    field_name: string;
    credential_id?: string | null;
    context?: Record<string, unknown> | null;
    workflow_id?: string | null;
    page_token?: string;
    search?: string;
};

export interface StepOptionsAnswer {
    success: boolean;
    options?: FieldOption[];
    next_page_token?: string | null;
    message?: string | null;
    error?: string;
}

/** A widget's value on a step, with the step's settings as the form holds them (`context`). */
export type StepValueRequest = {
    node_type: string;
    field_name: string;
    workflow_id: string;
    node_id: string;
    context?: Record<string, unknown>;
    credential_ids?: Record<string, string>;
};

/** `values` where the value fills several of the step's settings at once, else `value`. */
export interface StepValueAnswer {
    success: boolean;
    value?: unknown;
    values?: Record<string, unknown> | null;
    message?: string | null;
    error?: string;
}

export type StepValidateRequest = {
    node_type: string;
    config_data: Record<string, unknown>;
};

export interface StepValidateAnswer {
    valid: boolean;
    errors?: string[] | null;
    error?: string;
}

/** An expression evaluated against the outputs it references (`sample_outputs`, by step id). */
export type ExpressionPreviewRequest = {
    expression: string;
    sample_outputs: Record<string, unknown>;
    primary_input?: unknown;
    workflow_nodes: { id: string; data: { label?: unknown } }[];
};

export interface ExpressionPreviewAnswer {
    ok?: boolean;
    kind?: string;
    keys?: string[] | null;
    preview?: string;
    preview_tokens?: Array<{ t: string; v: string }>;
    error?: string;
}

export interface ClearStateAnswer {
    success: boolean;
    error?: string;
}

export interface StepReads {
    options(request: StepOptionsRequest): Promise<StepOptionsAnswer>;
    /** A loader's choices that are no setting of the stored step (the workflows a picker offers, another workflow's
     *  form fields): a host may read them another way than a setting's. */
    lookup(request: StepOptionsRequest): Promise<StepOptionsAnswer>;
    value(request: StepValueRequest): Promise<StepValueAnswer>;
    /** The server's verdict on a step's settings, or null where the host judges them only when they're saved. */
    validate: ((request: StepValidateRequest) => Promise<StepValidateAnswer>) | null;
    previewExpression(request: ExpressionPreviewRequest): Promise<ExpressionPreviewAnswer>;
    /** Clears what a step keeps between runs (an agent's conversations, a step's state). */
    clearState(workflowId: string | undefined, nodeId: string): Promise<ClearStateAnswer>;
    /** Reconnects a trigger's development webhook relay, where the host runs one; null elsewhere. */
    reconnectWebhookRelay: (() => Promise<{ success: boolean; message?: string }>) | null;
}

/** The step whose form this is, for reads that address it: provided by the form around its fields, so a widget's read
 *  names its workflow and step. */
export interface StepScope {
    workflowId?: string;
    nodeId?: string;
    /** Whoever draws the form saves what it's told of the step (a canvas, whose graph's own edits carry the step's
     *  accounts): the form's pickers then save nothing themselves. */
    hostSaves?: boolean;
}

export const StepContext = createContext<StepScope | null>(null);

/** The step the form around this component is for, or null outside one. */
export function useStepScope(): StepScope | null {
    return useContext(StepContext);
}
