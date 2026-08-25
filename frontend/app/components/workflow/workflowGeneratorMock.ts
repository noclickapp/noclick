/**
 * Mock workflow generator for AI-powered workflow creation.
 * Contains mock workflow templates and a simulated generator that will be
 * replaced with real backend API calls. Abstracted to enable easy swapping.
 */

// ============================================================================
// Types
// ============================================================================

/** Represents a node being generated in the workflow */
export interface GeneratedNode {
    id: string;
    type: string;
    label: string;
    description?: string;
    level: number;
    index: number;
    parentIds: string[];
    status: 'adding' | 'editing' | 'complete' | 'needs_input' | 'error';
    content: string;
    icon?: string;
    color?: string;
    // Custom generation fields (node drafter + 3)
    operation?: string;
    operationReason?: string;
    config?: Record<string, any>;
    userFields?: string[];
    error?: string;
    // Original position from template (preserved during fork/load)
    position?: { x: number; y: number };
    // Original dimensions from template (preserved for sticky notes)
    width?: number;
    height?: number;
}

/** Represents an edge connecting two nodes */
export interface GeneratedEdge {
    id: string;
    sourceId: string;
    targetId: string;
    sourceHandle?: string;  // For multi-output nodes (e.g., iteration: 'loop' or 'done')
    status: 'animating' | 'complete';
}

/** Represents a credential or input request from the AI */
export interface InputRequest {
    id: string;
    nodeId: string;
    type: 'credential' | 'selection' | 'text' | 'config' | 'env';
    label: string;
    description: string;
    options?: { id: string; label: string; icon?: string }[];
    /** Multi-select (type === 'selection'): render checkboxes and submit the
     *  chosen options comma-joined. From <ask multiple="true">. */
    multiple?: boolean;
    /** Sandbox env-var names the builder requested (type === 'env'). camelCase,
     *  as emitted by the backend ask parser. */
    envKeys?: { name: string; description?: string }[];
    /** Provider name (e.g., 'github', 'google', 'slack') used for OAuth flow */
    credentialType?: string;
    /** Specific credential types accepted (e.g., ['github_oauth', 'github_pat']) - if provided, used for filtering */
    acceptedCredentialTypes?: string[];
    required: boolean;
    /** Selected credential ID (set when user selects a credential) */
    value?: string;

    // Config field properties (for type: 'config')
    /** Node type for loading dynamic options (e.g., 'automation-google-sheets') */
    nodeType?: string;
    /** Field key in the node's config schema (e.g., 'spreadsheet_id', 'sheet_name') */
    fieldKey?: string;
    /** JSON Schema for the field (from node's schema) */
    fieldSchema?: Record<string, any>;
    /** Field this config depends on (e.g., 'sheet_name' depends on 'spreadsheet_id') */
    dependsOn?: string;
    /** Credential types required to load options for this field */
    requiredCredentialTypes?: string[];
    /** Snapshot of the node's credentialIds at ask emission — used by DynamicOptionsField to load options */
    credentialIds?: Record<string, string>;
    /** Snapshot of the node's current config (sibling fields) — used for depends_on resolution */
    nodeConfig?: Record<string, any>;
    /** Pre-fill the picker with this value (e.g., when drafter extracted a real value from the user's prompt). */
    defaultValue?: string;
}

/** Overall generation state */
export type GenerationPhase = 'idle' | 'generating' | 'awaiting_input' | 'complete';

/** Events emitted by the workflow generator */
export type GenerationEvent =
    | { type: 'node_start'; node: GeneratedNode }
    | { type: 'node_typing'; nodeId: string; content: string }
    | { type: 'node_complete'; nodeId: string }
    | { type: 'edge_add'; edge: GeneratedEdge }
    | { type: 'edge_complete'; edgeId: string }
    | { type: 'input_request'; request: InputRequest }
    | { type: 'generation_complete' };

// ============================================================================
// Workflow Templates
// ============================================================================

/** Structure for a workflow template */
export interface WorkflowTemplate {
    id: string;
    name: string;
    keywords: string[];
    nodes: Omit<GeneratedNode, 'status' | 'content'>[];
    edges: Omit<GeneratedEdge, 'status'>[];
    inputs: Omit<InputRequest, 'value'>[];
}

