import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-event-tickets']);

describe('Event Tickets manual connection', () => {
    it('offers the application password and all required fields', () => {
        const methods = credentialRequirements('automation-event-tickets').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'event_tickets_application_password', method_kind: 'api_key', is_oauth: false });
        expect(methods[0].credential_fields?.map(f => f.name)).toEqual(['site_url', 'username', 'application_password']);
    });
});
