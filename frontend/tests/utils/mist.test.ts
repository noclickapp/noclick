import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { MistNode } from '~/components/workflow/nodes/integrations/mist';

describe('Mist integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-mist']));
    it('offers a manually connected API token', async () => {
        const { default: schema } = await import('~/schemas/nodes/mist.json');
        expect(MistNode.category).toBe('monitoring');
        expect(getNodeCredentialInfo('automation-mist')?.acceptedTypes).toEqual(['mist_api_token']);
        expect(requirementsFromSchema(schema).map(methodFromRequirement)).toEqual([
            expect.objectContaining({ method_kind: 'api_key', is_oauth: false }),
        ]);
    });
    it('exposes the 20 account, network and alarm tools', () => {
        const ops = getAgentToolOperations('automation-mist').map(op => op.operation);
        expect(ops).toHaveLength(20);
        expect(ops).toEqual(expect.arrayContaining(['get_account', 'create_site', 'create_wlan', 'restart_device', 'acknowledge_alarm']));
        expect(ops).not.toContain('on_alarm');
    });
});
