import { beforeAll, describe, expect, it } from 'vitest';
import { ExtoleNode } from '~/components/workflow/nodes/integrations/extole';
import { NODE_SCHEMAS, loadNodeSchemas, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

const TYPE = 'automation-extole', FAMILY = 'extole_access_token';
describe('Extole native credentials', () => {
  beforeAll(() => loadNodeSchemas([TYPE]));
  it('discovers its definition, schema and exact credential aliases', () => {
    expect(ExtoleNode.type).toBe(TYPE);
    expect(ExtoleNode.label).toBe('Extole');
    expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual([FAMILY]);
    expect(getNodeCredentialInfo(TYPE)?.label).toBe('Extole Access Token');
    expect(getCredentialTypeFromSchemaTitle('ExtoleAccessTokenCredential')).toBe(FAMILY);
    expect(getCredentialTypeFromSchemaTitle('Extole Access Token')).toBe(FAMILY);
    const credential = NODE_SCHEMAS[TYPE].$defs.ExtoleAccessTokenCredential;
    expect(credential.required).toContain('access_token');
    expect(credential.properties.access_token['ui:widget']).toBe('password');
    expect(credential['x-oauth-provider']).toBeUndefined();
  });
  it('selects only owned Extole credentials', () => {
    upsertCredentialsIntoCache([{ id: 'extole-foreign', name: 'Other owner', credential_type: FAMILY, owned_by_me: false }]);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({});
    upsertCredentialsIntoCache([{ id: 'extole-owned', name: 'Client token', credential_type: FAMILY, owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({ [FAMILY]: 'extole-owned' });
    removeCredentialsFromCache(['extole-owned', 'extole-foreign']);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({});
  });
});
