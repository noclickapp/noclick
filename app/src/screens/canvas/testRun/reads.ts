// What a workflow's Test Run screen reads from whoever renders it (the `canvas.testRun` slot, ../slots.ts): the
// situations the workflow can stage, a run of one with its steps as they come, where the workflow's own test runs are
// kept, what still stands between the workflow and running for real, sharing a finished run, and what the screen
// remembers while the page lives. The standard is the platform API's (standards.tsx).
import type { ComponentType } from 'react';
import type { NoClick } from 'noclick';
import type { UnmetConnection } from '../readiness';
import type { RehearsalAuthoring } from './authoring';
import type { Scenario, TriggerFixture } from './scenarios';
import type { LiveRunState } from './liveRows';
import type { ReplayState } from './useReplay';

/** The triggers a workflow can stage a test run on, each with the situations offered for it. */
export interface StagedSituations {
    loading: boolean;
    triggers: TriggerFixture[];
    /** Why they couldn't be listed. */
    error: string | null;
}

/** The situation a run plays. */
export interface PickedRun {
    /** The offered situation it stages (a run the workflow added rides on the one it was copied from). */
    key: string;
    /** The run's own name among the workflow's test runs: an offered situation's key, or an added run's slug. */
    slug: string;
    /** A run the workflow added: its whole message is its own. */
    custom: boolean;
    /** The staged message as the screen shows it, where that differs from the offered one: the workflow's edits, or an
        added run's whole message. */
    patch?: Record<string, string>;
}

/** A test run asked for from elsewhere (the builder, after authoring one): which to open on, started once. */
export interface TestRunRequest {
    /** Trigger step TYPE (e.g. 'automation-telegram'): the staged list's slug. */
    trigger?: string;
    /** A situation's slug under that trigger (an offered key or an added run's slug). */
    run?: string;
}

export interface ShareRunProps {
    workflowId: string;
    /** The scenario as displayed (the run's own outcome text already folded in). */
    scenario: Scenario;
    run: ReplayState;
}

export interface TestRunHost {
    /** What the workflow can stage; nothing is read for null (the bench's canned runs). */
    useScenarios(workflowId: string | null): StagedSituations;
    /** A run of the picked situation: idle until started, then its steps and how it ended. */
    useRun(workflowId: string | null, picked: PickedRun): LiveRunState;
    /** Whether a run plays the test runs the workflow holds (so the screen's changes to them are written first),
        rather than the message the run is handed. */
    runsSaved: boolean;
    /** Where the workflow's own test runs, names, edits and removals are kept: read once, written as they change;
        through `client` (the one the screen was drawn with) where they're the API's. */
    authoring: {
        read(workflowId: string, client: NoClick | null): Promise<Partial<RehearsalAuthoring> | null>;
        write(workflowId: string, authoring: RehearsalAuthoring, client: NoClick | null): Promise<void>;
    };
    /** The connections the workflow still needs before what a test shows can happen for real. */
    useUnmet(workflowId: string | null): UnmetConnection[];
    /** Under a finished run: sharing it. null where runs aren't shared. */
    Share: ComponentType<ShareRunProps> | null;
    /** What the screen remembers while the page lives, by key: the trigger and situation selected (`trigger-<id>`,
        `mock-<id>`) and a start asked for from elsewhere (`autorun-<id>`, a `TestRunRequest`). */
    useKept<T>(key: string, initial: T): [T, (value: T) => void];
}
