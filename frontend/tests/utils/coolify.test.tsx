// @vitest-environment jsdom
import React from 'react';
import { createHash } from 'node:crypto';
import { renderToStaticMarkup } from 'react-dom/server';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
import { CoolifyNode } from '~/components/workflow/nodes/integrations/coolify';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import vendorSvg from '../../public/icons/coolify.svg?raw';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ success: true, valid: true, errors: [], options: [] })) }));
vi.mock('~/lib/analytics', () => ({ useAnalytics: () => ({ track: vi.fn(), logActivity: vi.fn() }) }));
vi.mock('~/hooks/useAgentCredentialsRequired', () => ({ useAgentCredentialsRequired: () => ({ credentialsRequired: false, allowUsageBased: false, provider: null }) }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
const TYPE = 'automation-coolify';
beforeAll(() => loadNodeSchemas([TYPE]));
afterEach(cleanup);

it('registers sixteen closed native operations, literal credential and project-scoped environment picker', () => {
  expect(AVAILABLE_NODES.some(node => node.type === TYPE)).toBe(true);
  expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual(['coolify_token']);
  const schema = NODE_SCHEMAS[TYPE];
  const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
  expect(method.method_kind).toBe('api_key');
  expect(method.is_oauth).toBe(false);
  const operations = schema.properties.config.oneOf.map((ref: any) => schema.$defs[ref.$ref.split('/').pop()].properties.operation.const);
  expect(operations).toHaveLength(16);
  expect(operations).toEqual(expect.arrayContaining(['create_project', 'update_environment', 'get_deployment', 'list_services']));
  for (const absent of ['delete_project', 'delete_environment', 'deploy', 'start', 'stop', 'cancel_deployment', 'get_logs', 'get_envs']) expect(operations).not.toContain(absent);
  expect(schema.$defs.GetEnvironment.properties.environment_uuid['x-dynamic-options']).toMatchObject({ field_name: 'environment_uuid', depends_on: 'project_uuid', allow_custom: true });
});

it('initializes real credential icon registry from exact official vector bytes', () => {
  expect(createHash('sha256').update(vendorSvg).digest('hex')).toBe('0b6df9fbb7dd046ce8c15ac7052e152ccc6bacb030e46c61c3139e929d746090');
  setNodeIconData({ [TYPE]: { type: TYPE, credentialKeys: ['coolify_token'], label: CoolifyNode.label, description: CoolifyNode.description, iconColor: '', iconHtml: renderToStaticMarkup(<CoolifyNode.Icon />), dimensions: CoolifyNode.dimensions! } });
  const icon = getCredentialIcon('coolify_token');
  expect(icon.hasServiceIcon).toBe(true);
  const { container } = render(<icon.Icon />);
  expect(container.querySelector('img')?.getAttribute('src')).toBe('/icons/coolify.svg');
  expect(humanizeCredentialLabel('Coolify Token')).toBe('Coolify Token');
});

it('actual visible-only credential panel masks full ID|secret token and sends typed form inputs', async () => {
  const schema = NODE_SCHEMAS[TYPE].$defs.CoolifyTokenCredential;
  const fields = Object.entries(schema.properties).filter(([, property]: any) => !property['ui:hidden']).map(([name, property]: any) => ({ name, label: property.title ?? name, type: property['ui:widget'] === 'password' ? 'password' : 'text', required: (schema.required ?? []).includes(name) }));
  const save = vi.fn(async (_name: string, _data: Record<string, string>) => null);
  const { container } = render(<CredentialCreatePanel app="Coolify" saveLabel="Create" initialValues={{ api_url: 'https://coolify.fixture.com' }} fields={fields} onSave={save} />);
  const visible = { api_url: 'https://coolify.fixture.com', expected_team_id: '7', api_token: '12|syntheticPrivateToken0123456789' };
  for (const [name, value] of Object.entries(visible)) fireEvent.change(container.querySelector(`[data-field="${name}"] input`)!, { target: { value } });
  expect(container.querySelector<HTMLInputElement>('[data-field="api_token"] input')?.type).toBe('password');
  fireEvent.click(screen.getByText('Create'));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][1]).toEqual(visible);
  expect(Object.hasOwn(save.mock.calls[0][1], 'credential_type')).toBe(false);
});
