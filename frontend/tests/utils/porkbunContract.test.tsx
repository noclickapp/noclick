// @vitest-environment happy-dom
// UNRUN actual native controls, save/export/hydration, credential form and cache.
import React, { useState } from 'react';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { NodeConfig } from '~/components/workflow/NodeConfig';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
import { PorkbunNode } from '~/components/workflow/nodes/PorkbunNode';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { applyNodeUpdate, buildSaveConfig, createWorkflowNode } from '~/lib/applyNodeUpdate';
import { buildWorkflowExport } from '~/lib/workflowIO';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ success: true, valid: true, errors: [], options: [] })) }));
vi.mock('~/lib/analytics', () => ({ useAnalytics: () => ({ track: vi.fn(), logActivity: vi.fn() }) }));
vi.mock('~/hooks/useAgentCredentialsRequired', () => ({ useAgentCredentialsRequired: () => [] }));
const TYPE = 'automation-porkbun';
beforeAll(async () => { await loadNodeSchemas([TYPE]); });
afterEach(() => { cleanup(); removeCredentialsFromCache(['porkbun-display', 'porkbun-owned']); });

function Panel({ initial = {} }: { initial?: Record<string, unknown> }) {
  const [node, setNode] = useState(() => createWorkflowNode('porkbun-panel', TYPE, { x: 0, y: 0 }, { operation: 'list_domains', ...initial }));
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

it('registers exactly four metadata reads and the supplied header-key family', () => {
  expect(AVAILABLE_NODES.some(node => node.type === TYPE)).toBe(true);
  expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual(['porkbun_api_key']);
  const schema = NODE_SCHEMAS[TYPE];
  expect(schema.properties.config.oneOf.map((ref: any) => schema.$defs[ref.$ref.split('/').pop()].properties.operation.const))
    .toEqual(['list_domains', 'get_domain', 'list_dns_records', 'get_dns_record']);
  expect(schema.$defs.ListDomains.properties.max_results.maximum).toBe(100);
  expect(schema.$defs.ListDomains.properties.start.default).toBe(0);
  expect(schema.$defs.GetDNSRecord.required).toEqual(['domain', 'record_id']);
  expect(schema.$defs.GetDNSRecord.properties.record_id.type).toBe('string');
  expect(schema.$defs.GetDNSRecord.properties.record_id['x-dynamic-options'].depends_on).toBe('domain');
  expect(schema.$defs.GetDomain.properties.domain['x-dynamic-options'].allow_custom).toBe(true);
  const credential = schema.$defs.PorkbunCredential;
  expect(credential.required).toEqual(['api_key', 'secret_api_key']);
  for (const field of credential.required) expect(credential.properties[field]['ui:widget']).toBe('password');
  expect(credential.properties.refresh_token).toBeUndefined();
  expect(credential.properties.host).toBeUndefined();
});

it('actual cache selects an owned pair and excludes display-only descriptors', () => {
  upsertCredentialsIntoCache([
    { id: 'porkbun-display', name: 'Descriptor', credential_type: 'porkbun_api_key', owned_by_me: false },
    { id: 'porkbun-owned', name: 'Owned', credential_type: 'porkbun_api_key', owned_by_me: true },
  ] as any);
  expect(autoSelectCredentialFromCache(TYPE)).toEqual({ porkbun_api_key: 'porkbun-owned' });
});

it('initializes the real icon registry with exact original official PNG bytes', () => {
  const bytes = readFileSync(resolve(process.cwd(), 'public/icons/porkbun.png'));
  expect(bytes.length).toBe(2604);
  expect(createHash('sha256').update(bytes).digest('hex')).toBe('1fc2ad79a30861fe490d7ebe914aafd61299758f647390ce138c1847599052f6');
  expect([...bytes.subarray(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
  setNodeIconData({ [TYPE]: { type: TYPE, label: PorkbunNode.label, description: PorkbunNode.description, credentialKeys: ['porkbun_api_key'], iconColor: '', iconHtml: renderToStaticMarkup(<PorkbunNode.Icon />), dimensions: PorkbunNode.dimensions! } });
  const icon = getCredentialIcon('porkbun_api_key');
  expect(icon.hasServiceIcon).toBe(true);
  expect(render(<icon.Icon />).container.querySelector('img')?.getAttribute('src')).toBe('/icons/porkbun-brand-vector.svg');
  expect(humanizeCredentialLabel('Porkbun')).toBe('Porkbun');
});

it('mounted native start and local cap save integers through update/export/hydration', async () => {
  const { container } = render(<Panel />);
  for (const [key, value] of Object.entries({ start: '25', max_results: '1' })) {
    fireEvent.change(container.querySelector('[data-field-key="' + key + '"] input')!, { target: { value } });
  }
  await waitFor(() => expect(JSON.parse(screen.getByTestId('saved').textContent!)).toMatchObject({ start: 25, max_results: 1 }));
  expect(JSON.parse(screen.getByTestId('exported').textContent!)).toMatchObject({ start: 25, max_results: 1 });
  fireEvent.click(screen.getByText('Hydrate'));
  expect(JSON.parse(screen.getByTestId('saved').textContent!)).toMatchObject({ start: 25, max_results: 1 });
});

it('exact parent, string record ID and explicit false survive actual save and reopen', () => {
  render(<Panel initial={{ operation: 'get_dns_record', domain: 'example.com', record_id: '123456789', include_names: false }} />);
  const saved = JSON.parse(screen.getByTestId('saved').textContent!);
  expect(saved).toMatchObject({ domain: 'example.com', record_id: '123456789', include_names: false });
  expect(JSON.parse(screen.getByTestId('exported').textContent!)).toEqual(saved);
  fireEvent.click(screen.getByText('Hydrate'));
  expect(JSON.parse(screen.getByTestId('saved').textContent!)).toEqual(saved);
});

it('visible credential form masks both keys and sends only edited visible fields', async () => {
  const schema = NODE_SCHEMAS[TYPE].$defs.PorkbunCredential;
  const fields = Object.entries(schema.properties).filter(([, field]: any) => !field['ui:hidden']).map(([name, field]: any) => ({ name, label: field.title ?? name, type: field['ui:widget'] === 'password' ? 'password' : 'text', required: (schema.required ?? []).includes(name) }));
  const save = vi.fn(async (_name: string, _data: Record<string, string>) => null);
  const { container } = render(<CredentialCreatePanel fields={fields} onSave={save} />);
  for (const [key, value] of Object.entries({ api_key: 'synthetic-public-key', secret_api_key: 'synthetic-secret-key' })) {
    fireEvent.change(container.querySelector('[data-field="' + key + '"] input')!, { target: { value } });
    expect(container.querySelector<HTMLInputElement>('[data-field="' + key + '"] input')?.type).toBe('password');
  }
  expect(container.querySelector('[data-field="credential_type"]')).toBeNull();
  fireEvent.click(screen.getByText('Connect'));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][1]).toEqual({ api_key: 'synthetic-public-key', secret_api_key: 'synthetic-secret-key' });
});
