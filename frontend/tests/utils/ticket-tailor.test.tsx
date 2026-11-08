import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/ticket-tailor.json';
import { TicketTailorNode } from '~/components/workflow/nodes/integrations/ticket-tailor';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

const type = 'automation-ticket-tailor';
describe('Ticket Tailor self-registering integration', () => {
    beforeAll(() => loadNodeSchemas([type]));
    it('discovers its API key method and selects a saved key', () => {
        expect(TicketTailorNode.type).toBe(type);
        expect(NODE_SCHEMAS[type]).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.TicketTailorCredential).toBe('ticket_tailor');
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['ticket_tailor']);
        expect(humanizeCredentialLabel(schema.$defs.TicketTailorCredential.title)).toBe('Ticket Tailor API Key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(schema.$defs.TicketTailorCredential.properties.api_key['ui:widget']).toBe('password');
        upsertCredentialsIntoCache([{id: 'ticket-tailor-test-key', name: 'Box office key', credential_type: 'ticket_tailor', owned_by_me: true}]);
        expect(autoSelectCredentialFromCache(type)).toEqual({ticket_tailor: 'ticket-tailor-test-key'});
    });
    it('exposes fourteen operations with parent-bound report pickers', () => {
        expect(getAgentToolOperations(type)).toHaveLength(14);
        expect(schema.$defs.GetTicket.properties.ticket_id['x-dynamic-options']).toMatchObject({field_name: 'ticket_id', depends_on: 'event_id', allow_custom: true});
        expect(schema.$defs.GetSeriesEvent.properties.occurrence_id['x-dynamic-options']).toMatchObject({depends_on: 'event_series_id'});
    });
});
