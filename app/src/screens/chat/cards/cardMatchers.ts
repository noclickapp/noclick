// What each of the chat's cards is drawn for, recognised from the call alone. Apart from the cards themselves so a
// host can recognise a call (and say what its card draws on its canvas) without loading them.
import type { CanvasOf } from './canvases';
import type { ConnectAsk } from './toolCardRegistry';
import type { CoordinatorJobs } from '@/lib/threadJobs';
import { failed, list, obj, str, type CoordinatorToolCall, type JsonObject } from '@/lib/toolCalls';

const HELD = new Set(['awaiting_approval', 'approved_running']);
const GOING = new Set(['queued', 'running', 'awaiting_human']);

/** The operation a call ran as its arguments name it (api_call's `operation`, else the tool's own name); undefined
 *  once they were cut, as a thread keeps a long call's arguments. */
export function operationOf(call: CoordinatorToolCall): string | undefined {
    return call.tool === 'api_call' ? str(call.args, 'operation') : call.tool;
}

/** The object of `kind` a call answered with: api_call's `response`, or a task tool's own key for it (agents_save's
 *  `agent`). A card is decided by what the call answered, never by its arguments: a thread keeps a long call's
 *  arguments cut (an agent made with its instructions, a channel with its schedule) and its answer's start whole.
 *  Arguments that still name an operation outside `writes` draw nothing, so reading a thing back never draws it
 *  again; only long arguments are cut, which a read's never are. */
function answered(call: CoordinatorToolCall, kind: string, writes: ReadonlySet<string>): JsonObject | undefined {
    const operation = operationOf(call);
    if (failed(call.result) || (operation && !writes.has(operation))) return undefined;
    return [obj(call.result, 'response'), obj(call.result, kind)].find((v) => str(v, 'object') === kind);
}

/** A platform call the gate held for a person. */
export function isPlatformApproval(call: CoordinatorToolCall): boolean {
    return HELD.has(str(call.result, 'status') ?? '') && !!str(call.result, 'approval_id');
}

/** A link a person opens to connect an account, as a platform call made it (a connection made with its link, or a
 *  new link for one) or read back while it waits on them (fetch's `object`: how a link made earlier is handed over):
 *  its provide page, the account type it connects, and what it's for. */
export function connectLinkOf(call: CoordinatorToolCall): { url: string; credentialType: string; reason?: string } | undefined {
    if (failed(call.result)) return undefined;
    const response = obj(call.result, 'response') ?? (str(call.result, 'status') === 'awaiting_human' ? obj(call.result, 'object') : undefined);
    const link = str(response, 'object') === 'connect_link' ? response : obj(response, 'connect_link');
    const url = str(link, 'url');
    const credentialType = str(link, 'credential_type') ?? str(response, 'credential_type');
    if (!url?.includes('/credential/provide/') || !credentialType) return undefined;
    return { url, credentialType, reason: str(obj(call.args, 'arguments'), 'reason') };
}

export function isConnectLink(call: CoordinatorToolCall): boolean {
    return !!connectLinkOf(call);
}

/** A connect link as an ask on the turn's one connect card. An AI company's key isn't one: it's offered as its plan's
 *  sign-in (PlanConnectCard), or on a card of its own where its company has no plan. */
export function connectAskOfLink(call: CoordinatorToolCall): ConnectAsk | undefined {
    const link = !isModelConnectLink(call) ? connectLinkOf(call) : undefined;
    return link && { id: call.id, credentialType: link.credentialType, url: link.url, message: link.reason, startedAt: call.startedAt, operationId: str(call.result, 'operation_id') };
}

/** A link to connect an AI company's account for an agent's model (a key type, `agent_<provider>`): offered as its
 *  plan's sign-in where it has one (PlanConnectCard), else as any other account's. */
export function isModelConnectLink(call: CoordinatorToolCall): boolean {
    const type = connectLinkOf(call)?.credentialType;
    return !!type?.startsWith('agent_') && !type.endsWith('_oauth');
}

/** A link a platform call made for the owner to pay (account_payment_links_create): funds for the balance, or a plan.
 *  Its operation waits on them, so it's drawn as a link to pay, never as work going on. */
