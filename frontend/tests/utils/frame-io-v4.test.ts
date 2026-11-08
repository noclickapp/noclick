import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo, getAgentToolOperations, filterConfigForExecution } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { FrameIoV4Node } from '~/components/workflow/nodes/integrations/frame-io-v4';

describe('Frame.io V4', () => {
  beforeAll(() => loadNodeSchemas(['automation-frame-io-v4']));
  it('discovers the definition and manual access token credential', () => {
    expect(FrameIoV4Node.type).toBe('automation-frame-io-v4');
    expect(FrameIoV4Node.label).toBe('Frame.io V4');
    const method = methodFromRequirement(requirementsFromSchema(NODE_SCHEMAS[FrameIoV4Node.type])[0]);
    expect(method).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    expect(method.credential_fields?.find(field => field.name === 'legacy_developer_token')?.options).toHaveLength(2);
    expect(getNodeCredentialInfo(FrameIoV4Node.type)?.acceptedTypes).toEqual(['frame_io_v4_token']);
    expect(getCredentialTypeFromSchemaTitle('Frame.io V4 Access Token')).toBe('frame_io_v4_token');
    expect(getCredentialTypeFromSchemaTitle('FrameIoV4TokenCredential')).toBe('frame_io_v4_token');
  });
  it('offers 25 operations and keeps fields within the selected action', () => {
    const operations = getAgentToolOperations(FrameIoV4Node.type);
    expect(operations).toHaveLength(25);
    expect(operations.map(op => op.operation)).toEqual(expect.arrayContaining(['get_current_user', 'create_project', 'create_comment', 'delete_file']));
    expect(filterConfigForExecution(FrameIoV4Node.type, { operation: 'update_file', account_id: 'a', file_id: 'f', name: 'new.mov', text: 'unrelated' })).toEqual({ operation: 'update_file', account_id: 'a', file_id: 'f', name: 'new.mov' });
  });
});
