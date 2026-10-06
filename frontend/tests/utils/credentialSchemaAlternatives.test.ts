// Exercises the credential schema shapes consumed by metadata and selection helpers.
// Real provider definitions cover nested discriminated unions, while malformed/cyclic inputs protect the shared traversal boundary.
import { afterEach, describe, expect, it } from 'vitest';
import { collectCredentialAlternatives, collectCredentialSchemas } from '~/utils/credentialSchemaAlternatives';
import { CREDENTIAL_TYPE_MAP, getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { dripCredentialSchema, mauticCredentialSchema } from '../fixtures/credentialUnionSchemas';

const fixtureType = 'automation-credential-union-fixture';
const oldFixture = NODE_SCHEMAS[fixtureType];
afterEach(() => {
    if (oldFixture === undefined) delete NODE_SCHEMAS[fixtureType];
    else NODE_SCHEMAS[fixtureType] = oldFixture;
});

describe('generated credential alternatives', () => {
    it.each([
        [dripCredentialSchema, ['drip_oauth', 'drip_api_token']],
        [mauticCredentialSchema, ['mautic_basic', 'mautic_oauth2']],
    ])('returns actual credential leaves and preserves their metadata', (schema, types) => {
        const before = JSON.stringify(schema);
        const leaves = collectCredentialSchemas(schema);
        expect(leaves.map(leaf => leaf.properties.credential_type.const)).toEqual(types);
        expect(leaves.every(leaf => Object.values(schema.$defs).includes(leaf))).toBe(true);
        expect(JSON.stringify(schema)).toBe(before);
    });

    it('keeps the real OAuth marker, scopes, fields and hidden discriminator field', () => {
        const [oauth, api] = collectCredentialSchemas(dripCredentialSchema);
        expect(oauth['x-credential-type']).toBe('oauth');
        expect(oauth['x-oauth-provider']).toBe('drip');
        expect(oauth['x-oauth-scopes']).toEqual(['public']);
        expect(oauth.properties.credential_type['ui:hidden']).toBe(true);
        expect(api.properties.api_token['ui:widget']).toBe('password');
        const [, manualOAuth] = collectCredentialSchemas(mauticCredentialSchema);
        expect(manualOAuth['x-credential-type']).toBeUndefined();
        expect(manualOAuth.required).toContain('refresh_token');
    });

    it('supports direct refs, legacy definitions, nested nullable unions and inline models in order', () => {
        const leaf = dripCredentialSchema.$defs.DripAPITokenCredential;
        const root: any = {
            $defs: { 'escaped/name~': leaf, Alias: { oneOf: [{ $ref: '#/definitions/Legacy' }] } },
            definitions: { Legacy: { anyOf: [{ type: 'null' }, { $ref: '#/$defs/escaped~1name~0' }] } },
            properties: { credentials: { $ref: '#/$defs/Alias' } },
        };
        expect(collectCredentialSchemas(root)).toEqual([leaf]);
        expect(collectCredentialAlternatives(root)[0].definitionName).toBe('escaped/name~');
        root.properties.credentials = leaf;
        expect(collectCredentialSchemas(root)[0]).toBe(leaf);
    });

    it('terminates ref/object cycles and deduplicates repeated aliases without walking fields', () => {
        const leaf: any = { ...dripCredentialSchema.$defs.DripAPITokenCredential };
        leaf.properties = { ...leaf.properties, unrelated: { oneOf: [mauticCredentialSchema.$defs.MauticBasicCredential] } };
        const union: any = { anyOf: [] };
        union.anyOf = [union, { $ref: '#/$defs/Cycle' }, { $ref: '#/$defs/Leaf' }, { $ref: '#/$defs/Leaf' }];
        const root = { $defs: { Cycle: { $ref: '#/$defs/Cycle' }, Leaf: leaf }, properties: { credentials: union } };
        expect(collectCredentialSchemas(root)).toEqual([leaf]);
    });

    it('ignores malformed branches and local/external unresolved refs while retaining a valid alternative', () => {
        const leaf = dripCredentialSchema.$defs.DripAPITokenCredential;
        const root = { $defs: { Leaf: leaf }, properties: { credentials: { oneOf: [
            null, true, 12, [], {}, { type: 'null' }, { anyOf: 'invalid' },
            { $ref: 'https://example.invalid/schema.json' }, { $ref: '#/$defs/Missing' },
            { $ref: '#/$defs/invalid~2escape' }, { properties: [] },
            { ...leaf, title: 42 }, { ...leaf, description: {} }, { ...leaf, 'x-oauth-provider': 42 },
            { ...leaf, properties: { credential_type: { const: 42 } } },
            { $ref: '#/$defs/Leaf' },
        ] } } };
        expect(collectCredentialSchemas(root)).toEqual([leaf]);
        NODE_SCHEMAS[fixtureType] = root;
        expect(getNodeCredentialInfo(fixtureType)?.acceptedTypes).toEqual([getCredentialTypeFromSchemaTitle(leaf.title)]);
        expect(collectCredentialSchemas(null)).toEqual([]);
        expect(collectCredentialSchemas({ properties: { credentials: { type: 'null' } } })).toEqual([]);
    });

    it('feeds nested alternatives into the real metadata lookup using its existing title map', () => {
        NODE_SCHEMAS[fixtureType] = dripCredentialSchema;
        expect(getNodeCredentialInfo(fixtureType)).toEqual({
            providerKey: 'drip', label: 'Drip Account',
            acceptedTypes: ['Drip OAuth', 'Drip API Token'].map(getCredentialTypeFromSchemaTitle),
        });
        NODE_SCHEMAS[fixtureType] = mauticCredentialSchema;
        expect(getNodeCredentialInfo(fixtureType)?.acceptedTypes).toEqual(
            ['MauticBasicCredential', 'MauticOAuth2Credential'].map(getCredentialTypeFromSchemaTitle),
        );
    });

    it('preserves the current catalog metadata type/order contract for every direct-ref/flat union', () => {
        let checked = 0;
        for (const [nodeType, schema] of Object.entries(NODE_SCHEMAS)) {
            const prop = schema.properties?.credentials;
            if (!prop) continue;
            const refs = prop.$ref ? [{ $ref: prop.$ref }] : (prop.anyOf ?? []).filter((entry: any) => entry?.$ref);
            const defs = schema.$defs || schema.definitions || {};
            const leaves = refs.map((entry: any) => defs[entry.$ref.replace('#/$defs/', '').replace('#/definitions/', '')])
                .filter((leaf: any) => leaf && (prop.$ref || leaf.title));
            if (!leaves.length) continue;
            const expected = leaves.map((leaf: any) => CREDENTIAL_TYPE_MAP[leaf.title || ''] || (leaf.title || '').toLowerCase());
            expect(getNodeCredentialInfo(nodeType)?.acceptedTypes, nodeType).toEqual(expected);
            checked++;
        }
        expect(checked).toBeGreaterThan(100);
    });
});
