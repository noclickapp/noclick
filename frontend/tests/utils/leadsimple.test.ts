// LeadSimple uses one manually entered bearer token for all REST operations.
// Guard generated discovery, credential fields and the catalog category.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/leadsimple.json';
import { LeadSimpleNode } from '~/components/workflow/nodes/integrations/leadsimple';

describe('LeadSimple', () => {
    it('discovers one manual token method', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-leadsimple');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'leadsimple_api_token', method_kind: 'api_key', is_oauth: false,
        });
        expect(schema.$defs.LeadSimpleTokenCredential.required).toEqual(['api_token']);
        expect(schema.$defs.LeadSimpleTokenCredential.properties.credential_type.default).toBe('leadsimple_api_token');
        expect(schema.$defs.LeadSimpleCreateContactConfig.properties.email_addresses['ui:widget']).toBe('list');
        expect(LeadSimpleNode.category).toBe('crm-sales');
    });
});
