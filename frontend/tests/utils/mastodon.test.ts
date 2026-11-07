import { beforeAll, expect, it } from 'vitest';
import { MastodonNode } from '~/components/workflow/nodes/integrations/mastodon';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-mastodon']));

it('discovers Mastodon with an existing user token and explicit instance origin', () => {
    expect(MastodonNode.type).toBe('automation-mastodon');
    expect(MastodonNode.label).toBe('Mastodon');
    expect(CREDENTIAL_TYPE_MAP.MastodonCredential).toBe('mastodon_user_token');
    expect(CREDENTIAL_TYPE_MAP['Mastodon User Token']).toBe('mastodon_user_token');
    expect(getNodeCredentialInfo('automation-mastodon')?.acceptedTypes).toEqual(['mastodon_user_token']);
    const methods = credentialRequirements('automation-mastodon').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['instance_origin', 'access_token']);
});
