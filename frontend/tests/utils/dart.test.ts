import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({
    valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
}));
import { DartNode } from '~/components/workflow/nodes/integrations/dart';
import { getFieldsForOption } from '~/utils/schemaFieldExtractor';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import {
    getNodeCredentialInfo,
    loadNodeSchemas,
    NODE_SCHEMAS,
} from '~/utils/nodeSchemas';
import {
    createWorkflowNode,
    buildSaveConfig,
    applyNodeUpdate,
} from '~/lib/applyNodeUpdate';

describe('Dart integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-dart']));
    it('discovers a manually connected, masked API token in productivity', () => {
        expect(DartNode.category).toBe('productivity');
        expect(getNodeCredentialInfo('automation-dart')).toBeTruthy();
        expect(CREDENTIAL_TYPE_MAP.DartAPITokenCredential).toBe(
            'dart_api_token'
        );
        expect(CREDENTIAL_TYPE_MAP['Dart API Token']).toBe('dart_api_token');
        const form =
            NODE_SCHEMAS['automation-dart'].$defs.DartAPITokenCredential;
        expect(form.required).toEqual(['api_token']);
        expect(form.properties.api_token['ui:widget']).toBe('password');
        expect(form.properties.credential_type.default).toBe('dart_api_token');
        expect(form).not.toHaveProperty('x-oauth-provider');
    });
    it('shows operation inputs without an extra discriminator field', () => {
        const fields = getFieldsForOption(
            'automation-dart',
            undefined,
            'update_task'
        );
        expect(fields.some((field) => field.key === 'task_id')).toBe(true);
        expect(fields.some((field) => field.key === 'operation')).toBe(false);
    });
    it('persists task IDs and credential selection through the shared save helpers', () => {
        const node = createWorkflowNode(
            'dart-test',
            'automation-dart',
            { x: 0, y: 0 },
            {
                operation: 'update_task',
                task_id: 'Ab12Cd34Ef56',
                status: 'Done',
                tags: [],
            }
        );
        const saved = buildSaveConfig(
            applyNodeUpdate(node, {
                credentialIds: { dart_api_token: 'owned-credential' },
                config: { task_id__label: 'Ship integration' },
            })
        );
        expect(saved.operation).toBe('update_task');
        expect(saved.task_id).toBe('Ab12Cd34Ef56');
        expect(saved.task_id__label).toBe('Ship integration');
        expect(saved.tags).toEqual([]);
        expect(saved.credentialIds).toEqual({
            dart_api_token: 'owned-credential',
        });
    });
});
