// Verifies discovery of Encharge through generated schemas and metadata.
// Ensures its account API key is offered as a manually pasted connection.
import { beforeAll, expect, it } from 'vitest';
import { EnchargeNode } from '~/components/workflow/nodes/integrations/encharge';
import {
    credentialRequirements,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-encharge']));
it('discovers Encharge and offers its pasted API key', () => {
    expect(EnchargeNode.type).toBe('automation-encharge');
    const methods = credentialRequirements(EnchargeNode.type).map(
        methodFromRequirement
    );
    expect(methods).toHaveLength(1);
    expect(methods[0].credential_type).toBe('encharge_api_key');
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map((field) => field.name)).toEqual([
        'api_key',
    ]);
});
