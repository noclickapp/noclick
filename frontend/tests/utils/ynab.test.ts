// YNAB uses the shared schema and credential metadata discovery paths.
// These checks pin the personal-token form and the node's public catalog entry.
import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import schema from '~/schemas/nodes/ynab.json';
import { YnabNode } from '~/components/workflow/nodes/integrations/ynab';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';

describe('YNAB integration', () => {
    beforeAll(() => loadNodeSchemas([YnabNode.type]));
    it('discovers the node and its personal access token', () => {
        expect(YnabNode.type).toBe('automation-ynab');
        expect(YnabNode.label).toBe('YNAB');
        expect(NODE_SCHEMAS[YnabNode.type]).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.YnabPersonalAccessTokenCredential).toBe('ynab_personal_access_token');
        const form = schema.$defs.YnabPersonalAccessTokenCredential;
        expect(form.properties.access_token['ui:widget']).toBe('password');
        expect(form['x-credential-url']).toBe('https://app.ynab.com/settings/developer');
        expect(form).not.toHaveProperty('x-oauth-provider');
    });
    it('offers one manual API token method and 25 distinct actions', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'ynab_personal_access_token', method_kind: 'api_key', is_oauth: false });
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(25);
    });
});
