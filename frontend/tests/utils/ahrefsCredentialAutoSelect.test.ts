import { describe, expect, it } from 'vitest';
import {
    autoSelectCredentialFromCache,
    upsertCredentialsIntoCache,
} from '~/utils/credentialAutoSelect';

describe('Ahrefs credential selection on canvas add', () => {
    it('selects the saved Ahrefs API key from the node schema', () => {
        upsertCredentialsIntoCache([{
            id: 'ahrefs-test-credential',
            name: 'Ahrefs test',
            credential_type: 'ahrefs_api_key',
            owned_by_me: true,
        }]);

        expect(autoSelectCredentialFromCache('automation-ahrefs')).toEqual({
            ahrefs_api_key: 'ahrefs-test-credential',
        });
    });
});
