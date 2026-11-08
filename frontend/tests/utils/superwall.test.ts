// Exercises Superwall's real credential, selector and native editor helpers.
// These checks cover the self-registering definition and generated credential metadata.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement, type ComponentType, type ImgHTMLAttributes } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

vi.mock('@lobehub/icons', () => ({ Anthropic: () => null, MCP: () => null, OpenAI: () => null }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), clear: vi.fn(), delete: vi.fn() } }));

import { SuperwallNode } from '~/components/workflow/nodes/integrations/superwall';
import { NODE_DEFINITION_FILES, loadNodeDefinitions, getNodeDefinition } from '~/components/workflow/nodes/nodeDefinitions';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { kindFromCredentialType } from '~/lib/credentialMethodKind';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { getCredentialIcon } from '~/utils/credentialIcons';

const type = 'automation-superwall';
const family = 'superwall_organization_api_key';

describe('native Superwall metadata reads', () => {
    beforeEach(async () => { invalidateCredentialsCache(); await loadNodeSchemas([type]); await loadNodeDefinitions([type]); });
    it('registers the native editor and unchanged official favicon', () => {
        expect(NODE_DEFINITION_FILES.filter(([nodeType]) => nodeType === type)).toEqual([[type, 'integrations/superwall']]);
        expect(getNodeDefinition(type)).toBe(SuperwallNode);
        expect(renderToStaticMarkup(createElement(SuperwallNode.Icon as ComponentType<ImgHTMLAttributes<HTMLImageElement>>))).toContain('/icons/superwall.svg');
        expect(SuperwallNode.iconColor).toBe('');
    });
    it('keeps the organization key manual and masked with saved project restrictions', () => {
        const model = NODE_SCHEMAS[type].$defs.SuperwallOrganizationAPIKeyCredential;
        expect(model.title).toBe('Superwall Organization API Key');
        expect(model.properties.api_key['ui:widget']).toBe('password');
        expect(model.required).toEqual(expect.arrayContaining(['api_key', 'organization_id', 'allowed_project_ids_json', 'witness_project_id']));
        expect(model.properties.read_scopes.default).toBe('projects:read');
        expect(model['x-credential-type']).toBeUndefined();
        expect(getProviderConfigByCredentialType(family)).toBeUndefined();
        expect(kindFromCredentialType(model['x-credential-type'])).toBe('api_key');
        expect(CREDENTIAL_TYPE_MAP[model.title]).toBe(family);
        expect(humanizeCredentialLabel(model.title)).toBe(model.title);
        expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'superwall', acceptedTypes: [family], label: model.title });
    });
    it('selects only a viewer-owned native key', () => {
        upsertCredentialsIntoCache([{ id: 'foreign', credential_type: 'superwall_oauth', name: 'Foreign', owned_by_me: true },
            { id: 'display-only', credential_type: family, name: 'Display only' }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({});
        upsertCredentialsIntoCache([{ id: 'native', credential_type: family, name: 'Fixture key', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({ [family]: 'native' });
    });
    it('exposes exactly twelve reads and project/application/chart dependencies', () => {
        const operations = getAgentToolOperations(type);
        expect(operations.map(op => op.operation).sort()).toEqual(['check_connection', 'get_application', 'get_chart_definitions',
            'get_entitlement', 'get_organization', 'get_product', 'get_project', 'list_applications', 'list_entitlements',
            'list_products', 'list_projects', 'query_chart_data']);
        expect(operations.find(op => op.operation === 'query_chart_data')?.scopableFields).toEqual(expect.arrayContaining([
            expect.objectContaining({ field: 'project_id', resourceType: 'superwall_project', loaderField: 'project_id' }),
            expect.objectContaining({ field: 'application_id', resourceType: 'superwall_application', loaderField: 'application_id' }),
        ]));
        const fields = NODE_SCHEMAS[type].$defs.QueryChartData.properties;
        expect(fields.application_id['x-dynamic-options'].depends_on).toBe('project_id');
        expect(fields.chart_key['x-dynamic-options'].depends_on).toBe('application_id');
        expect(fields.max_data_points.maximum).toBe(1000);
    });
    it('uses the native asset for saved credentials', () => {
        setNodeIconData({ [type]: { type, label: SuperwallNode.label, description: '', iconColor: '',
            credentialKeys: [family], iconHtml: '<img src="/icons/superwall.svg" />', dimensions: SuperwallNode.dimensions } });
        expect(getCredentialIcon(family).hasServiceIcon).toBe(true);
    });
});