/** All available workflow templates for mock generation */
export const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
    {
        id: 'github-slack',
        name: 'GitHub to Slack Notifications',
        keywords: ['slack', 'github', 'issue'],
        nodes: [
            { id: 'trigger', type: 'automation-github-rest', label: 'GitHub Issue Created', level: 0, index: 0, parentIds: [] },
            { id: 'code', type: 'automation-serverless-function', label: 'Parse Issue Data', level: 1, index: 0, parentIds: ['trigger'] },
            { id: 'ai', type: 'agent', label: 'Generate Summary', level: 2, index: 0, parentIds: ['code'] },
            { id: 'slack', type: 'automation-slack', label: 'Post to Slack', level: 3, index: 0, parentIds: ['ai'] },
            { id: 'airtable', type: 'automation-airtable', label: 'Log to Airtable', level: 3, index: 1, parentIds: ['ai'] },
        ],
        edges: [
            { id: 'e1', sourceId: 'trigger', targetId: 'code' },
            { id: 'e2', sourceId: 'code', targetId: 'ai' },
            { id: 'e3', sourceId: 'ai', targetId: 'slack' },
            { id: 'e4', sourceId: 'ai', targetId: 'airtable' },
        ],
        inputs: [
            { id: 'inp1', nodeId: 'trigger', type: 'credential', label: 'GitHub Account', description: 'Connect your GitHub account', credentialType: 'github', required: true },
            { id: 'inp2', nodeId: 'slack', type: 'credential', label: 'Slack Workspace', description: 'Connect your Slack workspace', credentialType: 'slack', required: true },
            { id: 'inp3', nodeId: 'airtable', type: 'credential', label: 'Airtable Account', description: 'Connect your Airtable account', credentialType: 'airtable', required: true },
        ],
    },
    {
        id: 'email-processing',
        name: 'Email Processing Pipeline',
        keywords: ['email', 'gmail', 'outlook'],
        nodes: [
            { id: 'gmail', type: 'automation-gmail', label: 'Gmail Trigger', level: 0, index: 0, parentIds: [] },
            { id: 'outlook', type: 'automation-outlook', label: 'Outlook Trigger', level: 0, index: 1, parentIds: [] },
            { id: 'code', type: 'automation-serverless-function', label: 'Extract Content', level: 1, index: 0, parentIds: ['gmail', 'outlook'] },
            { id: 'ai', type: 'agent', label: 'Categorize Email', level: 2, index: 0, parentIds: ['code'] },
            { id: 'sheets', type: 'automation-google-sheets', label: 'Log to Sheets', level: 3, index: 0, parentIds: ['ai'] },
            { id: 'drive', type: 'automation-google-drive', label: 'Save Attachments', level: 3, index: 1, parentIds: ['ai'] },
            { id: 'slack', type: 'automation-slack', label: 'Notify Team', level: 3, index: 2, parentIds: ['ai'] },
        ],
        edges: [
            { id: 'e1', sourceId: 'gmail', targetId: 'code' },
            { id: 'e2', sourceId: 'outlook', targetId: 'code' },
            { id: 'e3', sourceId: 'code', targetId: 'ai' },
            { id: 'e4', sourceId: 'ai', targetId: 'sheets' },
            { id: 'e5', sourceId: 'ai', targetId: 'drive' },
            { id: 'e6', sourceId: 'ai', targetId: 'slack' },
        ],
        inputs: [
            { id: 'inp1', nodeId: 'gmail', type: 'credential', label: 'Gmail Account', description: 'Connect your Gmail account', credentialType: 'google', required: true },
            { id: 'inp2', nodeId: 'outlook', type: 'credential', label: 'Outlook Account', description: 'Connect your Outlook account', credentialType: 'microsoft', required: true },
            { id: 'inp3', nodeId: 'sheets', type: 'credential', label: 'Google Sheets', description: 'Connect Google Sheets', credentialType: 'google', required: true },
        ],
    },
    {
        id: 'data-sync',
        name: 'Data Sync Pipeline',
        keywords: ['airtable', 'spreadsheet', 'database'],
        nodes: [
            { id: 'trigger', type: 'trigger-cron', label: 'Hourly Schedule', level: 0, index: 0, parentIds: [] },
            { id: 'http', type: 'automation-http-request', label: 'Fetch API Data', level: 1, index: 0, parentIds: ['trigger'] },
            { id: 'code', type: 'automation-serverless-function', label: 'Transform Data', level: 2, index: 0, parentIds: ['http'] },
            { id: 'loop', type: 'iteration', label: 'Process Each Row', level: 3, index: 0, parentIds: ['code'] },
            { id: 'airtable', type: 'automation-airtable', label: 'Upsert to Airtable', level: 4, index: 0, parentIds: ['loop'] },
            { id: 'sheets', type: 'automation-google-sheets', label: 'Backup to Sheets', level: 4, index: 1, parentIds: ['loop'] },
        ],
        edges: [
            { id: 'e1', sourceId: 'trigger', targetId: 'http' },
            { id: 'e2', sourceId: 'http', targetId: 'code' },
            { id: 'e3', sourceId: 'code', targetId: 'loop' },
            { id: 'e4', sourceId: 'loop', targetId: 'airtable' },
            { id: 'e5', sourceId: 'loop', targetId: 'sheets' },
        ],
        inputs: [
            { id: 'inp1', nodeId: 'http', type: 'text', label: 'API Endpoint', description: 'Enter the API URL to fetch data from', required: true },
            { id: 'inp2', nodeId: 'airtable', type: 'credential', label: 'Airtable Account', description: 'Connect your Airtable account', credentialType: 'airtable', required: true },
            { id: 'inp3', nodeId: 'sheets', type: 'credential', label: 'Google Account', description: 'Connect your Google account', credentialType: 'google', required: true },
        ],
    },
    {
        id: 'project-management',
        name: 'Project Management Sync',
        keywords: ['notion', 'linear', 'task', 'jira'],
        nodes: [
            { id: 'linear', type: 'automation-linear', label: 'Linear Issue', level: 0, index: 0, parentIds: [] },
            { id: 'jira', type: 'automation-jira', label: 'Jira Ticket', level: 0, index: 1, parentIds: [] },
            { id: 'code', type: 'automation-serverless-function', label: 'Normalize Data', level: 1, index: 0, parentIds: ['linear', 'jira'] },
            { id: 'ai', type: 'agent', label: 'Analyze Priority', level: 2, index: 0, parentIds: ['code'] },
            { id: 'notion', type: 'automation-notion', label: 'Create Notion Page', level: 3, index: 0, parentIds: ['ai'] },
            { id: 'discord', type: 'automation-discord', label: 'Alert Discord', level: 3, index: 1, parentIds: ['ai'] },
            { id: 'gmail', type: 'automation-gmail', label: 'Email Assignee', level: 3, index: 2, parentIds: ['ai'] },
        ],
        edges: [
            { id: 'e1', sourceId: 'linear', targetId: 'code' },
            { id: 'e2', sourceId: 'jira', targetId: 'code' },
            { id: 'e3', sourceId: 'code', targetId: 'ai' },
            { id: 'e4', sourceId: 'ai', targetId: 'notion' },
            { id: 'e5', sourceId: 'ai', targetId: 'discord' },
            { id: 'e6', sourceId: 'ai', targetId: 'gmail' },
        ],
        inputs: [
            { id: 'inp1', nodeId: 'linear', type: 'credential', label: 'Linear Account', description: 'Connect your Linear workspace', credentialType: 'linear', required: true },
            { id: 'inp2', nodeId: 'jira', type: 'credential', label: 'Jira Account', description: 'Connect your Jira workspace', credentialType: 'jira', required: true },
            { id: 'inp3', nodeId: 'notion', type: 'credential', label: 'Notion Account', description: 'Connect your Notion workspace', credentialType: 'notion', required: true },
        ],
    },
    {
        id: 'social-media',
        name: 'Social Media Automation',
        keywords: ['twitter', 'social', 'post'],
        nodes: [
            { id: 'trigger', type: 'trigger-cron', label: 'Daily at 9am', level: 0, index: 0, parentIds: [] },
            { id: 'sheets', type: 'automation-google-sheets', label: 'Get Content Ideas', level: 1, index: 0, parentIds: ['trigger'] },
            { id: 'ai', type: 'agent', label: 'Generate Posts', level: 2, index: 0, parentIds: ['sheets'] },
            { id: 'code', type: 'automation-serverless-function', label: 'Format for Platforms', level: 3, index: 0, parentIds: ['ai'] },
            { id: 'twitter', type: 'automation-twitter', label: 'Post to Twitter', level: 4, index: 0, parentIds: ['code'] },
            { id: 'linkedin', type: 'automation-linkedin', label: 'Post to LinkedIn', level: 4, index: 1, parentIds: ['code'] },
            { id: 'airtable', type: 'automation-airtable', label: 'Track Posts', level: 4, index: 2, parentIds: ['code'] },
        ],
        edges: [
            { id: 'e1', sourceId: 'trigger', targetId: 'sheets' },
            { id: 'e2', sourceId: 'sheets', targetId: 'ai' },
            { id: 'e3', sourceId: 'ai', targetId: 'code' },
            { id: 'e4', sourceId: 'code', targetId: 'twitter' },
            { id: 'e5', sourceId: 'code', targetId: 'linkedin' },
            { id: 'e6', sourceId: 'code', targetId: 'airtable' },
        ],
        inputs: [
            { id: 'inp1', nodeId: 'sheets', type: 'credential', label: 'Google Account', description: 'Connect your Google account', credentialType: 'google', required: true },
            { id: 'inp2', nodeId: 'twitter', type: 'credential', label: 'Twitter Account', description: 'Connect your Twitter account', credentialType: 'twitter', required: true },
            { id: 'inp3', nodeId: 'linkedin', type: 'credential', label: 'LinkedIn Account', description: 'Connect your LinkedIn account', credentialType: 'linkedin', required: true },
        ],
    },
];

