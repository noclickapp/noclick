import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Statuspage credential selection on canvas add', () => {
    it('selects the saved Statuspage API key from the node schema', async () => {
        await loadNodeSchemas(['automation-statuspage']);
        upsertCredentialsIntoCache([{
            id: 'statuspage-test-credential',
            name: 'Statuspage test',
            credential_type: 'statuspage_api_key',
            owned_by_me: true,
        }]);

        expect(autoSelectCredentialFromCache('automation-statuspage')).toEqual({
            statuspage_api_key: 'statuspage-test-credential',
        });
    });
});
