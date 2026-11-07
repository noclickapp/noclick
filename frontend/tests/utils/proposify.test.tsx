// Proposify schema/cache and native light/dark icon fixtures.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ProposifyIcon } from '~/components/workflow/nodes/integrations/proposify';
import { NODE_SCHEMAS, getNodeCredentialInfo, isAgentToolProviderType, loadNodeSchemas } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
const TYPE = 'automation-proposify', FAMILY = 'proposify_issued_token';
await loadNodeSchemas([TYPE]);
describe('native Proposify', () => {
  it('keeps actual issued family separate from invented OAuth setup', () => {
    expect(getNodeCredentialInfo(TYPE)?.acceptedTypes).toEqual([FAMILY]);
    expect(getCredentialTypeFromSchemaTitle('ProposifyIssuedTokenCredential')).toBe(FAMILY);
    expect(getCredentialTypeFromSchemaTitle('Proposify Issued OAuth Token')).toBe(FAMILY);
    const schema = NODE_SCHEMAS[TYPE];
    expect(schema.$defs.ProposifyIssuedTokenCredential['x-oauth-provider']).toBeUndefined();
    expect(isAgentToolProviderType(TYPE)).toBe(true);
    const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
    expect(ops).toHaveLength(9);
    expect(ops).toContain('create_draft_document_from_template');
    expect(ops).not.toContain('send_document');
    expect(schema.$defs.ProposifyUsersConfig.properties.include_personal_details.default).toBe(false);
    expect(schema.$defs.ProposifyCreateDraftConfig.required).toContain('template_id');
    expect(schema.$defs.ProposifyCreateDraftConfig.properties.template_id['x-dynamic-options'].auto_select_sole_option).toBe(false);
  });
  it('selects via the actual native provider import and removes cached selection', () => {
    upsertCredentialsIntoCache([{ id: 'proposify-fixture', name: 'Issued fixture', credential_type: FAMILY, owned_by_me: true }]);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({ [FAMILY]: 'proposify-fixture' });
    removeCredentialsFromCache(['proposify-fixture']);
    expect(autoSelectCredentialFromCache(TYPE)).toEqual({});
  });
  it('uses exact theme assets with shared disabled filter and contain sizing', () => {
    const filter = 'grayscale(100%) brightness(0.4) drop-shadow(0 0 3px black)';
    const html = renderToStaticMarkup(<ProposifyIcon style={{ width: 48, height: 48, filter }} />);
    expect(html).toContain('/icons/proposify.svg');
    expect(html).toContain('/icons/proposify-dark.svg');
    expect(html).toContain('dark:hidden');
    expect(html).toContain('dark:block');
    expect(html).toContain('object-fit:contain');
    expect(html).toContain(`filter:${filter}`);
  });
});
