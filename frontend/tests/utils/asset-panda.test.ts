import { beforeAll, describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '../../app/schemas/nodes/asset-panda.json';
import { NODE_SCHEMAS, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

describe('Asset Panda Pioneer native contracts', () => {
    beforeAll(() => loadNodeSchemas(['automation-asset-panda']));
    it('registers the exact native schema and manual access-key family', () => {
        expect(NODE_SCHEMAS['automation-asset-panda']).toBe(schema);
        expect(CREDENTIAL_TYPE_MAP.AssetPandaAccessKeyCredential).toBe('asset_panda_access_key');
        expect(humanizeCredentialLabel(schema.$defs.AssetPandaAccessKeyCredential.title)).toBe('Asset Panda Access Key');
        const credential = schema.$defs.AssetPandaAccessKeyCredential;
        expect(credential.properties.access_key_id['ui:widget']).toBe('password');
        expect(credential.properties.access_key_secret['ui:widget']).toBe('password');
        expect(credential.required).toEqual(expect.arrayContaining(['access_key_id', 'access_key_secret', 'account_id']));
        expect(JSON.stringify(credential)).not.toContain('x-oauth-provider');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    });
    it('keeps closed read operations, real dependent fields and documented search bounds', () => {
        const definitions = schema.$defs;
        const actions = Object.values(definitions as Record<string, { properties?: Record<string, { const?: string }> }>).filter(value => value.properties?.operation);
        expect(actions).toHaveLength(9);
        expect(actions.map(value => value.properties?.operation.const).sort()).toEqual([
            'get_account', 'get_collection', 'get_collection_record', 'get_module', 'list_accounts',
            'list_collection_columns', 'list_collections', 'list_modules', 'search_collection_records',
        ].sort());
        expect(definitions.SearchRecords.properties.column_id['x-dynamic-options'].depends_on).toEqual(['module_id', 'collection_id']);
        expect(definitions.SearchRecords.properties.page_size.maximum).toBe(100);
        expect(definitions.ListCollections.properties.include_names.default).toBe(false);
        expect(JSON.stringify(schema)).not.toContain('raw_request');
    });
});
