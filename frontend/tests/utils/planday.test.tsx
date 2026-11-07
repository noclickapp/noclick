// @vitest-environment jsdom
// Native catalog and masked credential form fixtures.
import React from 'react';
import { createHash } from 'node:crypto';
import { renderToStaticMarkup } from 'react-dom/server';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
import { PlandayNode } from '~/components/workflow/nodes/integrations/planday';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import vendorSvg from '../../public/icons/planday.svg?raw';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn(async () => ({ success: true, valid: true, errors: [], options: [] })) }));
vi.mock('~/lib/analytics', () => ({ useAnalytics: () => ({ track: vi.fn(), logActivity: vi.fn() }) }));
vi.mock('~/hooks/useAgentCredentialsRequired', () => ({ useAgentCredentialsRequired: () => [] }));
const TYPE = 'automation-planday';
beforeAll(() => loadNodeSchemas([TYPE]));
afterEach(() => cleanup());

it('registers exactly ten read operations and the supplied token family', () => {
  expect(AVAILABLE_NODES.some(node => node.type === TYPE)).toBe(true);
  expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual(['planday_access_token']);
  const schema = NODE_SCHEMAS[TYPE];
  const operations = schema.properties.config.oneOf.map((ref: any) => schema.$defs[ref.$ref.split('/').pop()].properties.operation.const);
  expect(operations).toEqual(['get_portal_info', 'list_departments', 'get_department', 'list_employee_groups', 'get_employee_group', 'list_employees', 'get_employee', 'list_department_employees', 'list_shifts', 'get_shift']);
  expect(schema.$defs.ListEmployees.properties.limit.maximum).toBe(50);
  expect(schema.$defs.ListEmployees.properties.offset.maximum).toBe(2147483647);
  expect(schema.$defs.GetEmployee.properties.employee_id['x-dynamic-options']).toBe(true);
  expect(schema.$defs.PlandayAccessTokenCredential.required).toEqual(['client_id', 'access_token']);
  expect(schema.$defs.PlandayAccessTokenCredential.properties.access_token['ui:widget']).toBe('password');
  expect(schema.$defs.PlandayAccessTokenCredential.properties.refresh_token).toBeUndefined();
});

it('uses the official navigation symbol in the initialized real icon registry', () => {
  expect(vendorSvg).toContain('width="24" height="24"');
  expect(createHash('sha256').update(vendorSvg).digest('hex')).toBe('34f6bcb496e6b2bd8a6251844986dc8c10fb75bb43f6cb834aabaaaad99113e7');
  setNodeIconData({ [TYPE]: { type: TYPE, label: PlandayNode.label, description: PlandayNode.description, iconColor: '', credentialKeys: ['planday_access_token'], iconHtml: renderToStaticMarkup(<PlandayNode.Icon />), dimensions: PlandayNode.dimensions! } });
  const icon = getCredentialIcon('planday_access_token');
  expect(icon.hasServiceIcon).toBe(true);
  const { container } = render(<icon.Icon />);
  expect(container.querySelector('img')?.getAttribute('src')).toBe('/icons/planday.svg');
  expect(humanizeCredentialLabel('PlandayAccessToken')).toBe('Planday Access Token');
});

it('actual visible credential form masks both headers and preserves an exact portal witness string', async () => {
  const schema = NODE_SCHEMAS[TYPE].$defs.PlandayAccessTokenCredential;
  const fields = Object.entries(schema.properties).filter(([, property]: any) => !property['ui:hidden']).map(([name, property]: any) => ({ name, label: property.title ?? name, type: property['ui:widget'] === 'password' ? 'password' : 'text', required: (schema.required ?? []).includes(name) }));
  const save = vi.fn(async (_name: string, _data: Record<string, string>) => null);
  const { container } = render(<CredentialCreatePanel app="Planday" fields={fields} onSave={save} />);
  fireEvent.click(screen.getByText('More options'));
  for (const [key, value] of Object.entries({ client_id: 'synthetic-client', access_token: 'synthetic-access', expected_portal_id: '7' })) {
    fireEvent.change(container.querySelector(`[data-field="${key}"] input`)!, { target: { value } });
  }
  expect(container.querySelector<HTMLInputElement>('[data-field="access_token"] input')?.type).toBe('password');
  expect(container.querySelector<HTMLInputElement>('[data-field="client_id"] input')?.type).toBe('password');
  expect(container.querySelector('[data-field="credential_type"]')).toBeNull();
  expect(container.querySelector('[data-field="refresh_token"]')).toBeNull();
  fireEvent.click(screen.getByText('Connect'));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][1]).toEqual({ client_id: 'synthetic-client', access_token: 'synthetic-access', expected_portal_id: '7' });
});
