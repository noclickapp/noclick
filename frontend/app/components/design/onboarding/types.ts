/* Client-safe shapes for the onboarding design routes. Kept separate from
   steps.server.ts (which imports the heavy node registry) so the variant
   components can reference these without pulling a server-only module into the
   client bundle — same split as nodeCatalogTypes.ts / nodeCatalog.server.ts. */

export interface ResolvedTool {
    value: string;
    name: string;
    description: string;
    /** Provider scope this operation needs, from the backend scope registry.
        Null where the provider has no verified scope table yet. */
    requiredScope: string | null;
    /** The schema's own x-category ("Message", "Channel", …), used to say what
        areas an overflowed allowlist covers. */
    category: string;
}

/** Outcome of testing a credential against the provider.
    `partial` is the one that matters: the token is valid but is missing a scope
    one of the allowlisted operations needs, so the agent authenticates fine and
    then fails mid-run. */
export type TestOutcome = 'untested' | 'working' | 'partial' | 'failed';

export interface CredentialStep {
    kind: 'credential';
    id: string;
    /** Node label straight from the registry ("Slack", "Gmail"). */
    label: string;
    iconHtml: string;
    iconColor: string;
    why: string;
    /** Humanized credential class, e.g. "Gmail OAuth". */
    credentialLabel: string | null;
    accountName?: string;
    connected: boolean;
    /** What this credential lets the agent do — real allowlisted operations. */
    tools: ResolvedTool[];
    /** Scopes the credential was actually granted, where the provider records them. */
    grantedScopes: string[] | null;
    /** Real dynamic-options field. `error` means loading them genuinely failed. */
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
    /** What a test would return today, measured against the real credential. */
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
    /** Every credential on the account this node would accept. */
    options: { id: string; name: string; type: string; health: 'ok' | 'dead' | 'unknown' }[];
    /** How to add a new one, per accepted credential kind. */
    connectMethods: { type: string; label: string; kind: 'oauth' | 'token' }[];
    /** Which option is attached right now (null = none). */
    attachedId: string | null;
    /** What stops working, and what the failure looks like in practice. */
    consequence: { loss: string; failure: string };
}

/** Shape the real ModelPickerModal consumes (Model & { source }); described
    loosely here so the design route does not depend on the app's model enums. */
export interface ManagedModel {
    id: string;
    name: string;
    provider: string;
    source?: string;
    free?: boolean;
    capabilities?: string[];
    input_modalities?: string[];
    output_modalities?: string[];
    created?: number;
}

export interface HarnessOption {
    slug: string;
    name: string;
    vendor: string;
    tagline: string;
    strengths: string[];
    iconHtml: string;
    iconColor: string;
    /** True when iconHtml is a full wordmark (name baked into the art). */
    includesName: boolean;
    accentColor: string;
    /** SDK path runs on NoClick's key; harnesses always need the user's own. */
    requiresOwnAccount: boolean;
    requirement?: string;
    /** Only the sandbox harnesses get a shell. */
    hasShell: boolean;
    recommended?: boolean;
    /** Credential this runtime needs, and the account already holding one. */
    credentialType: string;
    connectedAs: string | null;
    /** Real id of the credential already attached, for pre-selection. */
    credentialId: string | null;
    /** The data.config.model value this harness writes — what AgentCredentialsForm
        resolves its provider from. */
    modelValue: string | null;
}
