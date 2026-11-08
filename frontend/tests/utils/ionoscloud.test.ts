// Exercises IONOS Cloud's actual credential, selector and editor helpers.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), clear: vi.fn(), delete: vi.fn() } }));
import { IONOSCloudNode } from '~/components/workflow/nodes/integrations/ionoscloud';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { NODE_SCHEMAS, getAgentToolOperations, getNodeCredentialInfo, loadAllNodeSchemas, credentialMarks } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { getCredentialIcon } from '~/utils/credentialIcons';

const type = 'automation-ionoscloud';
const family = 'ionoscloud_bearer';
await loadAllNodeSchemas();
describe('native IONOS Cloud metadata', () => {
    beforeEach(() => invalidateCredentialsCache());
    it('registers the native editor with the original official SVG', () => {
        expect(AVAILABLE_NODES.filter(n => n.type === type)).toEqual([IONOSCloudNode]);
        expect(renderToStaticMarkup(createElement(IONOSCloudNode.Icon as ComponentType))).toContain('/icons/ionoscloud.svg');
        expect(IONOSCloudNode.iconColor).toBe('');
    });
    it('uses a masked supplied token, optional contract and saved names restriction', () => {
        const model = NODE_SCHEMAS[type].$defs.IONOSCloudBearerCredential;
        expect(model.title).toBe('IONOS Cloud Bearer Token');
        expect(model.properties.token['ui:widget']).toBe('password');
        expect(model.properties.approved_datacenter_ids_json.default).toBe('[]');
        expect(model.properties.include_labels.default).toBe(false);
        expect(model.properties.contract_number.default).toBeNull();
        expect(model['x-credential-type']).toBeUndefined();
        expect(model.properties.password).toBeUndefined();
        expect(model.properties.username).toBeUndefined();
        expect(model.properties.base_url).toBeUndefined();
        expect(model.properties.refresh_token).toBeUndefined();
        expect(getProviderConfigByCredentialType(family)).toBeUndefined();
        expect(CREDENTIAL_TYPE_MAP[model.title]).toBe(family);
        expect(humanizeCredentialLabel(model.title)).toBe(model.title);
        expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'ionoscloud', acceptedTypes: [family], label: model.title });
    });
    it('auto-selects only a viewer-owned native saved token', () => {
        upsertCredentialsIntoCache([{ id: 'foreign', credential_type: 'ionos_basic', name: 'Foreign', owned_by_me: true },
            { id: 'display-only', credential_type: family, name: 'Display only' }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({});
        upsertCredentialsIntoCache([{ id: 'native', credential_type: family, name: 'Fixture token', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({ [family]: 'native' });
    });
    it('exposes exactly five operations with real parent selectors and bounded offsets', () => {
        expect(getAgentToolOperations(type).map(op => op.operation).sort()).toEqual(['check_connection',
            'get_datacenter', 'get_server', 'list_datacenters', 'list_servers']);
        const schema = NODE_SCHEMAS[type];
        expect(schema.$defs.GetServer.properties.server_id['x-dynamic-options'].depends_on).toBe('datacenter_id');
        expect(schema.$defs.GetServer.properties.server_id['x-resource-type']).toBe('ionoscloud_server');
        expect(schema.$defs.ListServers.properties.limit.maximum).toBe(100);
        expect(schema.$defs.ListDatacenters.properties.offset.default).toBe(0);
        expect(schema.$defs.ListServers.properties.depth).toBeUndefined();
        expect(schema.$defs.GetDatacenter.properties.fields).toBeUndefined();
        expect(schema.$defs.GetServer.properties.base_url).toBeUndefined();
        expect(schema.$defs.GetServer.properties.contract_number).toBeUndefined();
    });
    it('uses the original asset for saved credentials', () => {
        setNodeIconData({ [type]: { type, label: IONOSCloudNode.label, description: '', iconColor: '',
            iconHtml: '<img src="/icons/ionoscloud.svg" />', dimensions: IONOSCloudNode.dimensions,
            credentialKeys: credentialMarks(t => t === type).get(type) } });
        expect(getCredentialIcon(family).hasServiceIcon).toBe(true);
    });
});
