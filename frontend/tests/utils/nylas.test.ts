// Prepared native fixtures; generation and execution need separate root lanes.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import schema from '~/schemas/nodes/nylas.json';
import { NODE_SCHEMAS, getNodeCredentialInfo, registerNodeSchemaFiles } from '~/utils/nodeSchemas';
import { isAgentToolProviderType, isTriggerSource } from '~/utils/nodeMeta';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

const key = 'automation-nylas';
registerNodeSchemaFiles({ './nylas.json': schema });
const refs = (schema.properties.config as any).oneOf;
const definitions = (schema as any).$defs;
const operations = refs.map((ref: { $ref: string }) => definitions[ref.$ref.split('/').pop()!]);

describe('native Nylas v3 wiring', () => {
    it('registers all 25 native actions and no triggers or creator growth', () => {
        expect(NODE_SCHEMAS[key]).toBe(schema);
        expect(isAgentToolProviderType(key)).toBe(true);
        expect(operations).toHaveLength(25);
        for (const operation of operations) {
            const name = operation.properties.operation.const;
            expect(isTriggerSource(key, name)).toBe(false);
            expect(name).not.toMatch(/send|invite|notetaker|grant_create|domain/);
            expect(JSON.stringify(operation)).not.toContain('x-creates-resource');
        }
    });

    it('offers both exact issued credential families with honest manual UI', () => {
        const alternatives = (schema.properties.credentials as any).anyOf
            .filter((entry: any) => entry.$ref).map((entry: any) => definitions[entry.$ref.split('/').pop()!]);
        expect(alternatives).toHaveLength(2);
        expect(getNodeCredentialInfo(key)?.acceptedTypes).toEqual(['nylas_api_key', 'nylas_access_token']);
        expect(getCredentialTypeFromSchemaTitle('Nylas API Key')).toBe('nylas_api_key');
        expect(getCredentialTypeFromSchemaTitle('Nylas Access Token')).toBe('nylas_access_token');
        expect(humanizeCredentialLabel('NylasAPIKey')).toBe('Nylas API Key');
        expect(humanizeCredentialLabel('NylasAccessToken')).toBe('Nylas Access Token');
        for (const type of ['nylas_api_key', 'nylas_access_token']) {
            expect(getProviderConfigByCredentialType(type)).toBeUndefined();
        }
        const credential = definitions.NylasAPIKeyCredential;
        expect(credential.properties.region.enum).toEqual(['us', 'eu']);
        expect(credential.required).toContain('grant_id');
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(JSON.stringify(alternatives)).not.toMatch(/refresh_token|client_secret|x-oauth-provider/);
    });

    it('declares real parent selection, bounded pages and private output defaults', () => {
        const event = definitions.GetEventConfig;
        expect(event.properties.event_id['x-dynamic-options'].depends_on).toEqual(['calendar_id', 'start', 'end']);
        expect(event.properties.calendar_id['x-resource-type']).toBe('nylas_calendar');
        const list = definitions.ListEventsConfig;
        expect(list.required).toEqual(expect.arrayContaining(['calendar_id', 'start', 'end']));
        expect(list.properties.limit.maximum).toBe(100);
        for (const operation of operations) expect(operation.properties.include_content.default).toBe(false);
    });

    it('keeps the exact official wordmark and native canvas definition', () => {
        const svg = readFileSync(new URL('../../public/icons/nylas.svg', import.meta.url));
        expect(svg.byteLength).toBe(7686);
        expect(createHash('sha256').update(svg).digest('hex')).toBe('f9245e93ecc6ede674095440e5f7908a5a24b45a86d677b1e41e9d4cd992c7e7');
        const ui = readFileSync(new URL('../../app/components/workflow/nodes/integrations/nylas.tsx', import.meta.url), 'utf8');
        expect(ui).toContain("type: 'automation-nylas'");
        expect(ui).toContain('/icons/nylas.svg');
        expect(ui).toContain("objectFit: 'contain'");
    });
});
