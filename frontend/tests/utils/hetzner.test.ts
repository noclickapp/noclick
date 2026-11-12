import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/hetzner.json';
import { HetznerNode } from '~/components/workflow/nodes/integrations/hetzner';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

const type = 'automation-hetzner';
describe('Hetzner Cloud registration', () => {
    beforeAll(() => loadNodeSchemas([type]));
    it('discovers the cloud category, manual API token and actions', () => {
        expect(HetznerNode.type).toBe(type);
        expect(HetznerNode.category).toBe('cloud-hosting');
        expect(NODE_SCHEMAS[type]).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.HetznerAPITokenCredential).toBe('hetzner_api_token');
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['hetzner_api_token']);
        expect(humanizeCredentialLabel(schema.$defs.HetznerAPITokenCredential.title)).toBe('Hetzner Cloud API Token');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getAgentToolOperations(type)).toHaveLength(24);
        expect(getAgentToolOperations(type).every(op => op.displayName !== 'Operation')).toBe(true);
    });
});
