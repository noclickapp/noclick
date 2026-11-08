import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { AnchorBrowserNode } from '~/components/workflow/nodes/integrations/anchor-browser';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/anchor-browser.json'), 'utf8'));

describe('Anchor Browser connection and catalog', () => {
    beforeAll(() => loadNodeSchemas(['automation-anchor-browser']));
    it('offers one API key method through the generated metadata', () => {
        expect(requirementsFromSchema(schema).map(methodFromRequirement)).toEqual([
            expect.objectContaining({ credential_type: 'anchor_browser_api_key', method_kind: 'api_key', is_oauth: false }),
        ]);
        expect(getNodeCredentialInfo('automation-anchor-browser')?.acceptedTypes).toEqual(['anchor_browser_api_key']);
        expect(getCredentialTypeFromSchemaTitle('AnchorBrowserAPIKeyCredential')).toBe('anchor_browser_api_key');
        expect(getCredentialTypeFromSchemaTitle('Anchor Browser API Key')).toBe('anchor_browser_api_key');
        expect(schema.$defs.AnchorBrowserAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
    });
    it('lists the integration in developer tools', () => {
        expect(AnchorBrowserNode.type).toBe('automation-anchor-browser');
        expect(AnchorBrowserNode.label).toBe('Anchor Browser');
        expect(AnchorBrowserNode.category).toBe('developer-tools');
    });
});