// ============================================================================
// DAG Test Generator - Clean directed acyclic graph for testing
// ============================================================================

/** Available node types for random generation */
const RANDOM_NODE_TYPES = [
    'automation-slack', 'automation-gmail', 'automation-notion', 'automation-airtable',
    'automation-discord', 'automation-google-sheets', 'automation-google-drive',
    'automation-http-request', 'automation-serverless-function', 'agent',
    'trigger-webhook', 'trigger-cron',
];

/**
 * Generate a long linear chain workflow for testing vertical scroll.
 * Structure: 50 nodes in a straight line, each connected to the next.
 */
function generateLongChainWorkflow(): WorkflowTemplate {
    const NUM_NODES = 50;
    const nodes: Omit<GeneratedNode, 'status' | 'content'>[] = [];
    const edges: Omit<GeneratedEdge, 'status'>[] = [];

    // Create 50 nodes in a linear chain
    for (let i = 0; i < NUM_NODES; i++) {
        const nodeType = RANDOM_NODE_TYPES[i % RANDOM_NODE_TYPES.length];
        const nodeId = `chain-${i}`;

        nodes.push({
            id: nodeId,
            type: nodeType,
            label: `Step ${i + 1}`,
            level: i,
            index: 0,
            parentIds: i > 0 ? [`chain-${i - 1}`] : [],
        });

        // Add edge from previous node
        if (i > 0) {
            edges.push({
                id: `chain-edge-${i - 1}`,
                sourceId: `chain-${i - 1}`,
                targetId: nodeId,
            });
        }
    }

    // Add a few inputs spread across the chain
    const inputs: Omit<InputRequest, 'value'>[] = [
        { id: 'chain-inp-0', nodeId: 'chain-0', type: 'credential', label: 'Start Credential', description: 'Connect your account', credentialType: 'slack', required: true },
        { id: 'chain-inp-1', nodeId: 'chain-24', type: 'credential', label: 'Midpoint Credential', description: 'Connect your account', credentialType: 'google', required: true },
        { id: 'chain-inp-2', nodeId: 'chain-49', type: 'credential', label: 'End Credential', description: 'Connect your account', credentialType: 'notion', required: true },
    ];

    return {
        id: 'long-chain',
        name: 'Long Chain Workflow',
        keywords: ['long', 'chain', 'linear'],
        nodes,
        edges,
        inputs,
    };
}

