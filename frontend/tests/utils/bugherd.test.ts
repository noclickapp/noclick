// Exercises the generated BugHerd schema, discovered metadata and execution filtering.
import { beforeAll, describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/bugherd.json';
import { getNodeCredentialInfo, filterConfigForExecution, loadNodeSchemas } from '~/utils/nodeSchemas';

import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';

describe('native BugHerd editor contract', () => {
    beforeAll(() => loadNodeSchemas(['automation-bugherd']));
    it('exposes nine actual reads, a password key and explicit task ancestry', () => {
        const operations = Object.values(schema.$defs).flatMap(model => 'properties' in model && 'operation' in model.properties ? [model.properties.operation.const] : []);
        expect(new Set(operations).size).toBe(9);
        expect(operations).not.toContain('create_task');
        expect(schema.$defs.BugHerdApiKeyCredential.required).toEqual(['api_key']);
        expect(schema.$defs.BugHerdApiKeyCredential.properties.api_key['ui:widget']).toBe('password');
        expect(schema.$defs.GetTask.properties.task_id['x-dynamic-options'].depends_on).toBe('project_id');
        expect(getNodeCredentialInfo('automation-bugherd')?.acceptedTypes).toEqual(['bugherd_api_key']);
        expect(getNodeCredentialInfo('automation-bugherd')?.label).toBe('BugHerd API Key');
    });

    it('discovers the native credential family through per-node metadata', () => {
        expect(CREDENTIAL_TYPE_MAP.BugHerdApiKeyCredential).toBe('bugherd_api_key');
        expect(INTEGRATION_METADATA.autoSelectTypes).toContain('automation-bugherd');
        expect(INTEGRATION_METADATA.nodeMeta['automation-bugherd'].agentToolProvider).toBe(true);
    });

    it('preserves current saved metadata and prunes fields of a different operation', () => {
        const filtered = filterConfigForExecution('automation-bugherd', { operation: 'list_projects', active_only: true, page: 2,
            label: 'Owned projects', _settings: { retryOnFail: 'false' }, task_id: 29 });
        expect(filtered).toEqual({ operation: 'list_projects', active_only: true, page: 2,
            label: 'Owned projects', _settings: { retryOnFail: 'false' } });
    });
});
