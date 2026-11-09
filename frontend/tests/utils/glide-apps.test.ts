import { beforeAll, expect, it } from 'vitest';
import { GlideAppsNode } from '~/components/workflow/nodes/integrations/glide-apps';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-glide-apps']));

it('discovers Glide with a manually pasted team API token', () => {
    expect(GlideAppsNode.type).toBe('automation-glide-apps');
    expect(GlideAppsNode.category).toBe('databases-storage');
    expect(getNodeCredentialInfo('automation-glide-apps')?.label).toBe('Glide API Token');
    expect(getNodeCredentialInfo('automation-glide-apps')?.acceptedTypes).toEqual(['glide_apps_api_token']);
    const methods = credentialRequirements('automation-glide-apps').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['api_token']);
});
