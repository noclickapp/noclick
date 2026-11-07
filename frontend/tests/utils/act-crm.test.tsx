import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import schema from '~/schemas/nodes/act-crm.json';
import { ActCRMNode } from '~/components/workflow/nodes/integrations/act-crm';
import { NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { isAgentToolProviderType, isTriggerSource } from '~/utils/nodeMeta';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { kindFromCredentialType } from '~/lib/credentialMethodKind';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

await loadNodeSchemas(['automation-act-crm']);

describe('Act CRM native integration', () => {
    it('discovers the schema and issued JWT credential with all native operations', () => {
        expect(NODE_SCHEMAS['automation-act-crm']).toEqual(schema);
        const credential = schema.$defs.ActCRMJWTCredential;
        expect(CREDENTIAL_TYPE_MAP[credential.title]).toBe('act_crm_jwt');
        expect(credential.properties.access_token['ui:widget']).toBe('password');
        expect(credential.required).toEqual(['instance_url', 'database_name', 'access_token']);
        expect(kindFromCredentialType(undefined)).toBe('api_key');
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(31);
        expect(schema.$defs.Note.properties.note_id['x-dynamic-options'].depends_on).toBe('contact_id');
        expect(isAgentToolProviderType(ActCRMNode.type)).toBe(true);
        expect(isTriggerSource(ActCRMNode.type, 'list_contacts')).toBe(false);
    });
    it('selects the native saved connection with staging credential selection', () => {
        upsertCredentialsIntoCache([{ id: 'act-crm-owned', name: 'Act CRM fixture', credential_type: 'act_crm_jwt', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache('automation-act-crm')).toEqual({ act_crm_jwt: 'act-crm-owned' });
        removeCredentialsFromCache(['act-crm-owned']);
    });
    it('renders the official vector used by the original integration', () => {
        expect(renderToStaticMarkup(<ActCRMNode.Icon />)).toContain('/icons/act-crm-brand-vector.svg');
    });
});
