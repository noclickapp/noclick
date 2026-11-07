// Exercises PredictLeads native credential, selector and editor helpers.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement, type ComponentType } from 'react';

vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
vi.mock('~/lib/applyNodeUpdate', () => ({ updateNodeInList: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn(), clear: vi.fn() } }));

import { PredictLeadsNode } from '~/components/workflow/nodes/PredictLeadsNode';
import { NODE_DEFINITION_FILES } from '~/components/workflow/nodes/nodeDefinitions';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMAS, getAgentToolOperations, getNodeCredentialInfo, loadAllNodeSchemas, credentialMarks } from '~/utils/nodeSchemas';
import { humanizeCredentialLabel, fixWordCasing } from '~/utils/credentialLabels';
import { invalidateCredentialsCache, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { getProviderConfigByCredentialType } from '~/utils/oauthProviders';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { getCredentialIcon } from '~/utils/credentialIcons';

const family = 'predictleads_api_key_token';
const type = 'automation-predictleads';

describe('native PredictLeads wiring', () => {
    beforeAll(async () => { await loadAllNodeSchemas(); });
    beforeEach(() => invalidateCredentialsCache());
    it('registers the native editor and sourced brand asset', () => {
        expect(NODE_DEFINITION_FILES.filter(([nodeType]) => nodeType === type)).toEqual([[type, 'PredictLeadsNode']]);
        expect(renderToStaticMarkup(createElement(PredictLeadsNode.Icon as ComponentType<any>))).toContain('/icons/predictleads-preferred-brand.svg');
        expect(PredictLeadsNode.iconColor).toBe('');
    });
    it('keeps the supplied header pair masked and manual, with an explicit local credit grant', () => {
        const model = NODE_SCHEMAS[type].$defs.PredictLeadsAPIKeyTokenCredential;
        expect(model.title).toBe('PredictLeads API Key and Token');
        expect(model.properties.api_key['ui:widget']).toBe('password');
        expect(model.properties.api_token['ui:widget']).toBe('password');
        expect(model.required).toEqual(expect.arrayContaining(['api_key', 'api_token', 'allowed_companies_json']));
        expect(model.properties.allow_credit_reads.default).toBe(false);
        expect(model['x-credential-type']).toBeUndefined();
        expect(getProviderConfigByCredentialType(family)).toBeUndefined();
        expect(CREDENTIAL_TYPE_MAP[model.title]).toBe(family);
        expect(humanizeCredentialLabel(model.title)).toBe(model.title);
        expect(fixWordCasing('Predictleads API Key')).toBe('PredictLeads API Key');
        expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'predictleads', acceptedTypes: [family], label: model.title });
        expect(NODE_SCHEMAS[type].$defs.ListJobOpenings.properties.company['x-dynamic-options'].field_name).toBe('company');
        expect(NODE_SCHEMAS[type].$defs.ListJobOpenings.properties.categories['ui:widget']).toBe('list');
    });
    it('selects only a viewer-owned native credential', () => {
        upsertCredentialsIntoCache([{ id: 'foreign', credential_type: 'predictleads_oauth', name: 'Foreign', owned_by_me: true },
            { id: 'display-only', credential_type: family, name: 'Display only' }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({});
        upsertCredentialsIntoCache([{ id: 'native', credential_type: family, name: 'Fixture pair', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({ [family]: 'native' });
    });
    it('exposes exactly five reads and scoped company selectors', () => {
        const operations = getAgentToolOperations(type);
        expect(operations.map(op => op.operation).sort()).toEqual(['check_connection', 'get_company', 'list_job_openings', 'list_news_events', 'list_technology_detections']);
        expect(operations.find(op => op.operation === 'get_company')?.scopableFields).toEqual(expect.arrayContaining([
            expect.objectContaining({ field: 'company', resourceType: 'predictleads_company', loaderField: 'company' }),
        ]));
    });
    it('uses the same brand asset for saved credentials', () => {
        setNodeIconData({ [type]: { type, label: PredictLeadsNode.label, description: '', iconColor: '',
            iconHtml: '<img src="/icons/predictleads-preferred-brand.svg" />', dimensions: PredictLeadsNode.dimensions,
            credentialKeys: credentialMarks(() => true).get(type) } });
        expect(getCredentialIcon(family).hasServiceIcon).toBe(true);
    });
});