/**
 * Generate a clean DAG workflow for testing.
 * Structure: Predictable tree-like structure with controlled branching.
 * Bell curve distribution across 9 levels.
 * Total: 50 nodes
 */
function generateDagTestWorkflow(): WorkflowTemplate {
    const nodes: Omit<GeneratedNode, 'status' | 'content'>[] = [];
    const edges: Omit<GeneratedEdge, 'status'>[] = [];

    // Define the structure: [nodesAtLevel0, nodesAtLevel1, ...] = 50 nodes total
    const structure = [2, 4, 6, 8, 10, 8, 6, 4, 2];
    let nodeCounter = 0;

    // Create nodes level by level
    const nodesPerLevel: string[][] = [];

    for (let level = 0; level < structure.length; level++) {
        const count = structure[level];
        nodesPerLevel[level] = [];

        for (let i = 0; i < count; i++) {
            const nodeId = `dag-${nodeCounter}`;
            const nodeType = RANDOM_NODE_TYPES[nodeCounter % RANDOM_NODE_TYPES.length];

            nodes.push({
                id: nodeId,
                type: nodeType,
                label: `Node ${nodeCounter + 1}`,
                level,
                index: i,
                parentIds: [],
            });

            nodesPerLevel[level].push(nodeId);
            nodeCounter++;
        }
    }

    // Create edges: each node (except level 0) connects to 1-2 parents from the previous level
    let edgeCounter = 0;
    for (let level = 1; level < structure.length; level++) {
        const currentNodes = nodesPerLevel[level];
        const parentNodes = nodesPerLevel[level - 1];

        for (let i = 0; i < currentNodes.length; i++) {
            const nodeId = currentNodes[i];
            const node = nodes.find(n => n.id === nodeId)!;

            // Connect to at least one parent
            const primaryParentIdx = Math.min(i, parentNodes.length - 1);
            const primaryParent = parentNodes[primaryParentIdx];

            edges.push({
                id: `dag-edge-${edgeCounter++}`,
                sourceId: primaryParent,
                targetId: nodeId,
            });
            node.parentIds.push(primaryParent);

            // Sometimes connect to a second parent (for DAG complexity)
            if (parentNodes.length > 1 && i > 0 && i < currentNodes.length - 1) {
                const secondaryParentIdx = (primaryParentIdx + 1) % parentNodes.length;
                const secondaryParent = parentNodes[secondaryParentIdx];
                if (secondaryParent !== primaryParent) {
                    edges.push({
                        id: `dag-edge-${edgeCounter++}`,
                        sourceId: secondaryParent,
                        targetId: nodeId,
                    });
                    node.parentIds.push(secondaryParent);
                }
            }
        }
    }

    // Add some inputs for testing the input panel (spread across different levels)
    const inputs: Omit<InputRequest, 'value'>[] = [
        { id: 'dag-inp-0', nodeId: 'dag-0', type: 'credential', label: 'Slack Account', description: 'Connect your Slack workspace', credentialType: 'slack', required: true },
        { id: 'dag-inp-1', nodeId: 'dag-5', type: 'credential', label: 'Google Account', description: 'Connect your Google account', credentialType: 'google', required: true },
        { id: 'dag-inp-2', nodeId: 'dag-15', type: 'credential', label: 'Notion Account', description: 'Connect your Notion workspace', credentialType: 'notion', required: true },
        { id: 'dag-inp-3', nodeId: 'dag-25', type: 'selection', label: 'Output Format', description: 'Select output format', options: [{ id: 'json', label: 'JSON' }, { id: 'csv', label: 'CSV' }], required: true },
        { id: 'dag-inp-4', nodeId: 'dag-40', type: 'credential', label: 'Airtable Account', description: 'Connect your Airtable base', credentialType: 'airtable', required: true },
    ];

    return {
        id: 'dag-test',
        name: 'DAG Test Workflow',
        keywords: ['dag'],
        nodes,
        edges,
        inputs,
    };
}

