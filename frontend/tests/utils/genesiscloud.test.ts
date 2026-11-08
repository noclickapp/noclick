import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/genesiscloud.json';
import { GenesisCloudNode } from '~/components/workflow/nodes/integrations/genesiscloud';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

const type = 'automation-genesiscloud';
describe('Genesis Cloud self-registering integration', () => {
    beforeAll(() => loadNodeSchemas([type]));
    it('discovers its definition, schema, credential label and API key method', () => {
        expect(GenesisCloudNode.type).toBe(type);
        expect(NODE_SCHEMAS[type]).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.GenesisCloudAPITokenCredential).toBe('genesiscloud_api_token');
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['genesiscloud_api_token']);
        expect(humanizeCredentialLabel(schema.$defs.GenesisCloudAPITokenCredential.title)).toBe('Genesis Cloud API Token');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getAgentToolOperations(type)).toHaveLength(2);
    });
});
