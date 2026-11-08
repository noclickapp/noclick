// Fulcrum's generated schema drives the actual credential and config surfaces.
// These prepared fixtures retain form ancestry and intentional record PATCH values.
import { describe, expect, it } from 'vitest';
import { NODE_SCHEMAS, filterConfigForExecution, isTriggerSource, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

await loadNodeSchemas(['automation-fulcrum']);

describe('Fulcrum native credentials and form records', () => {
    it('offers the real organization token rather than a generic OAuth callback', () => {
        const schema = NODE_SCHEMAS['automation-fulcrum'];
        const credential = schema.$defs.FulcrumAPITokenCredential;
        expect(CREDENTIAL_TYPE_MAP[credential.title]).toBe('fulcrum_api_token');
        expect(humanizeCredentialLabel(credential.title)).toBe('Fulcrum API Token');
        expect(credential.required).toEqual(['api_token']);
        expect(credential.properties.api_token['ui:widget']).toBe('password');
        expect(credential.properties.api_token.minLength).toBe(1);
        expect(credential.properties.credential_type['ui:hidden']).toBe(true);
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(schema['x-agent-tool-provider']).toBe(true);
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0].credential_type).toBe('fulcrum_api_token');
        expect(methods[0].method_kind).toBe('api_key');
    });

    it('binds records and field keys to the selected form', () => {
        const fields = NODE_SCHEMAS['automation-fulcrum'].$defs.FulcrumSetRecordFieldConfig.properties;
        expect(fields.record_id['x-dynamic-options'].depends_on).toBe('form_id');
        expect(fields.field_key['x-dynamic-options'].depends_on).toBe('form_id');
        expect(fields.record_id['x-resource-type']).toBe('fulcrum_record');
        expect(fields.skip_workflows.default).toBe(true);
        expect(fields.skip_webhooks.default).toBe(true);
        expect(isTriggerSource('automation-fulcrum', 'list_records')).toBe(false);
    });

    it('preserves null field clearing and explicit permission for existing automation', () => {
        expect(filterConfigForExecution('automation-fulcrum', {
            operation: 'set_record_field', form_id: 'form', record_id: 'record', field_key: 'text',
            value: null, skip_workflows: false, skip_webhooks: false, name: 'stale project', choices: [],
        })).toEqual({ operation: 'set_record_field', form_id: 'form', record_id: 'record', field_key: 'text',
            value: null, skip_workflows: false, skip_webhooks: false });
    });

    it('keeps intentional empty replacement choices and record zero coordinates', () => {
        expect(filterConfigForExecution('automation-fulcrum', {
            operation: 'update_choice_list', choice_list_id: 'choices', choices: [], name: 'Retained',
            form_id: 'stale', latitude: 1,
        })).toEqual({ operation: 'update_choice_list', choice_list_id: 'choices', choices: [], name: 'Retained' });
        expect(filterConfigForExecution('automation-fulcrum', {
            operation: 'create_record', form_id: 'form', latitude: 0, longitude: 0,
            form_values: { text: '', number: '0' },
        })).toEqual({ operation: 'create_record', form_id: 'form', latitude: 0, longitude: 0,
            form_values: { text: '', number: '0' } });
    });
});
