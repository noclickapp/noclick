// Bitrise's native credential and resource schemas use the current frontend consumers.
// Loading the generated schema exercises the same lazy path as the editor.
import { beforeAll, describe, expect, it } from 'vitest';
import { NODE_SCHEMAS, loadNodeSchemas, filterConfigForExecution, isTriggerSource } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

describe('Bitrise raw Authorization token metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-bitrise']));
    it('requires only the existing personal/workspace token without invented identity or OAuth', () => {
        const schema = NODE_SCHEMAS['automation-bitrise'];
        const cred = schema.$defs.BitriseAPITokenCredential;
        expect(cred.required).toEqual(['access_token']);
        expect(cred.properties.access_token['ui:widget']).toBe('password');
        expect(cred.properties.access_token.maxLength).toBe(8192);
        expect(CREDENTIAL_TYPE_MAP[cred.title]).toBe('bitrise_api_token');
        expect(humanizeCredentialLabel(cred.title)).toBe('Bitrise API Token Credential');
        expect(cred['x-oauth-provider']).toBeUndefined();
        expect(cred.properties.actor_id).toBeUndefined();
        expect(schema['x-agent-tool-provider']).toBe(true);
    });
    it('retains app/build parent scope, page caps and opt-in name defaults', () => {
        const defs = NODE_SCHEMAS['automation-bitrise'].$defs;
        expect(defs.BitriseGetBuildConfig.required).toEqual(['app_slug', 'build_slug']);
        expect(defs.BitriseGetBuildConfig.properties.build_slug['x-dynamic-options'].depends_on).toBe('app_slug');
        expect(defs.BitriseAppsConfig.properties.limit.maximum).toBe(50);
        expect(defs.BitriseAppsConfig.properties.include_names.default).toBe(false);
        expect(defs.BitriseBranchesConfig.properties.max_names.maximum).toBe(500);
        expect(isTriggerSource('automation-bitrise', 'list_builds')).toBe(false);
    });
    it('filters old paging fields while preserving the selected app/build', () => {
        expect(filterConfigForExecution('automation-bitrise', { operation: 'get_build', app_slug: 'app-a',
            build_slug: 'build-a', include_names: false, limit: 50, page_token: 'old' }))
            .toEqual({ operation: 'get_build', app_slug: 'app-a', build_slug: 'build-a', include_names: false });
    });
});
