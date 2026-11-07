// @vitest-environment happy-dom
// UNRUN mounted native editor, typed controls, save/export/hydration and credential form.
// Original PNG bytes and actual selection/icon seams are checked without provider calls.
import React, { useState } from 'react';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { NodeConfig } from '~/components/workflow/NodeConfig';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
import { HetrixToolsNode } from '~/components/workflow/nodes/HetrixToolsNode';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { humanizeCredentialLabel, fixWordCasing } from '~/utils/credentialLabels';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { applyNodeUpdate, buildSaveConfig, createWorkflowNode } from '~/lib/applyNodeUpdate';
import { buildWorkflowExport } from '~/lib/workflowIO';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ success: true, valid: true, errors: [], options: [] })) }));
vi.mock('~/lib/analytics', () => ({ useAnalytics: () => ({ track: vi.fn(), logActivity: vi.fn() }) }));
vi.mock('~/hooks/useAgentCredentialsRequired', () => ({ useAgentCredentialsRequired: () => [] }));
const TYPE = 'automation-hetrixtools';
beforeAll(async () => { await loadNodeSchemas([TYPE]); });
afterEach(() => { cleanup(); removeCredentialsFromCache(['hetrixtools-display', 'hetrixtools-owned']); });
function Panel({ initial = {} }: { initial?: Record<string, unknown> }) {
  const [node, setNode] = useState(() => createWorkflowNode('hetrixtools-panel', TYPE, { x: 0, y: 0 }, { operation: 'list_uptime_monitors', ...initial }));
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
it('registers seven current v3 reads and the literal issued-key form', () => {
  expect(AVAILABLE_NODES.some(node => node.type === TYPE)).toBe(true);
  expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual(['hetrixtools_api_key']);
  const schema = NODE_SCHEMAS[TYPE];
  expect(schema.properties.config.oneOf.map((ref: any) => schema.$defs[ref.$ref.split('/').pop()].properties.operation.const))
    .toEqual(['get_api_scope', 'list_uptime_monitors', 'get_uptime_monitor', 'get_uptime_report', 'list_downtimes', 'list_status_pages', 'list_scheduled_maintenance']);
  expect(schema.$defs.ListMonitors.properties.per_page.maximum).toBe(200);
  expect(schema.$defs.ListStatusPages.properties.per_page.maximum).toBe(100);
  expect(schema.$defs.GetReport.properties.days.maximum).toBe(30);
  expect(schema.$defs.GetReport.required).toContain('monitor_id');
  expect(schema.$defs.ListMaintenance.required).toContain('monitor_id');
  expect(schema.$defs.ListMonitors.properties.include_names.default).toBe(false);
  expect(schema.$defs.HetrixToolsAPIKeyCredential.required).toEqual(['api_key']);
  expect(schema.$defs.HetrixToolsAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
  expect(schema.$defs.HetrixToolsAPIKeyCredential.properties.refresh_token).toBeUndefined();
});
it('uses the actual cache selector and excludes display-only descriptors', () => {
  upsertCredentialsIntoCache([
    { id: 'hetrixtools-display', name: 'Descriptor', credential_type: 'hetrixtools_api_key', owned_by_me: false },
    { id: 'hetrixtools-owned', name: 'Owned', credential_type: 'hetrixtools_api_key', owned_by_me: true },
  ] as any);
  expect(autoSelectCredentialFromCache(TYPE)).toEqual({ hetrixtools_api_key: 'hetrixtools-owned' });
});
it('preserves original official PNG bytes in the initialized real icon registry', () => {
  const bytes = readFileSync(resolve(process.cwd(), 'public/icons/hetrixtools.png'));
  expect(createHash('sha256').update(bytes).digest('hex')).toBe('106c44319e3519ab4db66353bf17503bd2fe2a64d292c831fa8f782982566cc8');
  setNodeIconData({ [TYPE]: { type: TYPE, label: HetrixToolsNode.label, description: HetrixToolsNode.description, iconColor: '', iconHtml: renderToStaticMarkup(<HetrixToolsNode.Icon />), credentialKeys: ['hetrixtools_api_key'], dimensions: HetrixToolsNode.dimensions! } });
  const icon = getCredentialIcon('hetrixtools_api_key');
  expect(icon.hasServiceIcon).toBe(true);
  expect(render(<icon.Icon />).container.querySelector('img')?.getAttribute('src')).toBe('/icons/hetrixtools-brand-vector.svg');
  expect(humanizeCredentialLabel('HetrixToolsAPIKey')).toBe('HetrixTools API Key');
  expect(fixWordCasing('hetrixtools')).toBe('HetrixTools');
});
it('mounted page/per_page/name controls save integers and false through export/hydration', async () => {
  const { container } = render(<Panel />);
  fireEvent.change(container.querySelector('[data-field-key="page"] input')!, { target: { value: '2' } });
  fireEvent.change(container.querySelector('[data-field-key="per_page"] input')!, { target: { value: '200' } });
  fireEvent.change(container.querySelector('[data-field-key="include_names"] select')!, { target: { value: 'false' } });
  await waitFor(() => expect(JSON.parse(screen.getByTestId('saved').textContent!)).toMatchObject({ page: 2, per_page: 200, include_names: false }));
  expect(JSON.parse(screen.getByTestId('exported').textContent!)).toMatchObject({ page: 2, per_page: 200, include_names: false });
  fireEvent.click(screen.getByText('Hydrate'));
  expect(JSON.parse(screen.getByTestId('saved').textContent!)).toMatchObject({ page: 2, per_page: 200, include_names: false });
});
it('actual visible credential form masks one supplied key and emits no hidden discriminator', async () => {
  const schema = NODE_SCHEMAS[TYPE].$defs.HetrixToolsAPIKeyCredential;
  const fields = Object.entries(schema.properties).filter(([, property]: any) => !property['ui:hidden']).map(([name, property]: any) => ({ name, label: property.title ?? name, type: property['ui:widget'] === 'password' ? 'password' : 'text', required: (schema.required ?? []).includes(name) }));
  const save = vi.fn(async (_name: string, _data: Record<string, string>) => null);
  const { container } = render(<CredentialCreatePanel app="HetrixTools" fields={fields} onSave={save} />);
  fireEvent.change(container.querySelector('[data-field="api_key"] input')!, { target: { value: 'synthetic-issued-key' } });
  expect(container.querySelector<HTMLInputElement>('[data-field="api_key"] input')?.type).toBe('password');
  expect(container.querySelector('[data-field="credential_type"]')).toBeNull();
  expect(container.querySelector('[data-field="refresh_token"]')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][1]).toEqual({ api_key: 'synthetic-issued-key' });
});
