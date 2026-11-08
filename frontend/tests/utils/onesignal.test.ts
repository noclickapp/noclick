import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/onesignal.json';
import meta from '~/schemas/nodeMeta/onesignal.json';

describe('OneSignal credential method', () => {
    it('offers app and organization keys as one API key connection', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['onesignal_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(meta.credentialTypes.OneSignalCredential).toBe('onesignal_api_key');
        expect(meta.credentialTypes['OneSignal API Key']).toBe('onesignal_api_key');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
