// @vitest-environment happy-dom
// UNRUN mounted native editor, typed controls, save/export/hydration and credential form.
// Original SVG bytes and actual selection/icon seams are checked without provider calls.
import React, { useState } from 'react';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { NodeConfig } from '~/components/workflow/NodeConfig';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
import { ExoscaleNode } from '~/components/workflow/nodes/ExoscaleNode';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { applyNodeUpdate, buildSaveConfig, createWorkflowNode } from '~/lib/applyNodeUpdate';
import { buildWorkflowExport } from '~/lib/workflowIO';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ success: true, valid: true, errors: [], options: [] })) }));
vi.mock('~/lib/analytics', () => ({ useAnalytics: () => ({ track: vi.fn(), logActivity: vi.fn() }) }));
vi.mock('~/hooks/useAgentCredentialsRequired', () => ({ useAgentCredentialsRequired: () => [] }));
const TYPE = 'automation-exoscale';
beforeAll(async () => { await loadNodeSchemas([TYPE]); });
afterEach(() => { cleanup(); removeCredentialsFromCache(['exoscale-display', 'exoscale-owned']); });
function Panel({ initial = {} }: { initial?: Record<string, unknown> }) {
  const [node, setNode] = useState(() => createWorkflowNode('exoscale-panel', TYPE, { x: 0, y: 0 }, { operation: 'list_instances', ...initial }));
  const saved = JSON.parse(JSON.stringify(buildSaveConfig(node)));
  const exported = JSON.parse(buildWorkflowExport([node], [], 'Fixture')).workflow_data.nodes[0].config;
  return <>
    <NodeConfig nodeType={TYPE} nodeId={node.id} operation={node.data.operation as string} config={node.data.config as any}
      onChange={config => setNode(current => applyNodeUpdate(current, { config }))} />
    <output data-testid="saved">{JSON.stringify(saved)}</output>
    <output data-testid="exported">{JSON.stringify(exported)}</output>
    <button onClick={() => setNode(createWorkflowNode(node.id, TYPE, { x: 0, y: 0 }, saved))}>Hydrate</button>
  </>;
}
it('registers six closed APIv2 reads and the literal supplied key/secret form', () => {
  expect(AVAILABLE_NODES.some(node => node.type === TYPE)).toBe(true);
  expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual(['exoscale_api_key']);
  const schema = NODE_SCHEMAS[TYPE];
  expect(schema.properties.config.oneOf.map((ref: any) => schema.$defs[ref.$ref.split('/').pop()].properties.operation.const))
    .toEqual(['list_instances', 'get_instance', 'list_instance_types', 'get_instance_type', 'list_anti_affinity_groups', 'get_anti_affinity_group']);
  expect(schema.$defs.ListInstances.properties.max_records.maximum).toBe(1000);
  expect(schema.$defs.GetInstance.required).toContain('instance_id');
  expect(schema.$defs.GetInstanceType.required).toContain('instance_type_id');
  expect(schema.$defs.GetAntiAffinityGroup.required).toContain('anti_affinity_group_id');
  expect(schema.$defs.ListInstances.properties.include_names.default).toBe(false);
  const credential = schema.$defs.ExoscaleAPIKeyCredential;
  expect(credential['x-credential-type']).toBeUndefined();
  expect(credential.required).toEqual(['api_key', 'api_secret']);
  expect(credential.properties.api_key['ui:widget']).toBe('password');
  expect(credential.properties.api_secret['ui:widget']).toBe('password');
  expect(credential.properties.zone.enum).toEqual(['ch-gva-2', 'de-fra-1']);
  expect(credential.properties.refresh_token).toBeUndefined();
});
it('uses the actual cache selector and excludes display-only descriptors', () => {
  upsertCredentialsIntoCache([
    { id: 'exoscale-display', name: 'Descriptor', credential_type: 'exoscale_api_key', owned_by_me: false },
    { id: 'exoscale-owned', name: 'Owned', credential_type: 'exoscale_api_key', owned_by_me: true },
  ] as any);
  expect(autoSelectCredentialFromCache(TYPE)).toEqual({ exoscale_api_key: 'exoscale-owned' });
});
it('preserves original official SVG bytes in the initialized real icon registry', () => {
  const bytes = readFileSync(resolve(process.cwd(), 'public/icons/exoscale-brand-vector.svg'));
  expect(createHash('sha256').update(bytes).digest('hex')).toBe('f6cdc801de57ea0227a910debfb14dd8e0cf36c671f573b0a1871bb6fe497155');
  setNodeIconData({ [TYPE]: { type: TYPE, label: ExoscaleNode.label, description: ExoscaleNode.description, credentialKeys: ['exoscale_api_key'], iconColor: '', iconHtml: renderToStaticMarkup(<ExoscaleNode.Icon />), dimensions: ExoscaleNode.dimensions! } });
  const icon = getCredentialIcon('exoscale_api_key');
  expect(icon.hasServiceIcon).toBe(true);
  expect(render(<icon.Icon />).container.querySelector('img')?.getAttribute('src')).toBe('/icons/exoscale-brand-vector.svg');
  expect(humanizeCredentialLabel('ExoscaleAPIKey')).toBe('Exoscale API Key');
});
it('mounted record/name controls save integers and false through export/hydration', async () => {
  const { container } = render(<Panel />);
  fireEvent.change(container.querySelector('[data-field-key="max_records"] input')!, { target: { value: '20' } });
  fireEvent.change(container.querySelector('[data-field-key="include_names"] select')!, { target: { value: 'false' } });
  await waitFor(() => expect(JSON.parse(screen.getByTestId('saved').textContent!)).toMatchObject({ max_records: 20, include_names: false }));
  expect(JSON.parse(screen.getByTestId('exported').textContent!)).toMatchObject({ max_records: 20, include_names: false });
  fireEvent.click(screen.getByText('Hydrate'));
  expect(JSON.parse(screen.getByTestId('saved').textContent!)).toMatchObject({ max_records: 20, include_names: false });
});
it('actual visible credential form masks supplied key and secret and emits no hidden discriminator', async () => {
  const schema = NODE_SCHEMAS[TYPE].$defs.ExoscaleAPIKeyCredential;
  const fields = Object.entries(schema.properties).filter(([, property]: any) => !property['ui:hidden']).map(([name, property]: any) => ({ name, label: property.title ?? name, type: property['ui:widget'] === 'password' ? 'password' : 'text', required: (schema.required ?? []).includes(name) }));
  const save = vi.fn(async (_name: string, _data: Record<string, string>) => null);
  const { container } = render(<CredentialCreatePanel app="Exoscale" fields={fields} onSave={save} />);
  fireEvent.change(container.querySelector('[data-field="api_key"] input')!, { target: { value: 'synthetic-issued-key' } });
  fireEvent.change(container.querySelector('[data-field="api_secret"] input')!, { target: { value: 'synthetic-issued-secret' } });
  expect(container.querySelector<HTMLInputElement>('[data-field="api_key"] input')?.type).toBe('password');
  expect(container.querySelector<HTMLInputElement>('[data-field="api_secret"] input')?.type).toBe('password');
  expect(container.querySelector('[data-field="credential_type"]')).toBeNull();
  expect(container.querySelector('[data-field="refresh_token"]')).toBeNull();
  fireEvent.click(screen.getByText('Connect'));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][1]).toEqual({ api_key: 'synthetic-issued-key', api_secret: 'synthetic-issued-secret' });
});
