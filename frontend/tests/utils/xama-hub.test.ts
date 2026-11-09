import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/xama-hub.json';
import { XamaHubNode } from '~/components/workflow/nodes/integrations/xama-hub';

describe('Xama Hub credentials and metadata', () => {
    it('discovers a manually pasted bearer token and the CRM category', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-xama-hub');
        expect(XamaHubNode.category).toBe('crm-sales');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'xama_hub_bearer_token', method_kind: 'api_key', is_oauth: false,
        });
        expect(schema.$defs.XamaHubBearerTokenCredential.required).toEqual(['tenant_id', 'access_token']);
    });
});
