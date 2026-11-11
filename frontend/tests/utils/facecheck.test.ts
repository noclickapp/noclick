import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { FaceCheckNode } from '../../app/components/workflow/nodes/integrations/facecheck';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-facecheck']);

describe('FaceCheck integration', () => {
    it('exposes the published API actions and its category', () => {
        expect(FaceCheckNode.category).toBe('ai');
        expect(getAgentToolOperations('automation-facecheck').map(op => op.operation).sort()).toEqual(
            ['delete_image', 'get_info', 'get_search_status', 'search', 'upload_image']);
    });
    it('supports a manually pasted API token', () => {
        expect(credentialRequirements('automation-facecheck').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-facecheck')?.acceptedTypes).toContain('facecheck_api_token');
    });
});
