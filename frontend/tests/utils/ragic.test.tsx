// Generated Ragic schema and discovered node definition.
// Scope is read-only projected data; source fixtures never prove a real key/private sheet.
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import schema from '~/schemas/nodes/ragic.json';
import { RagicNode } from '~/components/workflow/nodes/integrations/ragic';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { isAgentToolProviderType, isTriggerSource } from '~/utils/nodeMeta';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
await loadNodeSchemas(['automation-ragic']);
describe('native Ragic scoped reads',()=>{
    it('exposes exact four operations, raw key family, explicit projection and current picker dependency',()=>{
        expect(NODE_SCHEMAS['automation-ragic']).toBe(schema);
        expect(getNodeCredentialInfo('automation-ragic')).toEqual({providerKey:'ragic',acceptedTypes:['ragic_api_key'],label:'Ragic API Key'});
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(schema.$defs.RagicAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
        expect(schema.$defs.RagicAPIKeyCredential.properties.credential_type.const).toBe('ragic_api_key');
        expect(schema.$defs.RagicAPIKeyCredential).not.toHaveProperty('x-oauth-provider');
        expect(Object.keys(schema.properties.config.discriminator.mapping).sort()).toEqual(['check_connection','get_record','list_records','search_records']);
        expect(schema.$defs.ListRecords.required).toContain('field_ids');
        expect(schema.$defs.ListRecords.required).toContain('confirm_safe_fields');
        expect(schema.$defs.ListRecords.properties.limit.maximum).toBe(1000);
        expect(schema.$defs.ListRecords.properties).not.toHaveProperty('offset');
        expect(schema.$defs.SearchRecords.properties).not.toHaveProperty('sql');
        expect(schema.$defs.GetRecord.properties.record_id['x-dynamic-options']).toMatchObject({field_name:'record_id',depends_on:'field_ids',allow_custom:true});
        expect(isAgentToolProviderType(RagicNode.type)).toBe(true);
        expect(isTriggerSource(RagicNode.type,'list_records')).toBe(false);
    });
    it('renders the exact unchanged official WebP asset',()=>{
        const Icon = RagicNode.Icon;
        expect(renderToStaticMarkup(<Icon />)).toContain('/icons/ragic.webp');
    });
});
