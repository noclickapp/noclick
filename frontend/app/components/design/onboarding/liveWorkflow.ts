/* A deterministic, synthetic "Inbound Lead Response Agent" fixture. It keeps
   the production graph shape and both healthy/rejected credential states while
   using only example identities and identifiers.

   The fixture is static because /design is unauthenticated and must never load
   account data. Update it alongside the onboarding UI when its expected states
   change. */

const FIXTURE_IDS = {
    workflow: '9662c9a8-9b27-5dd2-b476-9fa4f6195008',
    gmailNode: 'automation-gmail-fixture-trigger',
    agentNode: 'agent-fixture-lead-response',
    slackNode: 'automation-slack-fixture-tool',
    gmailCredential: 'a1244b02-a26d-5202-8d7f-6aa446744256',
    slackCredentialPrimary: '689d3672-cb57-50d2-b908-68c0660f23b7',
    slackCredentialSecondary: 'a2fc0a2a-264a-5b63-ac70-e6b2971ec8cb',
    slackCredentialTertiary: 'a80e001b-eaad-54a2-9c2e-525f189b3bf9',
    schedule: 'c66dbe39-9935-5257-8486-e1c1b2b87229',
    claudeCredential: 'eae3e672-624e-55a6-9fd9-77bd1e54e504',
    codexCredential: '78ce7604-0327-5ecc-bf76-2a5a7d72aca5',
    opencodeCredential: 'ebe5eb33-03bb-5af0-8d04-a31724358a61',
    openrouterCredential: 'e57d36e1-3e05-596d-95da-07add9d4ab29',
} as const;

export const LIVE_WORKFLOW = {
    id: FIXTURE_IDS.workflow,
    name: 'Inbound Lead Response Agent',
    capturedAt: '2000-01-01',
};

export interface LiveNode {
    nodeId: string;
    type: string;
    label: string;
    /** Saved operation const, null for the agent node. */
    operation: string | null;
    /** config.agent_tool_operations — the representative allowlist. */
    allow: string[];
    credential: {
        id: string;
        name: string;
        type: string;
        /** Credential state represented by the fixture. */
        health: 'ok' | 'dead';
        /** Representative provider error when health is dead. */
        error?: string;
        /** Representative granted scopes for the fixture. */
        grantedScopes?: string[] | null;
        /** Supporting line under the samples — names the account. */
        testEvidence?: string;
        /** Recognisable sample items used to demonstrate connection evidence. */
        evidenceSamples?: string[];
        /** The user's word for those items. */
        evidenceNoun?: string;
    } | null;
    /** Representative dynamic-options field and result.
        `null` means the node asks nothing — the strongest outcome,
        and the common one once hidden fields and provider-wired tools are
        accounted for. */
    dynamicField: {
        name: string;
        label: string;
        /** Populated for a healthy sample credential. */
        options: { value: string; label: string }[];
        /** Set when one value is correct for EVERY account, so importing needs
            no decision. Absent means account-bound: the saved value points at
            a resource only that account has (such as #sales), and the
            importer must re-point it. */
        preset?: string;
        /** Statement form of `label`, for when a preset is being confirmed
            rather than chosen ("Watching" vs "Watch which mailbox labels"). */
        presetLabel?: string;
        /** Populated when loading them failed. */
        error?: string;
    } | null;
}

/** The fixture workflow the rehearsal executes. Exported rather than duplicated
    so the metadata above and the run below cannot point at different graphs. */
export const LIVE_WORKFLOW_ID = FIXTURE_IDS.workflow;

export const LIVE_NODES: LiveNode[] = [
    {
        nodeId: FIXTURE_IDS.gmailNode,
        type: 'automation-gmail',
        label: 'New Lead Email',
        operation: 'poll_for_new_emails',
        allow: [],
        credential: {
            id: FIXTURE_IDS.gmailCredential,
            name: 'demo.mailbox@example.com',
            type: 'google_gmail_oauth',
            health: 'ok',
            // Example scopes demonstrate the UI without copying account data.
            grantedScopes: [
                'demo.mail.read',
                'demo.mail.send',
                'demo.mail.organize',
            ],
            // Senders, not labels: every Gmail account has the same standard
            // labels, so listing them would demonstrate little.
            testEvidence: 'Connected as demo.mailbox@example.com.',
            evidenceNoun: 'recent senders',
            evidenceSamples: ['Example CRM Notifications', 'Example Website'],
        },
        // No resource question. The trigger's label_ids is ui:hidden, and the
        // fixture node carries an empty config — the product never asks which
        // labels to watch, so neither does this.
        dynamicField: null,
    },
    {
        nodeId: FIXTURE_IDS.slackNode,
        type: 'automation-slack',
        label: 'Slack',
        operation: null,
        allow: ['send_message_to_channel', 'list_channels_in_workspace'],
        credential: {
            id: FIXTURE_IDS.slackCredentialPrimary,
            name: 'Demo Slack token A',
            type: 'slack_bot_token',
            // Bot-token credentials record no scopes, so a capability check has
            // nothing to compare against — only a live call can judge them.
            grantedScopes: null,
            // The rejected state lets the design exercise reconnection.
            health: 'dead',
            error: 'Slack API error: invalid_auth',
        },
        // Provider-wired (operation is null, tools hang off the bottom handle),
        // so the agent names the channel per tool call. There is no config
        // channel to attach, and asking for one would be inventing a question.
        dynamicField: null,
    },
];