export function paymentLinkOf(call: CoordinatorToolCall): JsonObject | undefined {
    const response = obj(call.result, 'response');
    return !failed(call.result) && str(response, 'object') === 'payment_link' && str(response, 'url')?.includes('/pay/') ? response : undefined;
}

export function isPaymentLink(call: CoordinatorToolCall): boolean {
    return !!paymentLinkOf(call);
}

/** A change handed to an app's coding agent as a job of its own: neither joined to one under way nor the turn that
 *  moves the agent to another model first. */
export function isCodingHandOff(call: CoordinatorToolCall): boolean {
    const job = obj(call.result, 'response');
    return !failed(call.result) && str(job, 'object') === 'coding_job' && !!str(job, 'operation_id') && job?.joined !== true && job?.switching !== true;
}

/** A browser act: an agent's own browser tool, or NoClick's call of the API that starts one. Drawn while it runs too:
 *  the browser is live beside the conversation until it settles into its receipt. */
export function isBrowserAct(call: CoordinatorToolCall): boolean {
    return (call.tool === 'browser__act' || operationOf(call) === 'browsers_act') && !failed(call.result);
}

// The calls that use a conversation's browser besides an act: NoClick's of the browser API (asking for its browser,
// opening a page, reading it), and an agent's browser tools.
const BROWSER_API_USE = /^browsers_(create|goto|act|extract|content|screenshot)$/;
const BROWSER_TOOL = /^browser__(goto|act|extract|content)$/;

/** A call that uses the conversation's browser (an act included): what the chat's browser cards are drawn for. */
export function isBrowserCall(call: CoordinatorToolCall): boolean {
    return BROWSER_TOOL.test(call.tool) || (call.tool === 'api_call' && BROWSER_API_USE.test(operationOf(call) ?? ''));
}

/** A turn that used the browser without an act (it opened and read pages itself): its card is drawn on its first
 *  such call that didn't fail, and carries the rest of the turn's (an act draws its own card instead). */
export function isBrowserUse(call: CoordinatorToolCall, turn: readonly CoordinatorToolCall[] = [call]): boolean {
    if (turn.some(isBrowserAct)) return false;
    return turn.find((c) => isBrowserCall(c) && !failed(c.result))?.id === call.id;
}

/** What every browser card in a thread is about, so only the newest is drawn live and in full: the conversation's
 *  browser (one works in it at a time). */
export const BROWSER_CANVAS = 'browser';

export function browserCanvas(call: CoordinatorToolCall): string | undefined {
    return isBrowserCall(call) && !failed(call.result) ? BROWSER_CANVAS : undefined;
}

/** The act's operation: the one the API answered with, else the one the browser tool named. */
export function actIdOf(call: CoordinatorToolCall): string | null {
    const response = obj(call.result, 'response');
    return (str(response, 'object') === 'operation' ? str(response, 'id') : undefined) ?? str(call.result, 'operation_id') ?? null;
}

/** A platform call that set an operation going, and it hasn't settled. */
export function isPlatformOperation(call: CoordinatorToolCall): boolean {
    return !failed(call.result) && GOING.has(str(call.result, 'status') ?? '') && !!str(call.result, 'operation_id') && !str(call.result, 'approval_id');
}

// Work on a site: deploying it, promoting a deployment, checking its pages.
const SITE_WORK = new Set(['project.deploy', 'project.promote', 'deployment.check']);

function hostOf(url: string | undefined): string | undefined {
    if (!url) return undefined;
    try {
        return new URL(url).host || undefined;
    } catch {
        return undefined;
    }
}

/** What an operation's card is about, drawn in full only on the newest card about it: the site its deploys and
 *  checks are for (so a site deployed and checked over several turns is one card, where it now stands), else the
 *  operation, so reading it again while it runs draws no second card. Its kind and address come from the thread's
 *  read of it, else from what the call answered. */
