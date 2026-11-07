// These tests exercise native schema discovery and credential selection.
// They do not establish real editor persistence or provider access.
import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/oracle-field-service.json';
import { CREDENTIAL_TYPE_MAP } from '../../app/utils/credentialTypeMap';

describe('Oracle Field Service native contract', () => {
    it('has exactly 17 closed actions and no technician lifecycle action', () => {
        const defs = schema.$defs as Record<string, any>;
        const actions = schema.properties.config.oneOf.map((choice: any) => defs[choice.$ref.split('/').pop()].properties.operation.const);
        expect(new Set(actions).size).toBe(17);
        expect(actions).toContain('delete_nonscheduled_activity');
        expect(actions).toContain('get_available_capacity');
        expect(actions).not.toContain('cancel_activity');
        expect(actions).not.toContain('start_activity');
        expect(defs.GetActivity.properties.activity_id['x-dynamic-options'].depends_on).toBe('resource_id');
    });
    it('keeps application Basic and supplied OAuth bearer credentials distinct', () => {
        expect(CREDENTIAL_TYPE_MAP.OracleFieldServiceBasicCredential).toBe('oracle_field_service_basic');
        expect(CREDENTIAL_TYPE_MAP.OracleFieldServiceBearerCredential).toBe('oracle_field_service_bearer');
        const defs = schema.$defs as Record<string, any>;
        expect(defs.OracleFieldServiceBasicCredential.properties.client_secret['ui:widget']).toBe('password');
        expect(defs.OracleFieldServiceBearerCredential.properties.access_token['ui:widget']).toBe('password');
        expect(defs.OracleFieldServiceBearerCredential.properties.refresh_token).toBeUndefined();
        expect(defs.OracleFieldServiceBearerCredential.properties['x-oauth']).toBeUndefined();
    });
});
