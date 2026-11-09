import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { RepairDeskNode } from '~/components/workflow/nodes/integrations/repairdesk';
import metadata from '~/schemas/nodeMeta/repairdesk.json';

beforeAll(async () => { await loadNodeSchemas(['automation-repairdesk']); });
it('discovers RepairDesk API tokens, v2 operations and poll triggers', () => {
    expect(RepairDeskNode.category).toBe('industry');
    expect(getNodeCredentialInfo(RepairDeskNode.type)?.acceptedTypes).toEqual(['repairdesk_api_key']);
    expect(credentialRequirements(RepairDeskNode.type).map(methodFromRequirement)).toEqual([
        expect.objectContaining({ credential_type: 'repairdesk_api_key', method_kind: 'api_key', is_oauth: false }),
    ]);
    const operations = getAgentToolOperations(RepairDeskNode.type).map(op => op.operation);
    expect(operations).toEqual(expect.arrayContaining(['list_purchase_orders', 'list_goods_received_notes', 'create_purchase_order_status']));
    expect(operations).not.toContain('get_customer');
    expect(metadata.nodeMeta.triggerOperations).toEqual([
        'on_new_or_updated_purchase_order', 'on_new_or_updated_goods_received_note',
    ]);
});
