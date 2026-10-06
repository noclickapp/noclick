// Exercises the actual synchronous canvas credential selector and its owned-credential cache.
// Generated nested fixtures reuse a registered schema slot, with no registry expansion or account/socket calls.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import slackSchema from '~/schemas/nodes/slack.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { dripCredentialSchema, mauticCredentialSchema } from '../fixtures/credentialUnionSchemas';

const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: boundary.get, set: boundary.set, delete: boundary.delete } }));
const { autoSelectCredentialFromCache, invalidateCredentialsCache, removeCredentialsFromCache, upsertCredentialsIntoCache } = await import('~/utils/credentialAutoSelect');

const originalProperty = slackSchema.properties.credentials;
const originalDefinitions = slackSchema.$defs;
const providerMappings: Record<string, string> = {
    DripOAuthCredential: 'drip_oauth', DripAPITokenCredential: 'drip_api_token',
    MauticBasicCredential: 'mautic_basic', MauticOAuth2Credential: 'mautic_oauth2',
};
const previousMappings = Object.fromEntries(Object.keys(providerMappings).map(key => [key, CREDENTIAL_TYPE_MAP[key]]));
const injectedIds: string[] = [];
const slot: any = slackSchema;

beforeEach(() => {
    invalidateCredentialsCache();
    Object.assign(CREDENTIAL_TYPE_MAP, providerMappings);
    boundary.send.mockClear(); boundary.get.mockClear(); boundary.set.mockClear(); boundary.delete.mockClear();
});
afterEach(() => {
    slot.properties.credentials = originalProperty;
    slot.$defs = originalDefinitions;
    removeCredentialsFromCache(injectedIds.splice(0));
    invalidateCredentialsCache();
    for (const [key, previous] of Object.entries(previousMappings)) {
        if (previous === undefined) delete CREDENTIAL_TYPE_MAP[key];
        else CREDENTIAL_TYPE_MAP[key] = previous;
    }
});

function own(type: string, id = `owned-${type}`) {
    injectedIds.push(id);
    upsertCredentialsIntoCache([{ id, name: id, credential_type: type, owned_by_me: true }]);
    return id;
}
function useFixture(schema: typeof dripCredentialSchema) {
    slot.properties.credentials = schema.properties.credentials;
    slot.$defs = { ...schema.$defs };
}

describe('canvas selection from nested generated credential unions', () => {
    it.each([
        [dripCredentialSchema, 'drip_oauth', 'drip_api_token'],
        [mauticCredentialSchema, 'mautic_basic', 'mautic_oauth2'],
    ])('selects an owned credential by the first referenced definition, independent of leaf title', (schema, first, second) => {
        useFixture(schema);
        own(second);
        expect(autoSelectCredentialFromCache('automation-slack')).toEqual({});
        const id = own(first);
        expect(autoSelectCredentialFromCache('automation-slack')).toEqual({ [first]: id });
        expect(boundary.send).not.toHaveBeenCalled();
        expect(boundary.get).not.toHaveBeenCalled();
        expect(boundary.set).not.toHaveBeenCalled();
    });

    it('does not auto-select injected owner descriptors when the nested method has an owned credential', () => {
        useFixture(dripCredentialSchema);
        const id = own('drip_oauth');
        injectedIds.push('someone-else');
        upsertCredentialsIntoCache([{ id: 'someone-else', name: 'Flow owner', credential_type: 'drip_oauth', owned_by_me: false }]);
        expect(autoSelectCredentialFromCache('automation-slack')).toEqual({ drip_oauth: id });
    });

    it('keeps direct-property title precedence and ignores null, unresolved refs, and cycles', () => {
        useFixture(dripCredentialSchema);
        own('drip_oauth');
        const id = own('slack_bot_token');
        slot.properties.credentials = { $ref: '#/$defs/DripOAuthCredential', title: 'SlackBotTokenCredential' };
        expect(autoSelectCredentialFromCache('automation-slack')).toEqual({ slack_bot_token: id });
        slot.$defs.Cycle = { $ref: '#/$defs/Cycle' };
        slot.properties.credentials = { anyOf: [null, { type: 'null' }, { $ref: 'https://example.invalid/credentials.json' }, { $ref: '#/$defs/Cycle' }] };
        expect(autoSelectCredentialFromCache('automation-slack')).toEqual({});
        delete slot.$defs.Cycle;
    });

    it('preserves the current registered catalog first-ref type mapping', () => {
        const registered = [
            'telegram', 'google-sheets', 'google-drive', 'gmail', 'outlook', 'excel', 'word', 'linear', 'airtable', 'stripe',
            'github-rest', 'apify', 'apollo', 'bluesky', 'canva', 'discord', 'google-calendar', 'google-docs', 'google-slides',
            'google-forms', 'google-tasks', 'google-contacts', 'instagram', 'instantly', 'jira', 'clickup', 'linkedin', 'notion',
            'postgres', 'reddit', 'rss', 'redis', 'salesforce', 'shopify', 'slack', 'supabase', 'twitter', 'youtube', 'hubspot',
            'mailchimp', 'firestore', 'elevenlabs', 'cloudflare', 'google-analytics', 'google-ads', 'google-business-profile', 'google-search-console',
        ].map(name => `automation-${name}`).concat('agent');
        for (const nodeType of registered) {
            const prop = NODE_SCHEMAS[nodeType]?.properties?.credentials;
            const name = prop?.anyOf
                ? prop.anyOf.find((alternative: any) => alternative?.$ref)?.$ref.split('/').pop()
                : prop?.title || prop?.$ref?.split('/').pop();
            const type = name ? CREDENTIAL_TYPE_MAP[name] : undefined;
            const expected = type ? { [type]: own(type) } : {};
            expect(autoSelectCredentialFromCache(nodeType), nodeType).toEqual(expected);
        }
        expect(boundary.send).not.toHaveBeenCalled();
    });
});