/** The agent node's representative saved config. */
export const LIVE_AGENT = {
    nodeId: FIXTURE_IDS.agentNode,
    label: 'Lead Response Agent',
    model: 'openrouter/openai/gpt-4o-mini',
    message:
        'A new inbound email just arrived. Read it, work out who the lead is and what they want, then post a short briefing to Slack: who they are, what they are asking for, and what you would do next. Keep it to a few lines.',
    /** agent_credential_requirement(config).required for this model. */
    credentialRequired: false,
    /** A validation false-positive state represented by the fixture. */
    validateSaysMissing: true,
};

/** Representative trigger registration in the saved Gmail-node shape. */
export const LIVE_TRIGGER = {
    registered: true,
    intervalMs: 300000,
    nextRun: '2000-01-01T00:05:00.000Z',
    scheduleId: FIXTURE_IDS.schedule,
};

/** Public scope contract for each allowlisted operation, from backend/nodes/scopes/*.py.
    Gmail has no verified scope table yet (it sits in the _UNVERIFIED allowlist),
    so its operations resolve to null and a test can only prove auth. */
export const OPERATION_SCOPES: Record<string, string | null> = {
    send_message_to_channel: 'chat:write',
    list_channels_in_workspace: 'channels:read',
    poll_for_new_emails: null,
};

/** The runtimes offered at the end of setup. modelType/slug match
    data/harness-content; the SDK entry is the credential-free platform path. */
export const RUNTIME_CHOICES = [
    {
        slug: 'sdk',
        requiresOwnAccount: false,
        hasShell: false,
        recommended: true,
    },
    {
        slug: 'claude-code',
        requiresOwnAccount: true,
        hasShell: true,
        requirement: 'Your Anthropic account or API key',
    },
    {
        slug: 'codex',
        requiresOwnAccount: true,
        hasShell: true,
        requirement: 'Your ChatGPT account or OpenAI key',
    },
    {
        slug: 'opencode',
        requiresOwnAccount: true,
        hasShell: true,
        requirement: 'Your OpenCode API key',
    },
    {
        slug: 'openclaw',
        requiresOwnAccount: true,
        hasShell: true,
        requirement: 'Your OpenRouter key',
    },
    {
        slug: 'hermes',
        requiresOwnAccount: true,
        hasShell: true,
        requirement: 'Your OpenRouter key',
    },
] as const;

/** The staged lead, mirroring backend/nodes/agent/rehearsal_scenarios.py. The
    rehearsal runs against this synthetic world, so the two must not drift. */
export const DRY_RUN_INPUT = {
    from: 'Casey Example <casey@example-manufacturing.example>',
    subject: 'Routing purchase-order approvals into Slack',
    receivedAgo: 'staged for this run',
    body: "I'm Casey, Operations Manager at Example Manufacturing. My team reviews purchase-order requests in a shared inbox. I'd like new requests to land in Slack with an approval link. Is that something you support, and roughly what does it cost for a team of about twelve?",
};

/** The fixture workflow in the saved/wire shape ReactFlow renders. The
    canvas-first variant draws the representative graph with production node
    components rather than a lookalike.
    targetHandle "bottom" is the load-bearing tool-provider signal. */
export const LIVE_BLOB = {
    nodes: [
        {
            id: FIXTURE_IDS.gmailNode,
            type: 'automation-gmail',
            position: { x: 265, y: 162.5 },
            config: {
                label: 'New Lead Email',
                operation: 'poll_for_new_emails',
                trigger_registered: true,
                credentialIds: {
                    google_gmail_oauth: FIXTURE_IDS.gmailCredential,
                },
            },
        },
        {
            id: FIXTURE_IDS.agentNode,
            type: 'agent',
            position: { x: 535, y: 137.5 },
            config: {
                label: 'Lead Response Agent',
                model: 'openrouter/openai/gpt-4o-mini',
                message:
                    'A new inbound email just arrived. Read it, work out who the lead is and what they want, then post a short briefing to Slack.',
            },
        },
        {
            id: FIXTURE_IDS.slackNode,
            type: 'automation-slack',
            position: { x: 590, y: 457.5 },
            config: {
                label: 'Slack',
                agent_tool_operations: [
                    'send_message_to_channel',
                    'list_channels_in_workspace',
                ],
                credentialIds: {
                    slack_bot_token: FIXTURE_IDS.slackCredentialPrimary,
                },
            },
        },
    ],
    edges: [
        {
            id: `e_${FIXTURE_IDS.gmailNode}_${FIXTURE_IDS.agentNode}`,
            source: FIXTURE_IDS.gmailNode,
            target: FIXTURE_IDS.agentNode,
            sourceHandle: null,
            targetHandle: null,
        },
        {
            id: `e_${FIXTURE_IDS.slackNode}_${FIXTURE_IDS.agentNode}`,
            source: FIXTURE_IDS.slackNode,
            target: FIXTURE_IDS.agentNode,
            sourceHandle: 'top',
            targetHandle: 'bottom',
        },
    ],
};

