// Exercises Sematext's real credential, selector and editor helpers.
// Prepared synthetic fixtures remain unrun until a root frontend lane is granted.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), clear: vi.fn() } }));
import { SematextNode } from '~/components/workflow/nodes/SematextNode';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { NODE_SCHEMAS, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { autoSelectCredentialFromCache, invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { getCredentialIcon } from '~/utils/credentialIcons';

const type = 'automation-sematext';
const family = 'sematext_account_api_key';
describe('native Sematext metadata', () => {
    beforeEach(() => invalidateCredentialsCache());
    it('registers the editor with the exact official SVG', () => {
        expect(AVAILABLE_NODES.filter(n => n.type === type)).toEqual([SematextNode]);
        expect(renderToStaticMarkup(createElement(SematextNode.Icon))).toContain('/icons/sematext.svg');
        expect(SematextNode.iconColor).toBe('');
    });
    it('uses masked manual API-key credentials and saved opt-in names', () => {
        const model = NODE_SCHEMAS[type].$defs.SematextAccountAPIKeyCredential;
        expect(model.title).toBe('Sematext Account API Key');
        expect(model.properties.api_key['ui:widget']).toBe('password');
        expect(model.properties.approved_app_ids_json.default).toBe('[]');
        expect(model.properties.region.enum).toEqual(['US', 'EU']);
        expect(model.properties.region.default).toBe('US');
        expect(model.properties.app_token).toBeUndefined();
        expect(model.properties.include_labels.default).toBe(false);
        expect(model['x-credential-type']).toBeUndefined();
        expect(model.properties.password).toBeUndefined();
        expect(getProviderConfigByCredentialType(family)).toBeUndefined();
        expect(CREDENTIAL_TYPE_MAP[model.title]).toBe(family);
        expect(humanizeCredentialLabel(model.title)).toBe(model.title);
        expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'sematext', acceptedTypes: [family], label: model.title });
    });
    it('auto-selects only a viewer-owned native token', () => {
        upsertCredentialsIntoCache([{ id: 'foreign', credential_type: 'sematext_app_token', name: 'Foreign', owned_by_me: true },
            { id: 'display-only', credential_type: family, name: 'Display only' }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({});
        upsertCredentialsIntoCache([{ id: 'native', credential_type: family, name: 'Fixture token', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({ [family]: 'native' });
    });
    it('exposes exactly five metadata reads with local limits and a bound app selector', () => {
        const operations = getAgentToolOperations(type);
        expect(operations.map(op => op.operation).sort()).toEqual(['check_connection', 'get_app',
            'list_alert_rules', 'list_app_types', 'list_apps']);
        expect(NODE_SCHEMAS[type].$defs.GetApp.properties.app_id['x-dynamic-options'].field_name).toBe('app_id');
        expect(NODE_SCHEMAS[type].$defs.GetApp.properties.app_id['x-resource-type']).toBe('sematext_app');
        expect(NODE_SCHEMAS[type].$defs.ListApps.properties.limit.maximum).toBe(100);
        expect(NODE_SCHEMAS[type].$defs.ListApps.properties.page).toBeUndefined();
        expect(NODE_SCHEMAS[type].$defs.ListAlertRules.properties.query).toBeUndefined();
        expect(NODE_SCHEMAS[type].$defs.GetApp.properties.region).toBeUndefined();
        expect(NODE_SCHEMAS[type].$defs.GetApp.properties.base_url).toBeUndefined();
    });
    it('uses the native asset for saved credentials', () => {
        setNodeIconData({ [type]: { type, label: SematextNode.label, description: '', iconColor: '',
            iconHtml: '<img src="/icons/sematext.svg" />', dimensions: SematextNode.dimensions } });
        expect(getCredentialIcon(family).hasServiceIcon).toBe(true);
    });
});
