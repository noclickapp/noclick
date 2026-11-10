// @vitest-environment happy-dom
// (The node catalog's ag-grid sets a bare `Node = {}` where there's no DOM.)
// A retired integration (its service shut down, `WorkflowNode.retired`) is offered by no listing in the app, while a
// workflow that already has one still draws it, reads its schema and finds its credential.
import { beforeAll, describe, expect, it } from 'vitest';
import {
    getAllSerializedNodeMeta,
    getDeclaredIntegrationCategories,
    listAgentToolProviderTypes,
    listIntegrationNodeTypes,
    listProviderIntegrations,
    listTriggerOptions,
    resolveNodeTypeFromSlug,
    resolveProviderTypeFromSlug,
    typeToSlug,
} from '~/lib/nodeCatalog.server';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { buildReactFlowNodeTypes, getSearchableNodes } from '~/components/workflow/nodes/nodeRegistry';
import {
    NODE_DEFINITION_TYPES,
    getNodeDefinition,
    isOfferedNodeType,
    loadNodeDefinitions,
    offeredNodeDefinitions,
} from '~/components/workflow/nodes/nodeDefinitions';
import { NODE_SCHEMA_TYPES, getAgentWirableCatalog, getNodeCredentialInfo, loadAllNodeSchemas } from '~/utils/nodeSchemas';
import { isListedNodeType } from '~/utils/nodeMeta';
import { getServiceCredentialOptions, getServiceForCredentialType } from '~/utils/credentialTypes';

const RETIRED = NODE_SCHEMA_TYPES.filter((type) => !isListedNodeType(type));

beforeAll(async () => {
    await Promise.all([loadNodeDefinitions(NODE_DEFINITION_TYPES), loadAllNodeSchemas()]);
    setNodeIconData(getAllSerializedNodeMeta());
}, 60_000);

const noneRetired = (types: Iterable<string>) => expect([...types].filter((type) => RETIRED.includes(type))).toEqual([]);

describe('retired integrations', () => {
    it('are the services that shut down, and only those', () => {
        expect(RETIRED).toEqual(expect.arrayContaining(['automation-humanloop', 'automation-starton', 'automation-rkvst']));
        expect(isListedNodeType('automation-freshteam')).toBe(true);
        expect(isListedNodeType('automation-toneden')).toBe(true);
        expect(isListedNodeType('automation-slack')).toBe(true);
    });

    it('appear on no listing', () => {
        // The node palette and its search.
        for (const type of RETIRED) expect(isOfferedNodeType(type)).toBe(false);
        noneRetired(getSearchableNodes().map((node) => node.type));
        noneRetired(offeredNodeDefinitions().map((node) => node.type));
        // The agent's add-a-trigger and add-a-tool palette.
        const wirable = getAgentWirableCatalog();
        noneRetired([...wirable.triggers.map((entry) => entry.nodeType), ...wirable.tools]);
        // Connections' catalog and the connect dialog's picker list only listed services.
        const services = getServiceCredentialOptions();
        expect(services.some((service) => service.value === 'automation-slack' && service.listed)).toBe(true);
        noneRetired(services.filter((service) => service.listed).map((service) => service.value));
        // The integration catalog the public pages, the sitemap and llms.txt read.
        expect(listIntegrationNodeTypes()).toContain('automation-freshteam');
        noneRetired(listIntegrationNodeTypes());
        noneRetired(listTriggerOptions().map((option) => option.type));
        noneRetired(listAgentToolProviderTypes());
        noneRetired(listProviderIntegrations().map((provider) => provider.type));
        const declared = Object.keys(getDeclaredIntegrationCategories());
        for (const type of RETIRED) {
            const slug = typeToSlug(type);
            expect(declared).not.toContain(slug);
            expect(resolveNodeTypeFromSlug(slug)).toBeNull();
            expect(resolveProviderTypeFromSlug(slug)).toBeNull();
        }
        expect(resolveNodeTypeFromSlug('freshteam')).toBe('automation-freshteam');
    });

    it('still draw, configure and find their credential in a workflow that has one', () => {
        const nodeTypes = buildReactFlowNodeTypes();
        for (const type of RETIRED) {
            expect(nodeTypes[type]).toBeDefined();
            expect(getNodeDefinition(type)?.label).toBeTruthy();
            expect(getNodeCredentialInfo(type)?.acceptedTypes.length).toBeGreaterThan(0);
        }
        expect(getNodeCredentialInfo('automation-humanloop')?.acceptedTypes).toContain('humanloop_api_key');
        // An account already connected to it keeps its app's name on Connections and the account cards.
        const service = getServiceForCredentialType('humanloop_api_key');
        expect(service?.label).toBe('Humanloop');
        expect(service?.listed).toBe(false);
    });
});
