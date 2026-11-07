// DataForSEO's actual schema, palette, credential label and owned selection.
// These fixture sources await generated schema and a root frontend test lane.
import { afterEach, describe, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/dataforseo.json';
import { DataForSEONode } from '~/components/workflow/nodes/integrations/dataforseo';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { autoSelectCredentialFromCache, invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
vi.mock('~/utils/credentialTypes', async () => ({ CREDENTIAL_TYPE_MAP: (await import('~/utils/credentialTypeMap')).CREDENTIAL_TYPE_MAP }));
vi.mock('~/lib/telemetry-errors', () => ({ reportInvariant: vi.fn() }));
afterEach(() => invalidateCredentialsCache());

describe('DataForSEO native wiring', () => {
  it('keeps API Basic credentials separate from console passwords and OAuth', () => {
    const def = schema.$defs.DataForSEOAPICredential;
    expect(def.title).toBe('DataForSEO API Login');
    expect(humanizeCredentialLabel(def.title)).toBe('DataForSEO API Login');
    expect(getCredentialTypeFromSchemaTitle(def.title)).toBe('dataforseo_basic');
    expect(getCredentialTypeFromSchemaTitle('DataForSEOAPICredential')).toBe('dataforseo_basic');
    expect(def.required).toEqual(expect.arrayContaining(['api_login', 'api_password']));
    expect(def.properties.api_password['ui:widget']).toBe('password');
    expect(def).not.toHaveProperty('x-oauth-provider');
    expect(getNodeCredentialInfo('automation-dataforseo')?.acceptedTypes).toContain('dataforseo_basic');
    expect(AVAILABLE_NODES.some(node => node.type === DataForSEONode.type)).toBe(true);
  });
  it('selects the owned API connection', () => {
    upsertCredentialsIntoCache([
      { id: 'other', name: 'Collaborator', credential_type: 'dataforseo_basic', owned_by_me: false },
      { id: 'owned', name: 'Owned API', credential_type: 'dataforseo_basic', owned_by_me: true },
    ]);
    expect(autoSelectCredentialFromCache('automation-dataforseo')).toEqual({ dataforseo_basic: 'owned' });
  });
  it('exposes fifteen concrete operations with locale parents and actual receipt path', () => {
    const defs = Object.values(schema.$defs) as Array<{ properties?: Record<string, unknown> }>;
    const operations = defs.filter(def => def.properties?.operation);
    expect(operations).toHaveLength(15);
    expect(schema.$defs.DataForSEOSubmitSerp.properties.operation['x-resource-id-path']).toBe('data.task_id');
    expect(schema.$defs.DataForSEOGetSerp.properties.task_id['x-resource-type']).toBe('dataforseo_serp_task');
    expect(schema.$defs.DataForSEOSubmitSerp.properties.serp_location_code['x-dynamic-options'].depends_on).toEqual(['country_code']);
    expect(schema.$defs.DataForSEORelatedKeywords.properties.labs_language_code['x-dynamic-options'].depends_on).toEqual(['labs_location_code']);
    for (const def of operations) {
      expect(def.properties).not.toHaveProperty('endpoint');
      expect(def.properties).not.toHaveProperty('postback_url');
      expect(def.properties).not.toHaveProperty('model');
    }
  });
});
