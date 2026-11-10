// Verifies discovery and manual API key connection metadata for MessageBird.
// This protects the connection method and communication category shown to people.
import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { MessageBirdNode } from '~/components/workflow/nodes/integrations/messagebird';

beforeAll(() => loadNodeSchemas(['automation-messagebird']));

it('discovers MessageBird as a communication integration with a manually pasted API key', () => {
    expect(MessageBirdNode.category).toBe('communication');
    expect(getCredentialTypeFromSchemaTitle('MessageBird API Key')).toBe('messagebird_api_key');
    expect(getNodeCredentialInfo(MessageBirdNode.type)?.acceptedTypes).toEqual(['messagebird_api_key']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS[MessageBirdNode.type]);
    expect(requirements).toHaveLength(1);
    const method = methodFromRequirement(requirements[0]);
    expect(method.method_kind).toBe('api_key');
    expect(method.is_oauth).toBe(false);
    expect(method.credential_fields?.map(field => field.name)).toEqual(['api_key']);
});
