import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/salesrobot.json';
import meta from '~/schemas/nodeMeta/salesrobot.json';

describe('SalesRobot manual connection metadata', () => {
    it('offers an API key connection with all required fields visible to a person', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['salesrobot_api_key']);
        expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        const credential = schema.$defs.SalesrobotAPIKeyCredential;
        expect(credential.required).toEqual(['api_key', 'linkedin_account_uuid']);
        expect(credential.properties.credential_type.default).toBe('salesrobot_api_key');
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential.properties.linkedin_account_uuid.title).toBe('LinkedIn Account UUID');
        expect(meta.credentialTypes['Salesrobot API Key']).toBe('salesrobot_api_key');
        expect(meta.autoSelectCredential).toBe(true);
    });
    it('publishes exactly the twenty fixed provider operations', () => {
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(20);
        expect(schema.properties.config.discriminator.mapping).toHaveProperty('send_message');
        expect(schema.properties.config.discriminator.mapping).toHaveProperty('list_campaigns');
    });
});
