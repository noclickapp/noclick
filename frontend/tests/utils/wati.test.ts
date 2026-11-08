import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { WATINode } from '../../app/components/workflow/nodes/integrations/wati';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '../../app/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '../../app/utils/credentialTypeMap';

await loadNodeSchemas(['automation-wati']);

describe('WATI self-registering integration', () => {
    it('discovers the issued token method and operations', () => {
        expect(WATINode.type).toBe('automation-wati');
        expect(getNodeCredentialInfo(WATINode.type)?.acceptedTypes).toEqual(['wati_api_access_token']);
        expect(getCredentialTypeFromSchemaTitle('WATI API Access Token')).toBe('wati_api_access_token');
        expect(credentialRequirements(WATINode.type).map(req => methodFromRequirement(req).method_kind)).toEqual(['api_key']);
        expect(getAgentToolOperations(WATINode.type).map(op => op.operation).sort()).toEqual([
            'create_contact', 'get_campaign', 'get_contact', 'get_contact_count', 'get_segment', 'get_template',
            'list_campaigns', 'list_channels', 'list_contacts', 'list_message_metadata', 'list_segments',
            'list_templates', 'soft_delete_contact', 'test_connection', 'update_contact_attributes',
        ]);
    });
    it('keeps explicit mutation confirmation and private-name defaults', () => {
        const defs = NODE_SCHEMAS[WATINode.type].$defs;
        expect(defs.WATIDeleteContactConfig.properties.confirm_changes.default).toBe(false);
        expect(defs.WATIUpdateContactConfig.properties.confirm_changes.default).toBe(false);
        expect(defs.WATIListContactsConfig.properties.include_names.default).toBe(false);
        expect(defs.WATIApiAccessTokenCredential).not.toHaveProperty('x-oauth-provider');
    });
});
