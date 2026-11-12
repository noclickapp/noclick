// @vitest-environment happy-dom
// UNRUN native editor/control/save/export/hydration and visible API-key form cases.
// Synthetic controls and descriptors are not live UI or provider qualification.
import React, { useState } from 'react';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { NodeConfig } from '~/components/workflow/NodeConfig';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
import { PowerDNSNode } from '~/components/workflow/nodes/integrations/powerdns';
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
const TYPE = 'automation-powerdns';
beforeAll(() => loadNodeSchemas([TYPE]));
afterEach(() => { cleanup(); removeCredentialsFromCache(['powerdns-display', 'powerdns-owned']); });
function Panel({ initial = {} }: { initial?: Record<string, unknown> }) {
  const [node, setNode] = useState(() => createWorkflowNode('powerdns-panel', TYPE, { x: 0, y: 0 }, { operation: 'list_servers', ...initial }));
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
it('registers five closed GETs, required catalog zone locator and existing key family', () => {
  expect(AVAILABLE_NODES.some(node => node.type === TYPE)).toBe(true);
  expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual(['powerdns_api_key']);
  const schema = NODE_SCHEMAS[TYPE];
  expect(schema.properties.config.oneOf.map((ref: any) => schema.$defs[ref.$ref.split('/').pop()].properties.operation.const))
    .toEqual(['list_servers', 'get_server', 'list_zones', 'get_zone', 'list_rrsets']);
  expect(schema.$defs.ListServers.properties.max_results.maximum).toBe(200);
  expect(schema.$defs.GetZone.required).toContain('zone_id');
  expect(schema.$defs.GetZone.properties.zone_id['x-dynamic-options'].allow_custom).toBe(true);
  expect(schema.$defs.GetZone.properties.include_record_count.default).toBe(false);
  const key = schema.$defs.PowerDNSCredential;
  expect(key.required).toEqual(['api_origin', 'api_key']);
  expect(key.properties.api_key['ui:widget']).toBe('password');
  expect(key.properties.server_id.default).toBe('localhost');
  expect(key.properties.refresh_token).toBeUndefined();
  expect(key.properties.password).toBeUndefined();
});
it('actual credential cache selects owned key and excludes display-only descriptor', () => {
  upsertCredentialsIntoCache([
    { id: 'powerdns-display', name: 'Descriptor', credential_type: 'powerdns_api_key', owned_by_me: false },
    { id: 'powerdns-owned', name: 'Owned', credential_type: 'powerdns_api_key', owned_by_me: true },
  ] as any);
  expect(autoSelectCredentialFromCache(TYPE)).toEqual({ powerdns_api_key: 'powerdns-owned' });
});
it('initializes actual icon registry with the unchanged official PNG', () => {
  const bytes = readFileSync(resolve(process.cwd(), 'public/icons/powerdns.png'));
  expect(bytes.length).toBe(821);
  expect(createHash('sha256').update(bytes).digest('hex')).toBe('d237ad97c32e430e36f9ad2c6e307206aab96d275bfca18ce63ab78f8d565635');
  expect(bytes.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
  setNodeIconData({ [TYPE]: { type: TYPE, label: PowerDNSNode.label, description: PowerDNSNode.description, iconColor: '', iconHtml: renderToStaticMarkup(<PowerDNSNode.Icon />), dimensions: PowerDNSNode.dimensions!, credentialKeys: ['powerdns_api_key'] } });
  const icon = getCredentialIcon('powerdns_api_key');
  expect(icon.hasServiceIcon).toBe(true);
  expect(render(<icon.Icon />).container.querySelector('img')?.getAttribute('src')).toBe('/icons/powerdns-brand-vector.svg');
  expect(humanizeCredentialLabel('PowerDNS')).toBe('Power DNS');
});
it('actual mounted cap saves an integer through update/export/hydration', async () => {
  const { container } = render(<Panel />);
  fireEvent.change(container.querySelector('[data-field-key="max_results"] input')!, { target: { value: '2' } });
  await waitFor(() => expect(JSON.parse(screen.getByTestId('saved').textContent!)).toMatchObject({ max_results: 2 }));
  expect(JSON.parse(screen.getByTestId('exported').textContent!)).toMatchObject({ max_results: 2 });
  fireEvent.click(screen.getByText('Hydrate'));
  expect(JSON.parse(screen.getByTestId('saved').textContent!)).toMatchObject({ max_results: 2 });
});
it('internal exact zone locator and false count survive actual save/export/reopen', () => {
  render(<Panel initial={{ operation: 'get_zone', zone_id: 'example.test.', include_names: false, include_record_count: false }} />);
  const saved = JSON.parse(screen.getByTestId('saved').textContent!);
  expect(saved).toMatchObject({ zone_id: 'example.test.', include_names: false, include_record_count: false });
  expect(JSON.parse(screen.getByTestId('exported').textContent!)).toEqual(saved);
  fireEvent.click(screen.getByText('Hydrate'));
  expect(JSON.parse(screen.getByTestId('saved').textContent!)).toEqual(saved);
});
it('visible credential form has masked key and distinct HTTPS origin/resource label', async () => {
  const schema = NODE_SCHEMAS[TYPE].$defs.PowerDNSCredential;
  const fields = Object.entries(schema.properties).filter(([, property]: any) => !property['ui:hidden']).map(([name, property]: any) => ({ name, label: property.title ?? name, type: property['ui:widget'] === 'password' ? 'password' : 'text', required: (schema.required ?? []).includes(name) }));
  const save = vi.fn(async (_name: string, _data: Record<string, string>) => null);
  const { container } = render(<CredentialCreatePanel app="PowerDNS" saveLabel="Create" initialValues={{ server_id: 'localhost' }} fields={fields} onSave={save} />);
  for (const [key, value] of Object.entries({ api_origin: 'https://dns.example.com:8443', api_key: 'synthetic-issued-key', server_id: 'localhost' })) {
    fireEvent.change(container.querySelector('[data-field="' + key + '"] input')!, { target: { value } });
  }
  expect(container.querySelector<HTMLInputElement>('[data-field="api_key"] input')?.type).toBe('password');
  expect(container.querySelector<HTMLInputElement>('[data-field="api_origin"] input')?.type).toBe('text');
  expect(container.querySelector('[data-field="credential_type"]')).toBeNull();
  fireEvent.click(screen.getByText('Create'));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][1]).toEqual({ api_origin: 'https://dns.example.com:8443', api_key: 'synthetic-issued-key', server_id: 'localhost' });
});
