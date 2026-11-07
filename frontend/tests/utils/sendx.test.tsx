import React from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { NODE_SCHEMAS, loadNodeSchemas, filterConfigForExecution, getNodeCredentialInfo, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { invalidateCredentialsCache, prefetchCredentials, upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { SendXNode } from '~/components/workflow/nodes/integrations/sendx';

const socket = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: socket.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn().mockResolvedValue(null), set: vi.fn().mockResolvedValue(undefined), delete: vi.fn() } }));
vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
afterEach(() => { removeCredentialsFromCache(['unowned']); invalidateCredentialsCache(); socket.send.mockReset(); });
const type = 'automation-sendx';
const tag = 'sendx_team_api_key';
beforeAll(() => loadNodeSchemas([type]));

describe('SendX metadata and editor', () => {
    it('discovers the supplied team key without inventing account/OAuth authority', () => {
        const schema = NODE_SCHEMAS[type];
        expect(requirementsFromSchema(schema).map(c => c.label)).toEqual(['Send X Existing Team API Key']);
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual([tag]);
        const credential = schema.$defs.SendXTeamAPIKeyCredential;
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential.required).toEqual(expect.arrayContaining(['api_key', 'witness_list_id', 'list_ids', 'allowed_operations']));
        expect(credential.properties.list_ids.maxItems).toBe(20);
        for (const field of ['api_base_url', 'team_id', 'password', 'access_token', 'refresh_token']) expect(credential.properties[field]).toBeUndefined();
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(getCredentialTypeFromSchemaTitle('SendXTeamAPIKeyCredential')).toBe(tag);
        expect(getCredentialTypeFromSchemaTitle(credential.title)).toBe(tag);
        expect(humanizeCredentialLabel(credential.title)).toBe('Send X Existing Team API Key');
    });

    it('selects a healthy owned native row through actual prefetch/cache selection', async () => {
        socket.send.mockResolvedValue({ success: true, credentials: [
            { id: 'foreign', credential_type: 'sendx_identify_key', updated_at: '2026-10-06T18:00:00Z' },
            { id: 'revoked', credential_type: tag, revoked_at: '2026-10-06T17:00:00Z', updated_at: '2026-10-06T17:00:00Z' },
            { id: 'native', credential_type: tag, updated_at: '2026-10-06T16:00:00Z' },
        ] });
        await prefetchCredentials();
        upsertCredentialsIntoCache([{ id: 'unowned', name: 'Shared SendX key', credential_type: tag, owned_by_me: false }]);
        socket.send.mockClear();
        expect(autoSelectCredentialFromCache(type)).toEqual({ [tag]: 'native' });
        expect(socket.send).not.toHaveBeenCalled();
    });

    it('keeps twenty closed operations, documented IDs/page caps and explicit write effects', () => {
        const schema = NODE_SCHEMAS[type];
        expect(Object.keys(schema.properties.config.discriminator.mapping).sort()).toEqual(['create_contact', 'create_list', 'create_tag', 'delete_contact', 'delete_list', 'delete_tag', 'get_campaign', 'get_campaign_report', 'get_contact', 'get_custom_field', 'get_list', 'get_tag', 'list_campaigns', 'list_contacts', 'list_custom_fields', 'list_lists', 'list_tags', 'update_contact', 'update_list', 'update_tag']);
        expect(schema.$defs.SendXListContactsConfig.properties.limit.maximum).toBe(30);
        expect(schema.$defs.SendXListListsConfig.properties.limit.maximum).toBe(100);
        expect(schema.$defs.SendXListTagsConfig.properties.search).toBeUndefined();
        expect(schema.$defs.SendXListCampaignsConfig.properties.campaign_type.enum).toEqual(['all', 'draft', 'scheduled', 'sent']);
        const update = schema.$defs.SendXUpdateContactConfig;
        expect(update.required).toEqual(expect.arrayContaining(['email', 'contact_id', 'automation_effects_acknowledged']));
        expect(update.properties.automation_effects_acknowledged.description).toContain('existing SendX automations');
        expect(update.properties.contact_id['x-dynamic-options'].field_name).toBe('contact_id');
        const fields = { operation: 'update_contact', contact_id: 'contact_' + 'C'.repeat(22), email: 'synthetic@example.invalid', automation_effects_acknowledged: true };
        expect(filterConfigForExecution(type, fields)).toEqual(fields);
        expect(isAgentToolProviderType(type)).toBe(true);
    });

    it('wires the exact official publisher SVG', () => {
        const Icon = SendXNode.Icon;
        expect(SendXNode.type).toBe(type);
        expect(renderToStaticMarkup(<Icon />)).toContain('src="/icons/sendx.svg"');
        expect(createHash('sha256').update(readFileSync(resolve(__dirname, '../../public/icons/sendx.svg'))).digest('hex')).toBe('c0a29cc7a7ddee4c924c082984ac8709c13991b1d8f0e1517b408110ebdb70af');
    });
});
