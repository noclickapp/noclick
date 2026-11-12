import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { LambdaTestNode } from '../../app/components/workflow/nodes/integrations/lambdatest';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-lambdatest']);

describe('LambdaTest integration', () => {
    it('discovers all nine published Screenshots operations', () => {
        expect(LambdaTestNode.category).toBe('developer-tools');
        expect(LambdaTestNode.keywords).toContain('TestMu AI');
        expect(getAgentToolOperations('automation-lambdatest').map(op => op.operation).sort()).toEqual([
            'get_screenshot_zip', 'get_screenshots', 'list_browsers', 'list_devices',
            'list_locations', 'list_profiles', 'list_resolutions', 'start_screenshot_test', 'stop_screenshot_test',
        ]);
    });

    it('offers a manually connected access key without an OAuth flow', () => {
        expect(credentialRequirements('automation-lambdatest').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-lambdatest')?.acceptedTypes).toContain('lambdatest_access_key');
    });
});
