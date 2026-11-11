// Covers the actual Sling schema and credential consumers after generation.
// These source fixtures do not establish real account or canvas behavior.
import { beforeAll, describe, expect, it } from 'vitest';
import { SlingNode } from '~/components/workflow/nodes/integrations/sling';
import { getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

describe('Sling native wiring', () => {
  beforeAll(() => loadNodeSchemas(['automation-sling']));
  it('discovers the raw user-token family and required resource parent', () => {
    expect(SlingNode.type).toBe('automation-sling');
    expect(getNodeCredentialInfo(SlingNode.type)?.acceptedTypes).toEqual(['sling_user_token']);
    expect(CREDENTIAL_TYPE_MAP.SlingUserTokenCredential).toBe('sling_user_token');
    const credential = NODE_SCHEMAS[SlingNode.type].$defs.SlingUserTokenCredential;
    expect(credential.required).toEqual(expect.arrayContaining(['token', 'organization_id']));
    expect(credential.properties.token['ui:widget']).toBe('password');
    expect(credential['x-oauth-provider']).toBeUndefined();
    expect(credential['x-credential-type']).toBe('api_key');
    expect(humanizeCredentialLabel('SlingUserToken')).toBe('Sling User Token');
  });

  it('keeps the bounded calendar and seven read operations', () => {
    const defs = NODE_SCHEMAS[SlingNode.type].$defs;
    expect(defs.ListCalendarEvents.required).toEqual(expect.arrayContaining(['user_id', 'start', 'end']));
    expect(defs.ListCalendarEvents.properties.page_size.maximum).toBe(100);
    expect(defs.ListCalendarEvents.properties).not.toHaveProperty('organization_id');
    const operations = Object.values(defs).flatMap((definition: any) => definition.properties?.operation?.const ? [definition.properties.operation.const] : []);
    expect(operations.sort()).toEqual(['get_group', 'get_organization', 'get_user', 'list_calendar_events', 'list_group_users', 'list_groups', 'list_users']);
    expect(defs.GetGroup.properties.group_id['x-dynamic-options'].field_name).toBe('group_id');
  });
});
