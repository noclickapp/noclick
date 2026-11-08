// @vitest-environment jsdom
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { CredentialCreatePanel } from '~/components/credential/CredentialCreatePanel';
import { ChurchToolsNode } from '~/components/workflow/nodes/integrations/churchtools';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import schema from '~/schemas/nodes/churchtools.json';

vi.mock('~/lib/analytics', () => ({ useAnalytics: () => ({ track: vi.fn(), logActivity: vi.fn() }) }));
afterEach(cleanup);

it('discovers ChurchTools with its literal Login-token credential and 27 native operations', async () => {
    await loadNodeSchemas(['automation-churchtools']);
    expect(AVAILABLE_NODES.some(node => node.type === 'automation-churchtools')).toBe(true);
    expect(getNodeCredentialInfo('automation-churchtools')?.acceptedTypes).toEqual(['churchtools']);
    const defs = schema.$defs as Record<string, any>;
    const operations = schema.properties.config.oneOf.map(ref => defs[ref.$ref.split('/').pop()!].properties.operation.const);
    expect(operations).toHaveLength(27);
    expect(operations).toContain('update_calendar');
    expect(operations).not.toContain('send_invitation');
    expect(defs.ChurchToolsCredential.properties.credential_type.const).toBe('churchtools');
    expect(defs.GetWikiPage.properties.page_guid['x-dynamic-options']).toMatchObject({ field_name: 'page_guid', depends_on: 'wiki_category_id', allow_custom: true });
});

it('uses the sourced brand vector in the discovered definition', () => {
    expect(renderToStaticMarkup(<ChurchToolsNode.Icon />)).toContain('/icons/churchtools-brand-vector.svg');
});

it('masks the Login token and submits the installation and exact person ID', async () => {
    const credential = schema.$defs.ChurchToolsCredential;
    const fields = Object.entries(credential.properties).filter(([, property]) => !(property as any)['ui:hidden']).map(([name, property]) => ({ name, label: property.title ?? name, type: (property as any)['ui:widget'] === 'password' ? 'password' : 'text', required: (credential.required as string[]).includes(name) }));
    const save = vi.fn(async (_name: string, _data: Record<string, string>) => null);
    const { container, getByText } = render(<CredentialCreatePanel app="ChurchTools" fields={fields} onSave={save} />);
    const values = { instance_url: 'https://fixture.church.tools', login_token: 'synthetic-token-private', expected_person_id: '7' };
    for (const [name, value] of Object.entries(values)) {
        fireEvent.change(container.querySelector(`[data-field="${name}"] input`)!, { target: { value } });
    }
    expect(container.querySelector<HTMLInputElement>('[data-field="login_token"] input')?.type).toBe('password');
    fireEvent.click(getByText('Connect'));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save.mock.calls[0][1]).toEqual(values);
});