/** Node labels for random generation */
const RANDOM_NODE_LABELS = [
    'Process Data', 'Transform Input', 'Validate Request', 'Send Notification',
    'Update Database', 'Filter Results', 'Parse Response', 'Generate Report',
    'Schedule Task', 'Sync Records', 'Archive Data', 'Clean Input',
    'Merge Datasets', 'Split Workflow', 'Aggregate Stats', 'Cache Results',
    'Retry Handler', 'Error Logger', 'Rate Limiter', 'Auth Check',
    'Format Output', 'Compress Data', 'Encrypt Payload', 'Decode Message',
    'Route Request', 'Load Balance', 'Queue Manager', 'Event Dispatcher',
    'State Manager', 'Config Loader', 'Health Check', 'Metrics Collector',
];

/**
 * Generate a stress test workflow with many nodes and edges
 */
function generateStressTestWorkflow(): WorkflowTemplate {
    const NUM_NODES = 50;
    const NUM_EDGES = 100;
    const NUM_LEVELS = 10;

    // Create nodes distributed across levels
    const nodes: Omit<GeneratedNode, 'status' | 'content'>[] = [];
    const nodesPerLevel: string[][] = Array.from({ length: NUM_LEVELS }, () => []);

    for (let i = 0; i < NUM_NODES; i++) {
        // Distribute nodes with more in middle levels (bell curve-ish)
        const levelWeights = [1, 2, 4, 6, 8, 8, 6, 4, 2, 1]; // 10 levels
        const totalWeight = levelWeights.reduce((a, b) => a + b, 0);
        let random = Math.random() * totalWeight;
        let level = 0;
        for (let l = 0; l < NUM_LEVELS; l++) {
            random -= levelWeights[l];
            if (random <= 0) {
                level = l;
                break;
            }
        }

        const nodeId = `node-${i}`;
        const nodeType = RANDOM_NODE_TYPES[Math.floor(Math.random() * RANDOM_NODE_TYPES.length)];
        const label = RANDOM_NODE_LABELS[Math.floor(Math.random() * RANDOM_NODE_LABELS.length)] + ` ${i + 1}`;

        nodesPerLevel[level].push(nodeId);

        nodes.push({
            id: nodeId,
            type: nodeType,
            label,
            level,
            index: nodesPerLevel[level].length - 1,
            parentIds: [], // Will be populated by edges
        });
    }

    // Create edges (only from lower levels to higher levels to maintain DAG)
    const edges: Omit<GeneratedEdge, 'status'>[] = [];
    const edgeSet = new Set<string>(); // Track unique edges

    // First, ensure connectivity - each node (except level 0) has at least one parent
    for (let level = 1; level < NUM_LEVELS; level++) {
        for (const nodeId of nodesPerLevel[level]) {
            // Find a parent from any lower level
            const possibleParents: string[] = [];
            for (let l = 0; l < level; l++) {
                possibleParents.push(...nodesPerLevel[l]);
            }
            if (possibleParents.length > 0) {
                const parentId = possibleParents[Math.floor(Math.random() * possibleParents.length)];
                const edgeKey = `${parentId}->${nodeId}`;
                if (!edgeSet.has(edgeKey)) {
                    edgeSet.add(edgeKey);
                    edges.push({
                        id: `edge-${edges.length}`,
                        sourceId: parentId,
                        targetId: nodeId,
                    });
                    // Update parentIds
                    const node = nodes.find(n => n.id === nodeId);
                    if (node && !node.parentIds.includes(parentId)) {
                        node.parentIds.push(parentId);
                    }
                }
            }
        }
    }

    // Add random edges until we reach NUM_EDGES
    let attempts = 0;
    while (edges.length < NUM_EDGES && attempts < 1000) {
        attempts++;

        // Pick a random source level (not the last)
        const sourceLevel = Math.floor(Math.random() * (NUM_LEVELS - 1));
        if (nodesPerLevel[sourceLevel].length === 0) continue;

        // Pick a random target level (higher than source)
        const targetLevel = sourceLevel + 1 + Math.floor(Math.random() * (NUM_LEVELS - sourceLevel - 1));
        if (targetLevel >= NUM_LEVELS || nodesPerLevel[targetLevel].length === 0) continue;

        const sourceId = nodesPerLevel[sourceLevel][Math.floor(Math.random() * nodesPerLevel[sourceLevel].length)];
        const targetId = nodesPerLevel[targetLevel][Math.floor(Math.random() * nodesPerLevel[targetLevel].length)];

        const edgeKey = `${sourceId}->${targetId}`;
        if (!edgeSet.has(edgeKey)) {
            edgeSet.add(edgeKey);
            edges.push({
                id: `edge-${edges.length}`,
                sourceId,
                targetId,
            });
            // Update parentIds
            const node = nodes.find(n => n.id === targetId);
            if (node && !node.parentIds.includes(sourceId)) {
                node.parentIds.push(sourceId);
            }
        }
    }

    // Sort nodes by level for proper generation order
    nodes.sort((a, b) => a.level - b.level || a.index - b.index);

    // Recalculate indices within each level
    const levelCounters: Record<number, number> = {};
    for (const node of nodes) {
        levelCounters[node.level] = (levelCounters[node.level] || 0);
        node.index = levelCounters[node.level]++;
    }

    // Create some input requests for random nodes
    const inputs: Omit<InputRequest, 'value'>[] = [];
    const credentialTypes = ['slack', 'google', 'airtable', 'notion', 'github', 'discord'];
    const inputNodes = nodes.filter(n => Math.random() < 0.15).slice(0, 8); // ~15% of nodes, max 8

    inputNodes.forEach((node, i) => {
        inputs.push({
            id: `stress-inp-${i}`,
            nodeId: node.id,
            type: 'credential',
            label: `${node.label} Credential`,
            description: `Connect your ${credentialTypes[i % credentialTypes.length]} account`,
            credentialType: credentialTypes[i % credentialTypes.length],
            required: true,
        });
    });

    return {
        id: 'stress-test',
        name: 'Stress Test Workflow',
        keywords: ['stress', 'test', 'complex', 'large'],
        nodes,
        edges,
        inputs,
    };
}

