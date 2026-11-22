// What the Setup tab's account step is told of the step whose account it connects.
import type { ReactNode } from 'react';

/** An operation the account lets the agent run. */
export interface ResolvedTool {
    value: string;
    name: string;
    description: string;
    /** The provider scope this operation needs; null where none is known. */
    requiredScope: string | null;
    /** The schema's own x-category ("Message", "Channel", …), used to say what
        areas an overflowed allowlist covers. */
    category: string;
}

/** Outcome of testing a credential against the provider.
    `partial` is the one that matters: the token is valid but is missing a scope
    one of the allowlisted operations needs, so the agent authenticates fine and
    then fails mid-run. */
export type TestOutcome = 'untested' | 'working' | 'partial' | 'failed' | 'unverified';

export interface CredentialStep {
    kind: 'credential';
    /** The step's type. */
    id: string;
    /** The step's name ("Slack", "Gmail"). */
    label: string;
    iconHtml: string;
    iconColor: string;
    /** In place of `iconHtml`: a ready glyph. */
    iconNode?: ReactNode;
    why: string;
    /** The kind of account, as people name it ("Gmail sign-in"). */
    credentialLabel: string | null;
    accountName?: string;
    connected: boolean;
    /** What this credential lets the agent do — real allowlisted operations. */
    tools: ResolvedTool[];
    /** Scopes the credential was actually granted, where the provider records them. */
    grantedScopes: string[] | null;
    /** A setting whose choices the account's own things answer. `error` means loading them genuinely failed. */
    rebind: {
        /** Config field this picker fills — compared against the evidence's
            answers_field to decide whether the proof can double as the answer. */
        name: string;
        label: string;
        options: { value: string; label: string }[];
        error?: string;
        /** Set when one value is correct for EVERY account, so the importer
            confirms rather than chooses. Absent = genuinely author-bound. */
        preset?: string;
        /** Statement form of `label`, used when confirming a preset. */
        presetLabel?: string;
    } | null;
    /** What a test would return today, where that's known before one runs. */
    expectedOutcome: TestOutcome;
    /** Verbatim provider error when the test fails. */
    testError?: string;
    /** Human evidence a passing test should show — specific, not "OK". */
    testEvidence?: string;
    /** The recognisable items the probe actually returned — the proof itself,
        so these lead the success state rather than a count. */
    evidenceSamples?: string[];
    /** The user's word for those items ("channels", "recent senders"). */
    evidenceNoun?: string;
    /** How many more than shown, when the account has more. */
    evidenceMore?: number;
    /** Operation values whose scope could not be confirmed. */
    unverifiedOps?: string[];
    /** Every credential on the account this step would accept. */
    options: { id: string; name: string; type: string; health: 'ok' | 'dead' | 'unknown' }[];
    /** How to add a new one, per accepted credential kind. */
    connectMethods: { type: string; label: string; kind: 'oauth' | 'token' }[];
    /** Which option is attached right now (null = none). */
    attachedId: string | null;
    /** What stops working, and what the failure looks like in practice. */
    consequence: { loss: string; failure: string };
}