export function operationCanvas(call: CoordinatorToolCall, jobs: CoordinatorJobs): string | undefined {
    if (!isPlatformOperation(call)) return undefined;
    const id = str(call.result, 'operation_id')!;
    const job = jobs.get(str(call.result, 'job_id') ?? id);
    const answered = [obj(call.result, 'response'), obj(call.result, 'object')].find((v) => str(v, 'object') === 'operation');
    const kind = [str(job, 'kind'), str(answered, 'kind')].find((k) => k && SITE_WORK.has(k));
    const site = kind && hostOf(str(job, 'url') ?? str(obj(job, 'result'), 'url') ?? str(answered, 'url'));
    return site ? `site:${site}` : `operation:${id}`;
}

const BUILD = 'workflow.build';

/** The build a platform call started: a workflow's build (its operation answered whole), or a workflow created with
 *  its build. A cut preview may keep only the workflow it made; the operation's own read names the rest. */
export function buildOf(call: CoordinatorToolCall): { workflowId?: string; name?: string; operation?: JsonObject } | undefined {
    if (!str(call.result, 'operation_id') || failed(call.result)) return undefined;
    const response = obj(call.result, 'response');
    const created = str(response, 'object') === 'workflow' ? response : undefined;
    const operation = str(response, 'kind') === BUILD ? response : str(obj(created, 'build'), 'kind') === BUILD ? obj(created, 'build') : undefined;
    if (!operation && !created) return undefined;
    const workflowId = str(operation, 'workflow_id') ?? str(created, 'id') ?? str(obj(call.args, 'arguments'), 'workflow_id');
    return { workflowId, name: str(created, 'name'), operation };
}

export function isWorkflowBuild(call: CoordinatorToolCall): boolean {
    return !!buildOf(call);
}

/** The workflow a platform build's card draws: as the call named it, else as its operation's read does. */
export function workflowBuildCanvas(call: CoordinatorToolCall, jobs: CoordinatorJobs): string | undefined {
    const build = buildOf(call);
    return build && (build.workflowId ?? str(jobs.get(str(call.result, 'operation_id')), 'workflow_id'));
}

const AGENT_WRITES = new Set(['agents_create', 'agents_update', 'agents_save']);

/** An agent a platform call made or changed, as the agent it answered: its id, the workflow it runs on (its
 *  automation), and its name. */
export function agentOf(call: CoordinatorToolCall): { agentId: string; workflowId: string; name?: string } | undefined {
    const agent = answered(call, 'agent', AGENT_WRITES);
    const agentId = str(agent, 'id');
    const workflowId = str(agent, 'workflow_id');
    return agentId && workflowId ? { agentId, workflowId, name: str(agent, 'name') } : undefined;
}

/** An agent's own card: unless a channel its turn made or put an agent in carries it (the channel's card in the reply
 *  shows it there, as the coordinator puts each new agent in a channel in the turn that makes it). */
export function isPlatformAgent(call: CoordinatorToolCall, turn?: readonly CoordinatorToolCall[]): boolean {
    return !!agentOf(call) && !turn?.some(isChannelCard);
}

/** What an agent's card is about, drawn in full only on the newest card about it: its automation. */
export function agentCanvas(call: CoordinatorToolCall): string | undefined {
    return agentOf(call)?.workflowId;
}

const CHANNEL_WRITES = new Set(['channels_create']);
const CHANNEL_JOINS = new Set(['channels_members_create']);

/** The channel a card in the reply shows: one a platform call made (as the channel it answered), or one it put an
 *  agent in (a channel the person named: the member it answered, `joined`, in the channel its arguments name, which
 *  a join's are short enough to keep whole). */
export function channelCardOf(call: CoordinatorToolCall): { channelId: string; name?: string; joined?: string } | undefined {
    const channel = answered(call, 'channel', CHANNEL_WRITES);
    const channelId = str(channel, 'id');
    if (channelId) return { channelId, name: str(channel, 'name') };
    const member = answered(call, 'channel_member', CHANNEL_JOINS);
    const into = str(call.tool === 'api_call' ? obj(call.args, 'arguments') : call.args, 'channel_id');
    const joined = str(member, 'type') === 'agent' ? str(member, 'id') : undefined;
    return into && joined ? { channelId: into, joined } : undefined;
}

export function isChannelCard(call: CoordinatorToolCall): boolean {
    return !!channelCardOf(call);
}