/** Cached stress test template (regenerated each time for variety) */
let cachedStressTestTemplate: WorkflowTemplate | null = null;

/** Get or generate stress test template */
function getStressTestTemplate(): WorkflowTemplate {
    // Regenerate each time for variety
    cachedStressTestTemplate = generateStressTestWorkflow();
    return cachedStressTestTemplate;
}

/** Default workflow template when no keywords match */
export const DEFAULT_WORKFLOW_TEMPLATE: WorkflowTemplate = {
    id: 'default',
    name: 'General Automation',
    keywords: [],
    nodes: [
        { id: 'webhook', type: 'trigger-webhook', label: 'Webhook Trigger', level: 0, index: 0, parentIds: [] },
        { id: 'form', type: 'interface-form', label: 'Form Submission', level: 0, index: 1, parentIds: [] },
        { id: 'code', type: 'automation-serverless-function', label: 'Validate & Transform', level: 1, index: 0, parentIds: ['webhook', 'form'] },
        { id: 'ai', type: 'agent', label: 'AI Processing', level: 2, index: 0, parentIds: ['code'] },
        { id: 'airtable', type: 'automation-airtable', label: 'Store in Airtable', level: 3, index: 0, parentIds: ['ai'] },
        { id: 'gmail', type: 'automation-gmail', label: 'Send Confirmation', level: 3, index: 1, parentIds: ['ai'] },
        { id: 'slack', type: 'automation-slack', label: 'Notify Slack', level: 3, index: 2, parentIds: ['ai'] },
    ],
    edges: [
        { id: 'e1', sourceId: 'webhook', targetId: 'code' },
        { id: 'e2', sourceId: 'form', targetId: 'code' },
        { id: 'e3', sourceId: 'code', targetId: 'ai' },
        { id: 'e4', sourceId: 'ai', targetId: 'airtable' },
        { id: 'e5', sourceId: 'ai', targetId: 'gmail' },
        { id: 'e6', sourceId: 'ai', targetId: 'slack' },
    ],
    inputs: [
        { id: 'inp1', nodeId: 'airtable', type: 'credential', label: 'Airtable Account', description: 'Connect your Airtable account', credentialType: 'airtable', required: true },
        { id: 'inp2', nodeId: 'gmail', type: 'credential', label: 'Gmail Account', description: 'Connect your Gmail account', credentialType: 'google', required: true },
        { id: 'inp3', nodeId: 'slack', type: 'credential', label: 'Slack Workspace', description: 'Connect your Slack workspace', credentialType: 'slack', required: true },
    ],
};

