// The agent step's AI account, as the Setup tab's standard draws it (standards.tsx, loaded when it first draws): the
// step's own account pickers for the model the agent names, which connect one through `connect.model`.
import type { Node } from '@xyflow/react';
import { NodeCredentials } from '../form/NodeCredentials';

export default function RuntimeAccounts({ node, onCredentialIdsChange }: { node: Node; onCredentialIdsChange: (nodeId: string, credentialIds: Record<string, string>) => void }) {
    const data = (node.data ?? {}) as { config?: Record<string, unknown>; credentialIds?: Record<string, string> };
    return <NodeCredentials nodeType="agent" nodeData={{ config: data.config ?? {} }} credentialIds={data.credentialIds ?? {}} onChange={(ids) => onCredentialIdsChange(node.id, ids)} compact />;
}
