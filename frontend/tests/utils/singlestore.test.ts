// SingleStore schema, native UI and credential-cache contracts.
// Load its schema through the current lazy registry before exercising helpers.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { SingleStoreNode } from '~/components/workflow/nodes/integrations/singlestore';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo, filterConfigForExecution, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { kindFromCredentialType } from '~/lib/credentialMethodKind';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { invalidateCredentialsCache, removeCredentialsFromCache, setActiveCredentialWorkflow, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';

const type = 'automation-singlestore';
beforeAll(() => loadNodeSchemas([type]));
const operations = ['get_organization', 'list_projects', 'get_project', 'rename_project', 'list_regions', 'list_shared_tier_regions',
    'list_clusters', 'get_cluster', 'list_stage_folder', 'get_stage_file_metadata', 'create_stage_folder', 'move_empty_stage_folder', 'delete_empty_stage_folder'];

describe('SingleStore native schema and wiring', () => {
    it('uses the organization-bound supplied Management key and thirteen closed operations', () => {
        expect(SingleStoreNode.type).toBe(type);
        expect(SingleStoreNode.label).toBe('SingleStore');
        expect(CREDENTIAL_TYPE_MAP.SingleStoreManagementCredential).toBe('singlestore_management_api_key');
        expect(CREDENTIAL_TYPE_MAP['SingleStore Management API']).toBe('singlestore_management_api_key');
        expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'singlestore', acceptedTypes: ['singlestore_management_api_key'], label: 'SingleStore Organization' });
        expect(humanizeCredentialLabel('SingleStore Management API')).toBe('Single Store Management API');
        expect(getAgentToolOperations(type).map(op => op.operation).sort()).toEqual([...operations].sort());
        expect(isAgentToolProviderType(type)).toBe(true);
        const credential = NODE_SCHEMAS[type].$defs.SingleStoreManagementCredential;
        expect(credential.properties.credential_type.const).toBe('singlestore_management_api_key');
        expect(credential.required).toEqual(expect.arrayContaining(['api_key', 'organization_id']));
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(credential['x-credential-type']).toBeUndefined();
        expect(kindFromCredentialType(credential['x-credential-type'])).toBe('api_key');
        expect(credential.properties.endpoint).toBeUndefined();
        expect(credential.properties.password).toBeUndefined();
    });
    it('filters declared stale variant fields and scopes cluster pickers to project', () => {
        const config = { operation: 'get_cluster', project_id: 'project', cluster_id: 'cluster', name: 'stale', folder_path: 'stale/' };
        expect(filterConfigForExecution(type, config)).toEqual({ operation: 'get_cluster', project_id: 'project', cluster_id: 'cluster' });
        const defs = Object.values<any>(NODE_SCHEMAS[type].$defs);
        const cluster = defs.find(def => def.properties?.operation?.const === 'get_cluster');
        expect(cluster.required).toEqual(expect.arrayContaining(['project_id', 'cluster_id']));
        expect(cluster.properties.cluster_id['x-dynamic-options'].depends_on).toEqual(['project_id']);
        const directory = defs.find(def => def.properties?.operation?.const === 'move_empty_stage_folder');
        expect(directory.required).toEqual(expect.arrayContaining(['folder_path', 'new_folder_path']));
        for (const operation of ['execute_sql', 'get_secret', 'create_cluster', 'suspend_cluster', 'invite_user', 'upload_file', 'download_file'])
            expect(operations).not.toContain(operation);
    });
    it('retains the exact official SVG and actual selection/registration entries', () => {
        const tree = join(__dirname, '../..');
        const svg = readFileSync(join(tree, 'public/icons/singlestore.svg'), 'utf8');
        expect(svg).toContain('viewBox="0 0 197 68"');
        expect(svg).not.toContain('<script');
        expect(readFileSync(join(tree, 'app/components/workflow/nodes/integrations/singlestore.tsx'), 'utf8')).toContain(`type: '${type}'`);
        expect(JSON.parse(readFileSync(join(tree, 'app/schemas/nodeMeta/singlestore.json'), 'utf8')).type).toBe(type);
    });
});
describe('real SingleStore credential cache selection', () => {
    beforeEach(() => {
        removeCredentialsFromCache(['native-singlestore', 'foreign-singlestore', 'owner-singlestore']);
        invalidateCredentialsCache();
        setActiveCredentialWorkflow('fixture-workflow');
    });
    it('selects only an owned native current descriptor', () => {
        upsertCredentialsIntoCache([
            { id: 'foreign-singlestore', credential_type: 'foreign_key', name: 'Foreign', owned_by_me: true },
            { id: 'owner-singlestore', credential_type: 'singlestore_management_api_key', name: 'Owner descriptor', owned_by_me: false },
        ]);
        expect(autoSelectCredentialFromCache(type)).toEqual({});
        upsertCredentialsIntoCache([{ id: 'native-singlestore', credential_type: 'singlestore_management_api_key', name: 'Native', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({ singlestore_management_api_key: 'native-singlestore' });
    });
});

