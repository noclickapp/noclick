// BigCommerce nodes should select the viewer's saved store token when added.
// This exercises the schema and credential maps used by the canvas.
import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('BigCommerce credential selection', () => {
    it('selects a saved store API token', async () => {
        await loadNodeSchemas(['automation-bigcommerce']);
        upsertCredentialsIntoCache([{
            id: 'bigcommerce-test', name: 'BigCommerce test',
            credential_type: 'bigcommerce_api_token', owned_by_me: true,
        }]);
        expect(autoSelectCredentialFromCache('automation-bigcommerce')).toEqual({
            bigcommerce_api_token: 'bigcommerce-test',
        });
    });
});
