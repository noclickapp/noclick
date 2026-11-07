// Checks the saved-token selection exposed by Coda's generated metadata.
// This keeps the integration usable without changing shared credential mappings.
import { expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
await loadNodeSchemas(['automation-coda']);
it('selects a saved Coda token for a new Coda node', () => {
    upsertCredentialsIntoCache([{ id: 'coda-test-token', name: 'Coda test', credential_type: 'coda_api_token', owned_by_me: true }]);
    expect(autoSelectCredentialFromCache('automation-coda')).toEqual({ coda_api_token: 'coda-test-token' });
});
