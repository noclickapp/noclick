import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/centralstationcrm.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES, isAgentToolProviderType } from '~/utils/nodeMeta';

describe('CentralStationCRM credential discovery', () => {
    it('offers the discovered API key method and maps credential aliases', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-centralstationcrm');
        expect(isAgentToolProviderType('automation-centralstationcrm')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.CentralStationCRMApiKeyCredential).toBe('centralstationcrm_api_key');
        expect(CREDENTIAL_TYPE_MAP['CentralStationCRM API Key']).toBe('centralstationcrm_api_key');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['centralstationcrm_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
});
