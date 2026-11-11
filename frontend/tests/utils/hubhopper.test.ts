import { describe, expect, it } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { HubhopperNode } from '~/components/workflow/nodes/integrations/hubhopper';
import { loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';

describe('Hubhopper hand connection', () => {
    it('offers a manual API key with both required header values', async () => {
        await loadNodeSchemas(['automation-hubhopper']);
        const schema = NODE_SCHEMAS['automation-hubhopper'];
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'hubhopper_api_key',
            method_kind: 'api_key',
            is_oauth: false,
        });
        const credential = schema.$defs.HubhopperAPIKeyCredential;
        expect(credential.required).toEqual(['api_key', 'partner_id']);
        expect(credential.properties.credential_type.default).toBe(
            'hubhopper_api_key'
        );
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential.properties.partner_id['ui:widget']).toBe('password');
        expect(HubhopperNode.category).toBe('media');
    });
});
