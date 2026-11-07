import { describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/skuvault.json';
import { loadNodeSchemas, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

describe('SkuVault discovered schema and credentials', () => {
    it('discovers the token tuple and automatically selects its saved connection', async () => {
        await loadNodeSchemas(['automation-skuvault']);
        expect(getNodeCredentialInfo('automation-skuvault')).toMatchObject({
            providerKey: 'skuvault', acceptedTypes: ['skuvault_api_tokens'], label: 'SkuVault API Tokens',
        });
        expect(CREDENTIAL_TYPE_MAP.SkuVaultAPITokensCredential).toBe('skuvault_api_tokens');
        upsertCredentialsIntoCache([{ id: 'skuvault-test', name: 'SkuVault test', credential_type: 'skuvault_api_tokens', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache('automation-skuvault')).toEqual({ skuvault_api_tokens: 'skuvault-test' });
    });
    it('keeps required operation fields and token secrets in the generated schema', () => {
        const defs = schema.$defs;
        expect(defs.SkuVaultListKitsConfig.required).toEqual(expect.arrayContaining(['modified_after_utc', 'modified_before_utc']));
        expect(defs.SkuVaultListWarehouseItemQuantitiesConfig.required).toContain('warehouse_id');
        expect(defs.SkuVaultAPITokensCredential.properties.tenant_token['ui:widget']).toBe('password');
        expect(defs.SkuVaultAPITokensCredential.properties.user_token['ui:widget']).toBe('password');
        expect(defs.SkuVaultProductMetadata.additionalProperties).toBe(false);
    });
});
