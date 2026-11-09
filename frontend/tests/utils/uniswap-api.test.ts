import { describe, expect, it } from 'vitest';
import {
    credentialRequirements,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';
import { UniswapAPINode } from '../../app/components/workflow/nodes/integrations/uniswap-api';
import {
    getAgentToolOperations,
    getNodeCredentialInfo,
    loadNodeSchemas,
} from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-uniswap-api']);
describe('Uniswap API integration', () => {
    it('discovers trading operations in the finance category', () => {
        expect(UniswapAPINode.type).toBe('automation-uniswap-api');
        expect(UniswapAPINode.category).toBe('finance-accounting');
        const operations = getAgentToolOperations('automation-uniswap-api').map(
            (o) => o.operation
        );
        expect(operations).toHaveLength(10);
        expect(operations).toContain('create_order');
        expect(operations).toContain('create_swap');
        expect(operations).toContain('get_quote');
        expect(operations).toContain('check_approval');
    });
    it('offers a manually pasted API key', () => {
        expect(
            credentialRequirements('automation-uniswap-api').map(
                (r) => methodFromRequirement(r).method_kind
            )
        ).toEqual(['api_key']);
        expect(
            getNodeCredentialInfo('automation-uniswap-api')?.acceptedTypes
        ).toContain('uniswap_api_key');
    });
});
