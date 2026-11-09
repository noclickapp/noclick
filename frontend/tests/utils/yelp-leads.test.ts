import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
import { YelpLeadsNode } from '~/components/workflow/nodes/integrations/yelp-leads';

await loadNodeSchemas(['automation-yelp-leads']);

describe('Yelp Leads connection', () => {
    it('declares its category and business-aware partner OAuth sign-in', () => {
        expect(YelpLeadsNode.category).toBe('crm-sales');
        const methods = credentialRequirements(YelpLeadsNode.type).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'yelp_leads_oauth', method_kind: 'oauth', is_oauth: true, oauth_provider: 'yelp_leads', oauth_scopes: ['leads'] });
        expect(INTEGRATION_METADATA.oauthProviders.yelp_leads).toMatchObject({
            authorizeUrl: 'https://biz.yelp.com/oauth2/authorize',
            contextFields: { business_id: { source: 'input', kind: 'value', pattern: '[A-Za-z0-9_-]+' } },
        });
    });
});
