// Verifies that adding a Dialpad node selects a saved Dialpad API key.
// Exercises the lazy schema path used by the workflow canvas.
import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';

describe('Dialpad credential selection on canvas add', () => {
    it('selects the saved Dialpad API key from the node schema', async () => {
        await loadNodeSchemas(['automation-dialpad']);
        upsertCredentialsIntoCache([{
            id: 'dialpad-test-credential',
            name: 'Dialpad test',
            credential_type: 'dialpad_api_key',
            owned_by_me: true,
        }]);

        expect(autoSelectCredentialFromCache('automation-dialpad')).toEqual({
            dialpad_api_key: 'dialpad-test-credential',
        });
    });
});