// ============================================================================
// Helper Functions
// ============================================================================

/**
 * Find the best matching workflow template for a given prompt
 */
export function getWorkflowTemplateForPrompt(prompt: string): WorkflowTemplate {
    const promptLower = prompt.toLowerCase();

    // Check for long chain test (linear 50-node chain)
    if (promptLower.includes('long') || promptLower.includes('chain') || promptLower.includes('linear')) {
        return generateLongChainWorkflow();
    }

    // Check for DAG test keyword (50 nodes in tree structure)
    if (promptLower.includes('dag')) {
        return generateDagTestWorkflow();
    }

    // Check for stress test keywords (large random graph)
    const stressKeywords = ['stress', 'complex', 'large', '50 nodes', 'many nodes'];
    if (stressKeywords.some(keyword => promptLower.includes(keyword))) {
        return getStressTestTemplate();
    }

    for (const template of WORKFLOW_TEMPLATES) {
        if (template.keywords.some(keyword => promptLower.includes(keyword))) {
            return template;
        }
    }

    return DEFAULT_WORKFLOW_TEMPLATE;
}

/** Node typing content for simulated streaming effect */
const NODE_TYPING_CONTENT: Record<string, string[]> = {
    'automation-github-rest': ['Listening for: issue.created', 'Repository: {{selected}}', 'Include: title, body, author'],
    'automation-gmail': ['Trigger: New email', 'Filter: Has attachments', 'From: Any sender'],
    'automation-outlook': ['Trigger: New email', 'Folder: Inbox', 'Filter: Unread only'],
    'trigger-webhook': ['Method: POST', 'Auth: Basic or JWT', 'Receives inbound HTTP requests'],
    'trigger-cron': ['Schedule: Every hour', 'Timezone: UTC', 'Enabled: true'],
    'interface-form': ['Form ID: {{generated}}', 'Fields: name, email', 'Validation: required'],
    'automation-serverless-function': ['// Transform data', 'const result = input.map(', '  item => process(item)', ');', 'return result;'],
    'agent': ['Model: GPT-4', 'Task: Analyze & summarize', 'Output: structured JSON'],
    'automation-slack': ['Channel: {{selected}}', 'Message: {{formatted}}', 'Thread: New message'],
    'automation-airtable': ['Base: {{selected}}', 'Table: {{selected}}', 'Action: Create record'],
    'automation-google-sheets': ['Spreadsheet: {{selected}}', 'Sheet: Sheet1', 'Action: Append row'],
    'automation-google-drive': ['Folder: {{selected}}', 'Filename: {{original}}', 'Convert: None'],
    'automation-http-request': ['Method: POST', 'URL: {{endpoint}}', 'Headers: Content-Type: json'],
    'iteration': ['Input: {{array}}', 'Batch size: 10', 'Continue on error: true'],
    'automation-linear': ['Team: {{selected}}', 'Event: Issue created', 'Filter: All priorities'],
    'automation-jira': ['Project: {{selected}}', 'Event: Issue created', 'Filter: All types'],
    'automation-notion': ['Database: {{selected}}', 'Action: Create page', 'Template: None'],
    'automation-discord': ['Server: {{selected}}', 'Channel: {{selected}}', 'Message type: Embed'],
    'automation-twitter': ['Account: {{connected}}', 'Action: Post tweet', 'Include media: optional'],
    'automation-linkedin': ['Profile: {{connected}}', 'Action: Create post', 'Visibility: Public'],
};

