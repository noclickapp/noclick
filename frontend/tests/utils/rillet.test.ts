import { beforeAll, expect, it } from 'vitest';
import { RilletNode } from '~/components/workflow/nodes/integrations/rillet';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/rillet.json';

beforeAll(() => loadNodeSchemas([RilletNode.type]));
it('discovers Rillet in accounting with one masked API key connection method', () => {
    expect(RilletNode.category).toBe('finance-accounting');
    expect(getNodeCredentialInfo(RilletNode.type)).toBeTruthy();
    expect(CREDENTIAL_TYPE_MAP['Rillet API Key']).toBe('rillet_api_key');
    expect(NODE_SCHEMAS[RilletNode.type]).toBe(schema);
    const requirements = credentialRequirements(RilletNode.type);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    const form = schema.$defs.RilletAPIKeyCredential;
    expect(form.properties.api_key['ui:widget']).toBe('password');
    expect(form.properties.environment.enum).toEqual(['production', 'sandbox']);
    expect(form).not.toHaveProperty('x-oauth-provider');
});
