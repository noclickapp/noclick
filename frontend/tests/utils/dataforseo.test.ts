// DataForSEO's actual schema, palette, credential label and owned selection.
import { beforeAll, describe, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/dataforseo.json';
import { DataForSEONode } from '~/components/workflow/nodes/integrations/dataforseo';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
vi.mock('~/lib/telemetry-errors', () => ({ reportInvariant: vi.fn() }));
beforeAll(() => loadNodeSchemas(['automation-dataforseo']));

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
    expect(requirementsFromSchema(schema).map(req => methodFromRequirement(req).method_kind)).toEqual(['api_key', 'mcp']); // and its MCP server, last
    expect(getNodeCredentialInfo('automation-dataforseo')?.acceptedTypes).toContain('dataforseo_basic');
    expect(AVAILABLE_NODES.some(node => node.type === DataForSEONode.type)).toBe(true);
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
