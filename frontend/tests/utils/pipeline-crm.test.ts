import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/pipeline-crm.json';
import meta from '~/schemas/nodeMeta/pipeline-crm.json';

describe('Pipeline CRM credential metadata', () => {
    it('offers a pasted API token connection', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['pipeline_crm_api_token']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(meta.credentialTypes['Pipeline CRM API Token']).toBe('pipeline_crm_api_token');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
