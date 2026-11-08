// Verify discovery and the account-key connection form for YouCanBookMe.
// This catches metadata regressions that could render the credential as OAuth.
import { beforeAll, describe, expect, it } from 'vitest';
import { NODE_DEFINITION_FILES } from '~/components/workflow/nodes/nodeDefinitions';
import { loadNodeSchemas, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';

beforeAll(() => loadNodeSchemas(['automation-youcanbookme']));

describe('YouCanBookMe integration', () => {
    it('discovers the definition and the issued API-key method', () => {
        expect(NODE_DEFINITION_FILES).toContainEqual(['automation-youcanbookme', 'integrations/youcanbookme']);
        expect(getNodeCredentialInfo('automation-youcanbookme')?.acceptedTypes).toEqual(['youcanbookme_api_key']);
        const methods = credentialRequirements('automation-youcanbookme').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0].method_kind).toBe('api_key');
        expect(methods[0].is_oauth).toBe(false);
        expect(getCredentialTypeFromSchemaTitle('YouCanBookMe Account API Key')).toBe('youcanbookme_api_key');
    });
});