/** What a channel's card is about, drawn in full only on the newest card about it: the channel. */
export function channelCanvas(call: CoordinatorToolCall): string | undefined {
    const card = channelCardOf(call);
    return card && `channel:${card.channelId}`;
}

const MCP_SERVER_CALLS = new Set(['mcp_servers_create', 'mcp_servers_get', 'mcp_servers_update', 'mcp_servers_rotate']);

/** An MCP server NoClick hosts that a platform call made, read or changed, as the server it answered: its card
 *  connects the owner's agent to it. */
export function mcpServerOf(call: CoordinatorToolCall): { serverId: string; name?: string } | undefined {
    const server = answered(call, 'mcp_server', MCP_SERVER_CALLS);
    const serverId = str(server, 'id');
    return serverId ? { serverId, name: str(server, 'name') } : undefined;
}

export function isMcpServer(call: CoordinatorToolCall): boolean {
    return !!mcpServerOf(call);
}

/** What a server's card draws in full only on the newest card about it: the server, apart from any workflow's id. */
export function mcpServerCanvas(call: CoordinatorToolCall): string | undefined {
    const server = mcpServerOf(call);
    return server && `mcp_server:${server.serverId}`;
}

const SERVE_OPERATION = 'projects_domains_create';

/** The domain a call answered and the name it served the app at, when the call served an app there: the operation
 *  as a tool of its own, or api_call's. */
export function servedDomainOf(call: CoordinatorToolCall): { domain: JsonObject; name: string } | undefined {
    const args = call.tool === SERVE_OPERATION ? call.args : call.tool === 'api_call' && str(call.args, 'operation') === SERVE_OPERATION ? obj(call.args, 'arguments') : undefined;
    const name = str(args, 'name')?.toLowerCase().replace(/\.$/, '');
    const domain = obj(call.result, 'response');
    return name && !failed(call.result) && str(domain, 'object') === 'domain' ? { domain: domain!, name } : undefined;
}

/** The hostnames the call served the app at (the name, and www. with it when the name is the domain itself) and
 *  that app's name: the domain's view lists every app it serves. */
export function servedNames({ domain, name }: { domain: JsonObject; name: string }): { app?: string; hostnames: string[] } {
    const wanted = name === str(domain, 'name') ? [name, `www.${name}`] : [name];
    const serves = list(domain, 'serves').filter(
        (s): s is JsonObject => !!s && typeof s === 'object' && (s as JsonObject).kind === 'project' && wanted.includes(str(s as JsonObject, 'hostname') ?? '')
    );
    return { app: str(serves[0], 'name'), hostnames: serves.map((s) => str(s, 'hostname')!) };
}

export function isDomainServed(call: CoordinatorToolCall): boolean {
    const served = servedDomainOf(call);
    return !!served && servedNames(served).hostnames.length > 0;
}

const PLACE_CALL = 'phone_numbers_calls_create';

/** A platform call that placed a phone call, with the operation that follows it. Its arguments name it (a call's
 *  are short, so a thread keeps them whole): what it answered is fenced as a call's words, never the operation. */
export function isPlacedCall(call: CoordinatorToolCall): boolean {
    return operationOf(call) === PLACE_CALL && !failed(call.result) && !!str(call.result, 'operation_id') && !str(call.result, 'approval_id');
}

/** The page a call answered with where the person picks and buys a phone number (a quote for a number whose country
 *  asks for documents, which they give there): its address, whatever the call's tool. */
export function phonePurchasePageOf(call: CoordinatorToolCall): string | undefined {
    const page = str(call.result, 'approval_url');
    return !failed(call.result) && page && /\/credential\/purchase\/[^/?#]+/.test(page) ? page : undefined;
}

export function isPhonePurchaseLink(call: CoordinatorToolCall): boolean {
    return !!phonePurchasePageOf(call);
}

/** What each of the chat's cards draws on its canvas, tried in this order after a host's. Every browser card is about
 *  the conversation's one browser, so it's tried ahead of the operation's, which would otherwise claim an act's call. */
export const CARD_CANVASES: readonly CanvasOf[] = [browserCanvas, workflowBuildCanvas, agentCanvas, channelCanvas, mcpServerCanvas, operationCanvas];
