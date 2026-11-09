import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';

beforeAll(() => loadNodeSchemas(['automation-tailscale']));
it('offers a manually connected API token with the Tailscale label', () => {
    const schema = getNodeSchema('automation-tailscale');
    expect(getNodeCredentialInfo('automation-tailscale')?.acceptedTypes).toEqual(['tailscale_api_token']);
    expect(getNodeCredentialInfo('automation-tailscale')?.label).toBe('Tailscale API Token');
    expect(methodFromRequirement(requirementsFromSchema(schema)[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    expect(getCredentialTypeFromSchemaTitle('Tailscale API Token')).toBe('tailscale_api_token');
});
it('makes the 21 read and write operations available to agents', () => {
    const operations = getAgentToolOperations('automation-tailscale').map(op => op.operation);
    expect(operations).toHaveLength(21);
    expect(operations).toContain('list_devices');
    expect(operations).toContain('set_device_routes');
    expect(operations).toContain('set_dns_preferences');
    expect(operations).toContain('delete_key');
});
