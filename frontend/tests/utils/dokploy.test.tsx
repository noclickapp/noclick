import React from 'react';
import { expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { NODE_SCHEMAS, getNodeCredentialInfo, filterConfigForExecution, loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { DokployNode } from '~/components/workflow/nodes/integrations/dokploy';
vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
await loadNodeSchemas(['automation-dokploy']);
it('discovers the native token method and its reviewed provider label', () => {
    const schema = NODE_SCHEMAS['automation-dokploy'];
    expect(CREDENTIAL_TYPE_MAP.DokployAPIKeyCredential).toBe('dokploy_api_key');
    expect(getNodeCredentialInfo('automation-dokploy')?.acceptedTypes).toEqual(['dokploy_api_key']);
    const requirements = requirementsFromSchema(schema);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    expect(schema.$defs.DokployAPIKeyCredential.title).toBe('Dokploy API Key');
    expect(schema.$defs.DokployAPIKeyCredential.properties.api_key['ui:sensitive']).toBe(true);
});
it('preserves dependent selectors and removes fields from other operations', () => {
    const schema = NODE_SCHEMAS['automation-dokploy'];
    const operations = Object.keys(schema.properties.config.discriminator.mapping);
    expect(operations).toHaveLength(16);
    expect(schema.$defs.GetApplication.properties.application_id['x-dynamic-options'].depends_on).toEqual(['project_id', 'environment_id']);
    expect(filterConfigForExecution('automation-dokploy', { operation: 'get_project', project_id: 'project-one', environment_id: 'other-operation', name: 'other-operation' })).toEqual({ operation: 'get_project', project_id: 'project-one' });
});
it('uses the checked-in vendor icon in the discovered tile', () => {
    expect(DokployNode.type).toBe('automation-dokploy');
    const Icon = DokployNode.Icon;
    expect(renderToStaticMarkup(<Icon />)).toContain('src="/icons/dokploy.svg"');
});
