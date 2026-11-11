// These fixtures exercise real credential/schema/execution consumers.
// The schema is loaded through staging's lazy node schema store.
import { describe, expect, it } from 'vitest';
import { NODE_SCHEMAS, filterConfigForExecution, isTriggerSource, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

await loadNodeSchemas(['automation-websupport']);

describe('Websupport signed DNS metadata', () => {
    it('requires an existing key/secret and explicit service without OAuth or an invented principal', () => {
        const schema = NODE_SCHEMAS['automation-websupport'];
        const cred = schema.$defs.WebsupportApiKeyCredential;
        expect(cred.required).toEqual(['api_key', 'api_secret', 'service_id']);
        expect(cred.properties.api_secret['ui:widget']).toBe('password');
        expect(CREDENTIAL_TYPE_MAP[cred.title]).toBe('websupport_api_key');
        expect(humanizeCredentialLabel(cred.title.replace('Credential', ''))).toBe('Websupport API Key');
        expect(cred['x-oauth-provider']).toBeUndefined();
        expect(cred.properties.owner).toBeUndefined();
        expect(schema['x-agent-tool-provider']).toBe(true);
    });
    it('selects only current record types under the saved service with bounded local output', () => {
        const defs = NODE_SCHEMAS['automation-websupport'].$defs;
        expect(defs.WebsupportRecordsConfig.properties.record_type['x-dynamic-options'].field).toBe('record_type');
        expect(defs.WebsupportRecordsConfig.properties.max_items.maximum).toBe(100);
        expect(defs.WebsupportRecordsConfig.properties.include_names.default).toBe(false);
        expect(defs.WebsupportRecordsConfig.properties.page).toBeUndefined();
        expect(isTriggerSource('automation-websupport', 'list_records')).toBe(false);
    });
    it('drops the record selector when switching to zone metadata', () => {
        expect(filterConfigForExecution('automation-websupport', { operation: 'get_zone', record_type: 'A',
            include_names: false }))
            .toEqual({ operation: 'get_zone', include_names: false });
    });
});
