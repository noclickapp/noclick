// Exercises Kubernetes credential and operation metadata through frontend consumers.
// These checks guard manual connection and operation switching for the new integration.
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/kubernetes.json'), 'utf8'));

describe('Kubernetes integration consumers', () => {
    beforeAll(() => loadNodeSchemas(['automation-kubernetes']));
    it('connects a pasted token with an editable cluster origin and optional CA', () => {
        expect(getNodeCredentialInfo('automation-kubernetes')?.acceptedTypes).toEqual(['kubernetes_bearer_token']);
        expect(getCredentialTypeFromSchemaTitle('Kubernetes Bearer Token')).toBe('kubernetes_bearer_token');
        expect(getCredentialTypeFromSchemaTitle('KubernetesBearerTokenCredential')).toBe('kubernetes_bearer_token');
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.credential_fields?.map(field => field.name)).toEqual(expect.arrayContaining(['api_server_url', 'token', 'ca_certificate']));
    });
    it('exposes all operations while dropping fields from another operation', () => {
        const operations = getAgentToolOperations('automation-kubernetes');
        expect(operations).toHaveLength(25);
        expect(operations.map(op => op.operation)).toEqual(expect.arrayContaining(['create_job', 'scale_deployment', 'get_pod_logs']));
        expect(filterConfigForExecution('automation-kubernetes', {
            operation: 'scale_deployment', namespace: 'default', name: 'nginx', replicas: 3, tail_lines: 200,
        })).toEqual({ operation: 'scale_deployment', namespace: 'default', name: 'nginx', replicas: 3 });
    });
});
