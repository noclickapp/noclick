// Verifies the Vocal Video catalog entry and generated manual API key method.
// This guards the connection metadata used by the frontend without contacting the provider.
import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { VocalVideoNode } from '~/components/workflow/nodes/integrations/vocal-video';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/vocal-video.json'), 'utf8'));

describe('Vocal Video connection and catalog', () => {
    beforeAll(() => loadNodeSchemas(['automation-vocal-video']));
    it('offers the generated manual API key method', () => {
        expect(requirementsFromSchema(schema).map(methodFromRequirement)).toEqual([
            expect.objectContaining({ credential_type: 'vocal_video_api_key', method_kind: 'api_key', is_oauth: false }),
        ]);
        expect(getNodeCredentialInfo('automation-vocal-video')?.acceptedTypes).toEqual(['vocal_video_api_key']);
        expect(getCredentialTypeFromSchemaTitle('Vocal Video API Key')).toBe('vocal_video_api_key');
        expect(schema.$defs.VocalVideoAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
    });
    it('lists Vocal Video under media', () => {
        expect(VocalVideoNode.type).toBe('automation-vocal-video');
        expect(VocalVideoNode.category).toBe('media');
    });
});
