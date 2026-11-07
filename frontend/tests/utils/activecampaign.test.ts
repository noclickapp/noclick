import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/activecampaign.json';
import meta from '~/schemas/nodeMeta/activecampaign.json';
import { ActiveCampaignNode } from '~/components/workflow/nodes/integrations/activecampaign';

describe('ActiveCampaign integration metadata', () => {
    it('offers the account API URL and API key as one API key connection', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['activecampaign_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(meta.credentialTypes.ActiveCampaignApiKeyCredential).toBe('activecampaign_api_key');
        expect(meta.credentialTypes['ActiveCampaign API Key']).toBe('activecampaign_api_key');
        expect(schema.$defs.ActiveCampaignApiKeyCredential.required).toEqual(['api_url', 'api_key']);
    });
    it('exposes the discovered canvas definition and contact poll trigger', () => {
        expect(ActiveCampaignNode.type).toBe('automation-activecampaign');
        expect(ActiveCampaignNode.label).toBe('ActiveCampaign');
        expect(meta.nodeMeta.triggerOperations).toEqual(['on_new_contact']);
        expect(meta.autoSelectCredential).toBe(true);
    });
});