export const AGENT_NODE_ID = FIXTURE_IDS.agentNode;

/** Which fixture node the canvas should spotlight for each phase. */
export const PHASE_NODE_ID: Record<string, string> = {
    'automation-gmail': FIXTURE_IDS.gmailNode,
    'automation-slack': FIXTURE_IDS.slackNode,
    runtime: FIXTURE_IDS.agentNode,
    dryrun: FIXTURE_IDS.agentNode,
    chat: FIXTURE_IDS.agentNode,
};

/** Representative credential options that each node would accept in the picker.
    Slack accepts
    two kinds (SlackOAuthCredential | SlackBotTokenCredential) — the picker has
    to offer both, and an "add another" path per kind. */
export interface CredentialOption {
    id: string;
    name: string;
    type: string;
    /** Credential state represented by the fixture. */
    health: 'ok' | 'dead' | 'unknown';
}

export const CREDENTIAL_OPTIONS: Record<string, CredentialOption[]> = {
    'automation-gmail': [
        {
            id: FIXTURE_IDS.gmailCredential,
            name: 'demo.mailbox@example.com',
            type: 'google_gmail_oauth',
            health: 'ok',
        },
    ],
    // Three sample rejected credentials exercise picker and reconnect states.
    'automation-slack': [
        {
            id: FIXTURE_IDS.slackCredentialPrimary,
            name: 'Demo Slack token A',
            type: 'slack_bot_token',
            health: 'dead',
        },
        {
            id: FIXTURE_IDS.slackCredentialSecondary,
            name: 'Demo Slack token B',
            type: 'slack_bot_token',
            health: 'dead',
        },
        {
            id: FIXTURE_IDS.slackCredentialTertiary,
            name: 'Demo Slack token C',
            type: 'slack_bot_token',
            health: 'dead',
        },
    ],
};

/** The ways a node can gain a NEW credential, per accepted kind. */
export const CONNECT_METHODS: Record<
    string,
    { type: string; label: string; kind: 'oauth' | 'token' }[]
> = {
    'automation-gmail': [
        {
            type: 'google_gmail_oauth',
            label: 'Sign in with Google',
            kind: 'oauth',
        },
    ],
    'automation-slack': [
        { type: 'slack_oauth', label: 'Sign in with Slack', kind: 'oauth' },
        { type: 'slack_bot_token', label: 'Paste a bot token', kind: 'token' },
    ],
};

/** What breaks if a credential is skipped, in two parts: what stops working,
    and what the failure actually looks like when it happens. People do not act
    on "not connected" — they act on "every run will finish having delivered
    nothing". */
export const SKIP_CONSEQUENCE: Record<
    string,
    { loss: string; failure: string }
> = {
    'automation-gmail': {
        loss: 'nothing will wake your agent',
        failure:
            'It will never run on its own. Leads can email you all day and the workflow stays idle — you would have to trigger every run by hand.',
    },
    'automation-slack': {
        loss: 'your agent can read leads but cannot tell anyone',
        failure:
            'Every run will look successful and deliver nothing. The agent researches the lead, writes the briefing, then fails on the final post — so you find out by noticing #sales is empty.',
    },
};

/** Representative credential for each runtime. Present is not the same as
    working — the same caveat as every other credential here. */
export const RUNTIME_CREDENTIALS: Record<
    string,
    { type: string; connectedAs: string | null; credentialId: string | null }
> = {
    sdk: { type: '', connectedAs: null, credentialId: null },
    'claude-code': {
        type: 'agent_claude_code_oauth',
        connectedAs: 'Anthropic (Claude Code)',
        credentialId: FIXTURE_IDS.claudeCredential,
    },
    codex: {
        type: 'agent_codex_oauth',
        connectedAs: 'ChatGPT (Codex)',
        credentialId: FIXTURE_IDS.codexCredential,
    },
    opencode: {
        type: 'agent_opencode',
        connectedAs: 'OpenCode (demo)',
        credentialId: FIXTURE_IDS.opencodeCredential,
    },
    // openclaw/hermes run on openrouter sub-models, so they resolve to the
    // openrouter key rather than a wrapper-specific credential.
    openclaw: {
        type: 'agent_openrouter',
        connectedAs: 'OpenRouter (demo)',
        credentialId: FIXTURE_IDS.openrouterCredential,
    },
    hermes: {
        type: 'agent_openrouter',
        connectedAs: 'OpenRouter (demo)',
        credentialId: FIXTURE_IDS.openrouterCredential,
    },
};
