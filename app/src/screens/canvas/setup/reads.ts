// What a workflow's Setup tab reads from whoever renders it (the `canvas.setup` slots, ../slots.ts): how each step
// stands (the lens its steps are derived through), proof that a chosen account works, the workflow's setup check, what
// the tab remembers while the page lives, asking the Test Run screen for a run, and the three parts only a host has in
// full: choosing which agent runs the workflow, connecting a coding agent to a workflow that serves its tools to one,
// and what covers the page on the way into Setup. The standards are the platform API's (standards.tsx).
import type { ComponentType } from 'react';
import type { Edge, Node } from '@xyflow/react';
import type { ConnectionCheck } from '@/lib/connectionCheck';
import type { BrandIconComponent } from '@/ui/BrandIcon';
import type { TestRunRequest } from '../testRun/reads';
import type { Mark as FrameMark } from '../testRun/variants';

/** One thing a step still needs. */
export interface StepIssue {
    type: 'missing_required_field' | 'missing_credentials' | 'missing_operation' | 'trigger_not_receiving';
    message: string;
    /** The setting it's about, where it's about one. */
    fieldKey?: string;
}

/** What the tab reads of a step type. */
export interface StepTypeFacts {
    /** The type's name as a person reads it ("Slack"). */
    label: string;
    Icon?: BrandIconComponent;
    iconColor?: string;
    /** A sentence on what the type is, which heads the step that connects its account. */
    description?: string;
}

/** How each step of a workflow stands, as the tab derives its steps: the same judgment the canvas marks a step
 *  incomplete by. */
export interface SetupLens {
    /** Whether everything it judges by has been read for the steps given: the tab opens once it has. */
    ready: boolean;
    /** What a step still needs, judged in the workflow around it (a tool wired to an agent needs its allowlist, not an
     *  action; an agent a trigger feeds needs no message). */
    issuesOf(node: Node): StepIssue[];
    typeOf(type: string): StepTypeFacts;
    /** A step's setting as its form draws it (its schema), by key; null where the step has no such setting. */
    fieldOf(node: Node, fieldKey: string): Record<string, any> | null;
    /** Whether a step of this type, doing this, starts runs on an event from outside. */
    isTriggerSource(type: string, operation: string | undefined): boolean;
}

/** The workflow's setup check, as the tab shows it: a line on how it stands, what's in the way, and what else it can
 *  say (each a line). */
export interface SetupReport {
    title: string;
    issues: string[];
    notes: string[];
}

export type SetupReportRead = { status: 'loading' } | { status: 'failed'; message: string } | { status: 'ready'; report: SetupReport };

export interface SetupHost {
    /** The lens over the workflow as the canvas holds it. */
    useLens(nodes: Node[], edges: Edge[]): SetupLens;
    /** Asks the provider to prove an account a step holds: its own things, who it signs in as, or its refusal. null
     *  where nothing could be judged. */
    useProbe(): (stepType: string, credentialId: string) => Promise<ConnectionCheck | null>;
    /** The workflow's setup check, read when the tab's last step draws and again when asked. */
    useReport(workflowId: string): { read: SetupReportRead; refresh: () => void };
    /** The marks the staged message's frame draws its apps with, by provider. */
    useIcons(): Record<string, FrameMark>;
    /** What the tab remembers while the page lives, by key (`pending-step-<workflow>`: a step to open on, asked for
     *  from elsewhere). */
    useKept<T>(key: string, initial: T): [T, (value: T) => void];
    /** Asks the Test Run screen to start a run once it's drawn (the one named, else the one it would pick), for the
     *  workflow the tab is on (undefined where the canvas hasn't one yet). */
    askForTestRun(workflowId: string | undefined, request?: TestRunRequest): Promise<void>;
    /** Beside the name of what's being set up. */
    Orb: ComponentType;
}

/** How the step that chooses the workflow's agent stands. */
export interface RuntimeStatus {
    /** The agent chosen needs an account of the person's own and has none. */
    unmet: boolean;
    /** A few words on what's chosen, or on what it needs. */
    detail: string;
}

export interface RuntimePhaseProps {
    /** The workflow's agent step. */
    node: Node;
    /** Writes the agent step's settings whole. */
    onConfigChange: (nodeId: string, config: Record<string, any>) => void;
    onCredentialIdsChange: (nodeId: string, credentialIds: Record<string, string>) => void;
}

/** Going on from the agent's step with no account connected. */
export interface WithoutAccount {
    /** The button's words. */
    label: string;
    /** What going on does, said beside it. */
    note: string;
    /** The settings that move the agent to where it needs no account, over its own. */
    settings(config: Record<string, unknown>): Record<string, unknown>;
}

/** The agent's step as the tab lists it, and the way on from it with no account (null where the step just goes on). */
export interface RuntimeStep extends RuntimeStatus {
    withoutAccount: WithoutAccount | null;
}

export interface SetupRuntime {
    /** How the step stands for the workflow's agent step (undefined: the workflow has no agent), read by the tab on
     *  every draw. A host that was told which agent to choose before the tab drew (a page that named one) writes it
     *  through `onConfigChange` as the tab opens. */
    useStep(workflowId: string | undefined, agent: Node | undefined, onConfigChange: RuntimePhaseProps['onConfigChange']): RuntimeStep;
    /** The step: which agent (a model NoClick runs, or a coding agent on the person's own account) runs the workflow. */
    Phase: ComponentType<RuntimePhaseProps>;
}

export interface McpConnectProps {
    workflowId: string;
    /** The step that serves the workflow's tools. */
    nodeId: string;
    nodeLabel?: string;
}
