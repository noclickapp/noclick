// What is wired to an agent step, as the canvas works it out from its steps and connections: the triggers that wake it
// and the steps that give it tools. The agent's chat on the Interface tab lists both (its Triggers and Tools).

/** NoClick's own steps an agent uses as its tools, wired from their top into the agent's bottom as an integration that
 *  offers its operations is: each makes its own tools, so it takes no allowlist. */
export const STRUCTURAL_TOOL_TYPES: ReadonlySet<string> = new Set(['tool', 'mcp-server', 'alarm', 'filesystem', 'noclick']);

/** A trigger wired into an agent's input: when it fires, the agent runs with the event as part of its turn. */
export interface AgentTriggerSource {
    edgeId: string;
    nodeId: string;
    nodeType: string;
    /** The step's own name; empty when unset (show its type's). */
    label: string;
    /** The operation it's set to, for an integration's trigger. */
    operation?: string;
}

/** A step wired under an agent as its tools. */
export interface AgentWiredTool {
    edgeId: string;
    nodeId: string;
    nodeType: string;
    /** The step's own name; empty when unset (show its type's). */
    label: string;
    /** The operations the agent may call on it (its `agent_tool_operations`). */
    operations: string[];
    /** It needs an account and none is connected, so its calls will fail. */
    credentialsMissing: boolean;
    /** The accounts it holds, credential type to id, so a reader can tell whether each still works. */
    credentialIds: Record<string, string>;
}

/** An agent's triggers and tools. */
export interface AgentWiring {
    triggers: AgentTriggerSource[];
    tools: AgentWiredTool[];
}
