import { describe, expect, it } from 'vitest';
import {
    credentialRequirements,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';
import { SecurityTrailsNode } from '../../app/components/workflow/nodes/integrations/securitytrails';
import {
    getAgentToolOperations,
    getNodeCredentialInfo,
    loadNodeSchemas,
} from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-securitytrails']);

describe('SecurityTrails integration', () => {
    it('offers DNS intelligence, ASI asset search and asynchronous tag actions', () => {
        expect(SecurityTrailsNode.category).toBe('developer-tools');
        const operations = getAgentToolOperations(
            'automation-securitytrails'
        ).map((op) => op.operation);
        expect(operations).toHaveLength(22);
        expect(operations).toContain('get_dns_history');
        expect(operations).toContain('search_assets');
        expect(operations).toContain('apply_asset_tag');
        expect(operations).toContain('remove_asset_tag');
        expect(operations).toContain('get_tag_task');
    });

    it('connects with one manually pasted API key', () => {
        expect(
            credentialRequirements('automation-securitytrails').map(
                (r) => methodFromRequirement(r).method_kind
            )
        ).toEqual(['api_key']);
        expect(
            getNodeCredentialInfo('automation-securitytrails')?.acceptedTypes
        ).toContain('securitytrails_api_key');
    });
});
