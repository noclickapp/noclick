import { beforeAll, describe, expect, it } from 'vitest';
import { HospitableNode } from '~/components/workflow/nodes/integrations/hospitable';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Hospitable integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-hospitable']));
    it('offers a manual token connection in bookings', () => {
        const schema = NODE_SCHEMAS['automation-hospitable'];
        expect(HospitableNode.category).toBe('bookings');
        expect(getNodeCredentialInfo('automation-hospitable')?.acceptedTypes).toEqual(['hospitable_api_token', 'hospitable_mcp']); // and its vendor's MCP server, last (backend nodes/core/vendor_mcp.py)
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(schema.$defs.HospitableTokenCredential.title).toBe('Hospitable Personal Access Token');
        expect(schema.$defs.HospitableTokenCredential.properties.api_token['ui:widget']).toBe('password');
    });
    it('exposes the 22 fixed hosting operations', () => {
        expect(getAgentToolOperations('automation-hospitable').map(op => op.operation).sort()).toEqual([
            'cancel_reservation', 'create_reservation', 'create_task', 'delete_task', 'get_calendar',
            'get_inquiry', 'get_property', 'get_reservation', 'get_task', 'get_user', 'list_inquiries',
            'list_properties', 'list_reservation_messages', 'list_reservations', 'list_reviews', 'list_tasks',
            'list_teammates', 'respond_review', 'send_inquiry_message', 'send_reservation_message',
            'update_calendar', 'update_task',
        ]);
    });
});