/**
 * Get typing content for a node type (used for streaming animation)
 */
export function getTypingContent(nodeType: string): string[] {
    return NODE_TYPING_CONTENT[nodeType] || ['Configuring...', 'Setting up node...'];
}

// ============================================================================
// Mock Generator
// ============================================================================

export interface WorkflowGenerator {
    start: () => void;
    cancel: () => void;
}

/**
 * Creates a mock workflow generator that simulates AI-powered workflow creation.
 * Emits events as nodes and edges are "generated" with typing animations.
 *
 * This will be replaced with real backend streaming calls in production.
 */
export function createWorkflowGenerator(
    prompt: string,
    onEvent: (event: GenerationEvent) => void
): WorkflowGenerator {
    let cancelled = false;
    const timeouts: NodeJS.Timeout[] = [];

    const delay = (ms: number) => new Promise<void>((resolve) => {
        const timeout = setTimeout(resolve, ms);
        timeouts.push(timeout);
    });

    const generateWorkflow = async () => {
        const template = getWorkflowTemplateForPrompt(prompt);
        const { nodes, edges, inputs } = template;

        // Use fast timing for test workflows (dag, stress) or large workflows
        const isTestWorkflow = template.id === 'dag-test' || template.id === 'stress-test' || nodes.length > 20;
        const timing = isTestWorkflow
            ? { nodeStart: 50, typing: 0, typeChar: 0, nodeComplete: 30, edgeAdd: 20, edgeComplete: 0, inputDelay: 40 }
            : { nodeStart: 300, typing: 200, typeChar: 50, nodeComplete: 300, edgeAdd: 400, edgeComplete: 0, inputDelay: 200 };

        // Track which edges have been added (to avoid duplicates)
        const addedEdges = new Set<string>();

        // Simulate streaming the workflow generation
        for (const node of nodes) {
            if (cancelled) return;

            // Start adding node
            onEvent({ type: 'node_start', node: { ...node, status: 'adding', content: '' } });
            await delay(timing.nodeStart);
            if (cancelled) return;

            // Simulate typing in the node (skip for test workflows)
            if (!isTestWorkflow) {
                const typingTexts = getTypingContent(node.type);
                onEvent({ type: 'node_typing', nodeId: node.id, content: '' });
                await delay(timing.typing);

                for (let i = 0; i < typingTexts.length; i++) {
                    if (cancelled) return;
                    onEvent({ type: 'node_typing', nodeId: node.id, content: typingTexts.slice(0, i + 1).join('\n') });
                    await delay(timing.typeChar + Math.random() * timing.typeChar);
                }

                await delay(timing.nodeComplete);
            }
            if (cancelled) return;

            // Complete the node
            onEvent({ type: 'node_complete', nodeId: node.id });
            await delay(timing.nodeComplete);

            // Add edges from this node's parents (edges where this node is the target)
            const nodeEdges = edges.filter(e => e.targetId === node.id && !addedEdges.has(e.id));
            for (const edge of nodeEdges) {
                if (cancelled) return;
                addedEdges.add(edge.id);
                onEvent({ type: 'edge_add', edge: { ...edge, status: 'animating' } });
                await delay(timing.edgeAdd);
                if (cancelled) return;
                onEvent({ type: 'edge_complete', edgeId: edge.id });
            }
        }

        // Request inputs
        if (inputs.length > 0) {
            await delay(timing.inputDelay * 2);
            for (const input of inputs) {
                if (cancelled) return;
                onEvent({ type: 'input_request', request: { ...input, value: undefined } });
                await delay(timing.inputDelay);
            }
        }

        await delay(timing.nodeComplete);
        if (!cancelled) {
            onEvent({ type: 'generation_complete' });
        }
    };

    return {
        start: () => { generateWorkflow(); },
        cancel: () => {
            cancelled = true;
            timeouts.forEach(t => clearTimeout(t));
        },
    };
}
