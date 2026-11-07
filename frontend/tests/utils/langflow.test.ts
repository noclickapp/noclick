import { beforeAll, describe, expect, it, vi } from 'vitest';
import schema from '~/schemas/nodes/langflow.json';
import { LangflowNode } from '~/components/workflow/nodes/integrations/langflow';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));

describe('Langflow native credential wiring', () => {
    beforeAll(() => loadNodeSchemas(['automation-langflow']));
    it('uses actual generated human title, native family, palette and modal schema', () => {
        const title = schema.$defs.LangflowAPIKeyCredential.title;
        expect(title).toBe('Langflow API Key');
        expect(humanizeCredentialLabel(title)).toBe(title);
        expect(getCredentialTypeFromSchemaTitle(title)).toBe('langflow_api_key');
        expect(getNodeCredentialInfo('automation-langflow')?.acceptedTypes).toEqual(['langflow_api_key']);
        expect(LangflowNode.type).toBe('automation-langflow');
        expect(LangflowNode.label).toBe('Langflow');
    });
    it('uses staging field-based credential methods', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['langflow_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
    it('keeps parent scope and actual creator path; has no invented OAuth popup', () => {
        expect(schema.$defs.LangflowGetFlow.properties.flow_id['x-dynamic-options']).toMatchObject({ depends_on: 'project_id' });
        expect(schema.$defs.LangflowCreateEmptyFlow.properties.operation['x-resource-id-path']).toBe('data.id');
        expect(schema.$defs.LangflowAPIKeyCredential).not.toHaveProperty('x-oauth-provider');
        expect(schema.$defs.LangflowAPIKeyCredential.properties.server_url.title).toBe('Public HTTPS Server Origin');
    });
});
