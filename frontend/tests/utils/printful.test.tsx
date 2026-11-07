// Printful schema-reader, canvas credential selection and icon checks.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn() } }));
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { PrintfulIcon, PrintfulNode } from '~/components/workflow/nodes/integrations/printful';
import { kindFromCredentialType } from '~/lib/credentialMethodKind';
import schema from '~/schemas/nodes/printful.json';
import { isAgentToolProviderType } from '~/utils/nodeMeta';

beforeAll(() => loadNodeSchemas(['automation-printful']));
afterEach(() => removeCredentialsFromCache(['printful-own', 'printful-foreign-display']));
describe('Printful native wiring', () => {
    it('uses actual schema readers and both declared credential families', () => {
        expect(NODE_SCHEMAS['automation-printful']).toBeDefined();
        expect(getNodeCredentialInfo('automation-printful')?.acceptedTypes).toEqual(['printful_private_token', 'printful_oauth_access_token']);
        expect(CREDENTIAL_TYPE_MAP.PrintfulPrivateTokenCredential).toBe('printful_private_token');
        expect(CREDENTIAL_TYPE_MAP['Printful Issued OAuth Access Token']).toBe('printful_oauth_access_token');
        expect(isAgentToolProviderType('automation-printful')).toBe(true);
        expect(PrintfulNode.type).toBe('automation-printful');
    });
    it('keeps already-issued tokens as manual credential methods', () => {
        for (const credential of [schema.$defs.PrintfulPrivateTokenCredential, schema.$defs.PrintfulOAuthAccessTokenCredential]) {
            expect(kindFromCredentialType((credential as Record<string, unknown>)['x-credential-type'] as string | undefined)).toBe('api_key');
            expect(credential).not.toHaveProperty('x-oauth-provider');
        }
    });
    it('auto-selects the actual own private family and excludes a display-only collaborator descriptor', () => {
        upsertCredentialsIntoCache([{ id: 'printful-own', name: 'Owned store', credential_type: 'printful_private_token', owned_by_me: true },
            { id: 'printful-foreign-display', name: 'Other owner', credential_type: 'printful_private_token', owner_name: 'Other' }]);
        expect(autoSelectCredentialFromCache('automation-printful')).toEqual({ printful_private_token: 'printful-own' });
    });
    it('preserves source colors, aspect ratio and the actual supplied canvas filter', () => {
        const filter = 'invert(0) brightness(.8) drop-shadow(0 0 2px white)';
        const html = renderToStaticMarkup(<PrintfulIcon style={{ width: 48, height: 48, filter }} />);
        expect(html).toContain('/icons/printful.svg');
        expect(html).toContain('object-fit:contain');
        expect(html).toContain(filter);
        expect(html).not.toContain('brand-mono');
    });
});
