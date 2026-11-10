// The node search catalog (utils/nodeSearchCatalog), built from every node's definition and schema the server holds
// (lib/nodeSchemas.server) with the same functions the client used to run over a thousand fetched schemas, once per
// server process.
import '~/lib/nodeSchemas.server';
import { getAgentToolOperations, getAgentWirableCatalog } from '~/utils/nodeSchemas';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { nodeSearchText } from '~/utils/nodeSearchMatch';
import { toolActionText, triggerActionText } from '~/utils/nodeServiceSearch';
import { encodeNodeSearchCatalog, type NodeSearchCatalog } from '~/utils/nodeSearchCatalog';
import { getAllSerializedNodeMeta } from '~/lib/nodeCatalog.server';

let _json: string | null = null;

export function buildNodeSearchCatalog(): NodeSearchCatalog {
    const text: NodeSearchCatalog['text'] = {};
    for (const node of AVAILABLE_NODES) text[node.type] = nodeSearchText(node.type);
    const wirable = getAgentWirableCatalog();
    const actions: NodeSearchCatalog['actions'] = { trigger: {}, tool: {} };
    for (const { nodeType, triggerOps } of wirable.triggers) actions.trigger[nodeType] = triggerActionText(triggerOps);
    for (const nodeType of wirable.tools) actions.tool[nodeType] = toolActionText(getAgentToolOperations(nodeType));
    return { nodes: getAllSerializedNodeMeta(), text, wirable, actions };
}

/** The catalog as the route sends it (computed on first request). */
export function nodeSearchCatalogJson(): string {
    _json ??= JSON.stringify(encodeNodeSearchCatalog(buildNodeSearchCatalog()));
    return _json;
}
