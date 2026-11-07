// Exercises Uptime.com's actual credential, selector and editor helpers.
// Schemas are loaded through staging's per-node loader before synchronous helpers run.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), clear: vi.fn(), delete: vi.fn() } }));

import { UptimeComNode } from '~/components/workflow/nodes/UptimeComNode';
import { NODE_DEFINITION_FILES } from '~/components/workflow/nodes/nodeDefinitions';
import { NODE_SCHEMAS, getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { getCredentialIcon } from '~/utils/credentialIcons';

const type = 'automation-uptimecom';
const family = 'uptimecom_api_token';

describe('native Uptime.com monitoring metadata', () => {
    beforeAll(async () => { await loadNodeSchemas([type]); });
    beforeEach(() => invalidateCredentialsCache());
    it('registers the native editor and unaltered official wordmark', () => {
        expect(NODE_DEFINITION_FILES.filter(([nodeType]) => nodeType === type)).toEqual([[type, 'UptimeComNode']]);
        const markup = renderToStaticMarkup(createElement(UptimeComNode.Icon));
        expect(markup).toContain('/icons/uptimecom-brand-vector.svg');
        expect(markup).toContain('object-fit:contain');
        expect(UptimeComNode.iconColor).toBe('');
    });
    it('keeps the API key manual and masked with an explicit user witness', () => {
        const model = NODE_SCHEMAS[type].$defs.UptimeComAPITokenCredential;
        expect(model.title).toBe('Uptime.com API Token');
        expect(model.properties.api_key['ui:widget']).toBe('password');
        expect(model.required).toEqual(expect.arrayContaining(['api_key', 'expected_user_pk']));
        expect(model.properties.approved_resources_json.default).toBe('{"checks":[],"tags":[],"statuspages":[]}');
        expect(model.properties.include_labels.default).toBe(false);
        expect(model.properties.password).toBeUndefined();
        expect(model.properties.access_token).toBeUndefined();
        expect(model['x-credential-type']).toBeUndefined();
        expect(getProviderConfigByCredentialType(family)).toBeUndefined();
        expect(CREDENTIAL_TYPE_MAP[model.title]).toBe(family);
        expect(humanizeCredentialLabel(model.title)).toBe(model.title);
        expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'uptimecom', acceptedTypes: [family], label: model.title });
    });
    it('selects only a viewer-owned native family rather than display-only or foreign forms', () => {
        upsertCredentialsIntoCache([{ id: 'foreign', credential_type: 'uptimecom_bearer', name: 'Foreign', owned_by_me: true },
            { id: 'display-only', credential_type: family, name: 'Display only' }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({});
        upsertCredentialsIntoCache([{ id: 'native', credential_type: family, name: 'Fixture key', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({ [family]: 'native' });
    });
    it('exposes the exact eleven reads and actual check/outage dependency', () => {
        const operations = getAgentToolOperations(type);
        expect(operations.map(op => op.operation).sort()).toEqual(['check_connection', 'get_check', 'get_check_statistics',
            'get_outage', 'get_status_page', 'get_status_page_current_status', 'get_tag', 'list_checks', 'list_outages', 'list_status_pages', 'list_tags']);
        expect(operations.find(op => op.operation === 'get_outage')?.scopableFields).toEqual(expect.arrayContaining([
            expect.objectContaining({ field: 'check_id', resourceType: 'uptimecom_check', loaderField: 'check_id' }),
            expect.objectContaining({ field: 'outage_id', resourceType: 'uptimecom_outage', loaderField: 'outage_id' }),
        ]));
        expect(NODE_SCHEMAS[type].$defs.GetOutage.properties.outage_id['x-dynamic-options'].depends_on).toBe('check_id');
        expect(NODE_SCHEMAS[type].$defs.ListChecks.properties.page_size.maximum).toBe(100);
        expect(NODE_SCHEMAS[type].$defs.GetCheckCurrentStatus).toBeUndefined();
    });
    it('uses the native asset for the saved credential icon', () => {
        setNodeIconData({ [type]: { type, label: UptimeComNode.label, description: '', credentialKeys: [family], iconColor: '',
            iconHtml: '<img src="/icons/uptimecom.svg" />', dimensions: UptimeComNode.dimensions } });
        expect(getCredentialIcon(family).hasServiceIcon).toBe(true);
    });
});
