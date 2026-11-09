import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/instapaper.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES, isAgentToolProviderType } from '~/utils/nodeMeta';

describe('Instapaper discovery', () => {
    it('discovers the manual access token method and aliases', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-instapaper');
        expect(isAgentToolProviderType('automation-instapaper')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.InstapaperTokenCredential).toBe('instapaper_access_token');
        expect(CREDENTIAL_TYPE_MAP['Instapaper Access Token']).toBe('instapaper_access_token');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['instapaper_access_token']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
});
