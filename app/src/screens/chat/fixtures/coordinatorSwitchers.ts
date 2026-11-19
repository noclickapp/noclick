// What the Chat page's switchers read and change beside the coordinator agent, for its tests and the local preview:
// Work's own catalog (harnesses and their models, the account's connections, its machines) and the agent's PATCH as
// the API answers it: a coding harness with no model connection refused for want of one, a move to one answered with
// its notes. Plugged into fakeCoordinatorAgent's `routes`.
import { catalogRoutes } from '@/screens/work/conversation/fixtures/workAgent';
import { AGENT_ID, type ExtraRoutes } from './coordinatorAgent';

type Json = Record<string, unknown>;

/** The coordinator as it's made: on NoClick's own runtime and key, no budget of its own set, no machine. */
export const SWITCHING_AGENT: Json = { harness: 'sdk', model: 'claude-sonnet-5-5', effort: 'medium', model_connection: null, budget_usd_per_month: null, machine_id: null };

/** An Anthropic key the account connected itself. */
export const ANTHROPIC_KEY: Json = { object: 'connection', id: 'conn-key', name: 'anthropic', integration: 'anthropic', credential_type: 'agent_anthropic', connected: true, status: 'connected', origin: 'api', account: 'Key ending 4f2a' };

/** What a move to a coding harness tells the person, as the API's `notes` say it. */
export const CODING_NOTE = 'Texts you send while it’s writing a reply now wait for that reply, and its first reply after a quiet spell takes longer.';

/** `agent`: the fake's own agent (fakeCoordinatorAgent's `agent`), which a PATCH here changes. */
export function switcherRoutes(options: { agent: () => Json; connections?: Json[]; at?: () => string }): ExtraRoutes {
    const at = options.at ?? (() => new Date().toISOString());
    const connections = (options.connections ?? [ANTHROPIC_KEY]).map((c) => ({ ...c }));
    return (method, path, query, body) => {
        if (method === 'PATCH' && path === `/v1/agents/${AGENT_ID}`) {
            const agent = options.agent();
            const changes = body as Json;
            const harness = String(changes.harness ?? agent.harness);
            const connection = 'model_connection' in changes ? changes.model_connection : agent.model_connection;
            if (harness !== 'sdk' && !connection)
                return Response.json(
                    {
                        error: {
                            type: 'invalid_request',
                            message: `${harness} runs on your own key or plan, and none is connected.`,
                            field: 'model_connection',
                            next_step: `Have the person connect one: POST /v1/connections {name, integration, use_for: {agent: "${AGENT_ID}", harness: "${harness}"}} (connections_create).`,
                        },
                    },
                    { status: 400 }
                );
            const moved = 'harness' in changes && changes.harness !== agent.harness && harness !== 'sdk';
            Object.assign(agent, changes, 'harness' in changes && !('model' in changes) ? { model: null } : {});
            return Response.json({ ...agent, notes: moved ? [CODING_NOTE] : [] });
        }
        return catalogRoutes(method, path, connections, undefined, at, query);
    };
}
