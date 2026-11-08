// Exercises Env0's real credential, selector and editor helpers.
// Verify self-registration, lazy schema loading and manual API-key selection.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn(), clear: vi.fn() } }));
import { Env0Node } from '~/components/workflow/nodes/integrations/env0';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { getCredentialIcon } from '~/utils/credentialIcons';

const type = 'automation-env0';
const family = 'env0_api_key';
describe('native Env0 metadata', () => {
    beforeAll(async () => { await loadNodeSchemas([type]); });
    beforeEach(() => invalidateCredentialsCache());
    it('registers the editor with the official vector icon', () => {
        expect(AVAILABLE_NODES.filter(n => n.type === type)).toEqual([Env0Node]);
        expect(renderToStaticMarkup(createElement(Env0Node.Icon as ComponentType))).toContain('/icons/env0-brand-vector.svg');
        expect(Env0Node.iconColor).toBe('');
    });
    it('uses a masked manual key pair and saved opt-in names', () => {
        const model = NODE_SCHEMAS[type].$defs.Env0APIKeyCredential;
        expect(model.title).toBe('env zero API Key');
        expect(model.properties.api_key_id['ui:widget']).toBe('password');
        expect(model.properties.api_key_secret['ui:widget']).toBe('password');
        expect(model.properties.approved_resources_json.default).toBe('{"organizations":[],"projects":[],"environments":[],"deployments":[]}');
        expect(model.properties.include_labels.default).toBe(false);
        expect(model['x-credential-type']).toBeUndefined();
        expect(model.properties.password).toBeUndefined();
        expect(model.properties.access_token).toBeUndefined();
        expect(getProviderConfigByCredentialType(family)).toBeUndefined();
        expect(CREDENTIAL_TYPE_MAP[model.title]).toBe(family);
        expect(humanizeCredentialLabel(model.title)).toBe(model.title);
        expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'env0', acceptedTypes: [family], label: model.title });
    });
    it('auto-selects only a viewer-owned native token', () => {
        upsertCredentialsIntoCache([{ id: 'foreign', credential_type: 'env0_oidc', name: 'Foreign', owned_by_me: true },
            { id: 'display-only', credential_type: family, name: 'Display only' }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({});
        upsertCredentialsIntoCache([{ id: 'native', credential_type: family, name: 'Fixture token', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({ [family]: 'native' });
    });
    it('exposes nine closed reads with typed parent selectors and honest offsets', () => {
        expect(getAgentToolOperations(type).map(op => op.operation).sort()).toEqual(['check_connection',
            'get_deployment', 'get_environment', 'get_organization', 'get_project',
            'list_deployments', 'list_environments', 'list_organizations', 'list_projects']);
        const schema = NODE_SCHEMAS[type];
        expect(schema.$defs.GetDeployment.properties.environment_id['x-dynamic-options'].depends_on).toEqual(['organization_id', 'project_id']);
        expect(schema.$defs.GetDeployment.properties.deployment_id['x-resource-type']).toBe('env0_deployment');
        expect(schema.$defs.ListEnvironments.properties.limit.maximum).toBe(100);
        expect(schema.$defs.ListEnvironments.properties.offset.default).toBe(0);
        expect(schema.$defs.ListProjects.properties.offset).toBeUndefined();
        expect(schema.$defs.GetEnvironment.properties.fields).toBeUndefined();
        expect(schema.$defs.GetDeployment.properties.base_url).toBeUndefined();
        expect(schema.$defs.ListDeployments.properties.query).toBeUndefined();
    });
    it('uses the native asset for saved credentials', () => {
        setNodeIconData({ [type]: { type, label: Env0Node.label, description: '', credentialKeys: [family], iconColor: '',
            iconHtml: '<img src="/icons/env0-brand-vector.svg" />', dimensions: Env0Node.dimensions } });
        expect(getCredentialIcon(family).hasServiceIcon).toBe(true);
    });
});
