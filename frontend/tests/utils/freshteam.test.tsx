// @vitest-environment jsdom
// Preserve the Freshteam credential, cache and icon contracts after moving its definition.
// Exercise the schema consumers used by staging rather than the original shared UI changes.
import React from 'react';
import { createHash } from 'node:crypto';
import { renderToStaticMarkup } from 'react-dom/server';
import { cleanup, render } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { FreshteamNode } from '~/components/workflow/nodes/integrations/freshteam';
import { AVAILABLE_NODES } from '~/components/workflow/nodes/nodeRegistry';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { getCredentialIcon } from '~/utils/credentialIcons';
import { setNodeIconData } from '~/lib/nodeIconRegistry';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import vendorSvg from '../../public/icons/freshteam.svg?raw';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
const TYPE = 'automation-freshteam';
await loadNodeSchemas([TYPE]);
afterEach(() => { cleanup(); removeCredentialsFromCache(['ft-own', 'ft-display']); });

it('registers genuine native credential and closed operation schemas with job parents', () => {
    expect(AVAILABLE_NODES.some(node => node.type === TYPE)).toBe(true);
    expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual(['freshteam']);
    const schema = NODE_SCHEMAS[TYPE];
    const operations = schema.properties.config.oneOf.map((ref: any) => schema.$defs[ref.$ref.split('/').pop()].properties.operation.const);
    expect(operations).toHaveLength(20);
    expect(operations).toContain('update_applicant_text_field');
    expect(operations).not.toContain('send_invitation');
    expect(operations).not.toContain('terminate_employee');
    expect(operations).not.toContain('create_note');
    expect(schema.$defs.GetApplicant.properties.applicant_id).toMatchObject({ 'x-dynamic-options': { field_name: 'applicant_id', depends_on: 'job_id', allow_custom: true } });
    expect(humanizeCredentialLabel(schema.$defs.FreshteamCredential.title)).toBe('Freshteam');
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'freshteam', method_kind: 'api_key', is_oauth: false });
});

it('selects an owned Freshteam key through the actual cache', () => {
    upsertCredentialsIntoCache([{ id: 'ft-display', name: 'Descriptor', credential_type: 'freshteam', owned_by_me: false }, { id: 'ft-own', name: 'Own key', credential_type: 'freshteam', owned_by_me: true }] as any);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({ freshteam: 'ft-own' });
});

it('initializes the actual icon registry with exact official Freshteam mark', () => {
    expect(createHash('sha256').update(vendorSvg).digest('hex')).toBe('aaa3064b4eb4aa7da8c9809a11e08f1575c21e6ea2970ea401cbf4100c163fb6');
    setNodeIconData({ [TYPE]: { type: TYPE, label: FreshteamNode.label, description: FreshteamNode.description, iconColor: '', credentialKeys: ['freshteam'], iconHtml: renderToStaticMarkup(<FreshteamNode.Icon />), dimensions: FreshteamNode.dimensions! } });
    const icon = getCredentialIcon('freshteam');
    expect(icon.hasServiceIcon).toBe(true);
    const { container } = render(<icon.Icon />);
    expect(container.querySelector('img')?.getAttribute('src')).toBe('/icons/freshteam.svg');
});
