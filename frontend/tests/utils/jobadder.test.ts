import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
import { JobAdderNode } from '~/components/workflow/nodes/integrations/jobadder';

await loadNodeSchemas(['automation-jobadder']);

describe('JobAdder connection', () => {
    it('exposes recruiting OAuth with a declared sign-in provider', () => {
        expect(JobAdderNode.category).toBe('hr-recruiting');
        const methods = credentialRequirements(JobAdderNode.type).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'jobadder_oauth', method_kind: 'oauth', is_oauth: true, oauth_provider: 'jobadder' });
        expect(methods[0].oauth_scopes).toContain('offline_access');
        expect(INTEGRATION_METADATA.oauthProviders.jobadder).toMatchObject({
            authorizeUrl: 'https://id.jobadder.com/connect/authorize',
        });
    });
});
