// Exercises Vendasta's real credential schema, label, operation and cache helpers.
// These fixtures use synthetic credentials to exercise the discovered integration.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement, type ComponentType } from 'react';

vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
vi.mock('@lobehub/icons', () => ({ Anthropic: () => null, MCP: () => null, OpenAI: () => null }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn(), clear: vi.fn() } }));

import { VendastaNode } from '~/components/workflow/nodes/integrations/vendasta';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMAS, loadAllNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { getCredentialIcon } from '~/utils/credentialIcons';

import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

await loadAllNodeSchemas();
const family = 'vendasta_access_token';
const type = 'automation-vendasta';

describe('native Vendasta wiring', () => {
    beforeEach(() => invalidateCredentialsCache());
    it('registers one editor node and keeps the exact vendor asset untinted', () => {
        expect(VendastaNode.type).toBe(type);
        const html = renderToStaticMarkup(createElement(VendastaNode.Icon as ComponentType));
        expect(html).toContain('/icons/vendasta.svg');
        expect(VendastaNode.iconColor).toBe('');
    });
    it('uses an ordinary masked supplied-token form and explicit issuer context', () => {
        const schema = NODE_SCHEMAS[type].$defs.VendastaAccessTokenCredential;
        expect(schema.title).toBe('Vendasta Access Token');
        expect(schema.properties.access_token['ui:widget']).toBe('password');
        expect(schema.required).toEqual(expect.arrayContaining(['environment', 'namespace', 'expires_at', 'scope']));
        expect(schema['x-credential-type']).toBeUndefined();
        expect(getProviderConfigByCredentialType(family)).toBeUndefined();
        expect(credentialRequirements(type).map(req => methodFromRequirement(req).method_kind)).toEqual(['api_key']);
        expect(CREDENTIAL_TYPE_MAP.VendastaAccessTokenCredential).toBe(family);
        expect(humanizeCredentialLabel(schema.title)).toBe('Vendasta Access Token');
        expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'vendasta', acceptedTypes: [family], label: 'Vendasta Access Token' });
    });
    it('auto-selects a viewer-owned native credential and skips display-only or foreign rows', () => {
        upsertCredentialsIntoCache([{ id: 'foreign', credential_type: 'marketplace_api_key', name: 'Foreign', owned_by_me: true },
            { id: 'shared-display', credential_type: family, name: 'Display only' }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({});
        upsertCredentialsIntoCache([{ id: 'own-native', credential_type: family, name: 'Fixture namespace', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({ [family]: 'own-native' });
    });
    it('derives all 26 native agent operations and resource-scoped record pickers', () => {
        const operations = getAgentToolOperations(type);
        expect(operations).toHaveLength(26);
        expect(operations.find(op => op.operation === 'get_contact')?.scopableFields).toEqual(expect.arrayContaining([
            expect.objectContaining({ field: 'record_id', resourceType: 'vendasta_record', loaderField: 'record_id' }),
        ]));
        expect(operations.some(op => /send|invite|billing|custom_object/.test(op.operation))).toBe(false);
    });
    it('uses the native icon on credential surfaces', () => {
        setNodeIconData({ [type]: { type, label: VendastaNode.label, description: '', iconColor: '',
            credentialKeys: [family], iconHtml: '<img src="/icons/vendasta.svg" />', dimensions: VendastaNode.dimensions } });
        expect(getCredentialIcon(family).hasServiceIcon).toBe(true);
    });
});
