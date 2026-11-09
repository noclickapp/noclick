import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/microsoft-teams-events.json'), 'utf8'));

describe('Microsoft Teams Events', () => {
    it('uses the shared Microsoft sign-in with its own delegated scopes', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.method_kind).toBe('oauth');
        expect(requirements[0].credential_type).toBe('microsoft_teams_events_oauth');
        const credential = schema.$defs.TeamsEventsOAuthCredential;
        expect(credential['x-oauth-provider']).toBe('microsoft');
        expect(credential['x-oauth-scopes']).toEqual([
            'https://graph.microsoft.com/User.Read',
            'https://graph.microsoft.com/VirtualEvent.Read',
            'https://graph.microsoft.com/VirtualEvent.ReadWrite',
            'offline_access',
        ]);
    });
});
