// LibreTranslate's pasted API key must be discoverable by the shared connect form.
// This guards the generated metadata that manual credential requests consume.
import { beforeAll, describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

import { loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-libretranslate']));

describe('LibreTranslate credentials', () => {
    it('offers a manually entered API key', () => {
        const requirements = credentialRequirements('automation-libretranslate');
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method).toMatchObject({ credential_type: 'libretranslate_api_key', method_kind: 'api_key', is_oauth: false });
        expect(method.credential_fields?.some(field => field.name === 'api_key')).toBe(true);
    });
});
