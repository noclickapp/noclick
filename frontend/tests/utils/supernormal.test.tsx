// UNRUN Supernormal native schema/cache, privacy defaults and actual icon renderer fixtures.
// Generated schema assertions run only after a separately granted native generation.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, it } from 'vitest';
import { SupernormalIcon } from '~/components/icons/SupernormalIcon';
import { NODE_SCHEMAS, loadNodeSchemas, getNodeCredentialInfo, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

describe('native Supernormal wiring', () => {
  beforeAll(() => loadNodeSchemas(['automation-supernormal']));
  it('exposes the real scoped token family and only five meeting-service reads', () => {
    const schema = NODE_SCHEMAS['automation-supernormal'];
    expect(schema.$defs.SupernormalAPITokenCredential.properties.credential_type.const).toBe('supernormal_api_key');
    expect(getNodeCredentialInfo('automation-supernormal')?.acceptedTypes).toEqual(['supernormal_api_key']);
    expect(getCredentialTypeFromSchemaTitle('Supernormal API Token')).toBe('supernormal_api_key');
    expect(getCredentialTypeFromSchemaTitle('SupernormalAPITokenCredential')).toBe('supernormal_api_key');
    expect(isAgentToolProviderType('automation-supernormal')).toBe(true);
    const ops = schema.properties.config.oneOf.map((r: { $ref: string }) => schema.$defs[r.$ref.split('/').at(-1)!].properties.operation.const);
    expect(ops).toEqual(['get_user', 'list_upcoming_calendar_events', 'list_recordings', 'get_recording', 'get_transcript']);
    expect(ops).not.toContain('update_task');
    expect(ops).not.toContain('toggle_capture');
  });

  it('selects and removes an owned credential through the actual native mapping', () => {
    const id = 'supernormal-owned-fixture';
    upsertCredentialsIntoCache([{ id, name: 'Owned token fixture', credential_type: 'supernormal_api_key', owned_by_me: true }]);
    expect(autoSelectCredentialFromCache('automation-supernormal')).toEqual({ supernormal_api_key: id });
    removeCredentialsFromCache([id]);
    expect(autoSelectCredentialFromCache('automation-supernormal')).toEqual({});
  });

  it('retains explicit scope/parent/privacy defaults and no invented page size', () => {
    const defs = NODE_SCHEMAS['automation-supernormal'].$defs;
    expect(defs.SupernormalAPITokenCredential.required).toEqual(expect.arrayContaining(['api_token', 'scopes']));
    expect(defs.SupernormalAPITokenCredential.properties.api_token['ui:widget']).toBe('password');
    expect(defs.SupernormalAPITokenCredential['x-oauth-provider']).toBeUndefined();
    expect(defs.SupernormalTranscriptConfig.properties.recording_id['x-dynamic-options'].depends_on).toBe('visibility');
    expect(defs.SupernormalTranscriptConfig.properties.recording_id['x-dynamic-options'].auto_select_sole_option).toBe(false);
    expect(defs.SupernormalTranscriptConfig.properties.include_text.default).toBe(false);
    expect(defs.SupernormalTranscriptConfig.properties.include_speaker_names.default).toBe(false);
    expect(defs.SupernormalRecordingsConfig.properties.include_meeting_text.default).toBe(false);
    expect(defs.SupernormalRecordingsConfig.properties.per_page).toBeUndefined();
  });

  it('shows the exact dark artwork in light mode and its white copy in dark, under the real canvas filter', () => {
    const filter = 'drop-shadow(0 0 3px black)';
    const html = renderToStaticMarkup(<SupernormalIcon style={{ width: 48, height: 48, filter }} />);
    const [light, dark, ...more] = html.match(/<img[^>]*>/g) ?? [];
    expect(more).toEqual([]);
    expect(light).toContain('src="/icons/supernormal.svg"');
    expect(light).toContain('class="dark:hidden"');
    expect(dark).toContain('src="/icons/supernormal-dark.svg"');
    expect(dark).toContain('class="hidden dark:block"');
    for (const img of [light, dark]) {
      expect(img).toContain('object-fit:contain');
      expect(img).toContain(`filter:${filter}`);
    }
    const disabled = renderToStaticMarkup(<SupernormalIcon style={{ filter: 'grayscale(100%) brightness(0.4) drop-shadow(0 0 3px black)' }} />);
    expect(disabled).toContain('filter:grayscale(100%) brightness(0.4)');
    expect(disabled).not.toContain('invert(');
  });
});
