// Enforcement seam for credential display names: every credential class title
// in the generated node schemas is run through the humanizer and compared to
// the committed snapshot. Adding a node with a NEW credential class fails
// this test until the humanized name is reviewed — that's the moment to catch
// a compound brand the camel-splitter would break ("WordPress" → "Word Press")
// and add it to COMPOUND_BRANDS in ~/utils/credentialLabels.ts (or, better,
// give the Pydantic class a human title at the source — schema titles win).
// Bless a correct new name by re-running with: npx vitest run -u tests/utils/credentialLabelAudit.test.ts
import { expectCredentialSnapshots } from './credentialAuditSnapshots';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it, expect } from 'vitest';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

const legacyTypes = new Set(Object.keys(JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodeMeta.json'), 'utf8')).types).map(type => type.replace(/^automation-/, '') + '.json'));
const SCHEMAS_DIR = join(__dirname, '../../app/schemas/nodes');

function collectCredentialTitles(legacy: boolean): Record<string, { raw: string; human: string; credentialType: string; slug: string }> {
  const out: Record<string, { raw: string; human: string; credentialType: string; slug: string }> = {};
  for (const file of readdirSync(SCHEMAS_DIR).filter(f => f.endsWith('.json') && legacyTypes.has(f) === legacy).sort()) {
    const schema = JSON.parse(readFileSync(join(SCHEMAS_DIR, file), 'utf8'));
    for (const [name, def] of Object.entries<Record<string, unknown>>(schema.$defs ?? {})) {
      const props = (def as { properties?: Record<string, unknown> }).properties;
      if (!props || !('credential_type' in props)) continue;
      const title = ((def as { title?: string }).title || name).replace('Credential', '');
      const credential = (props.credential_type as { const?: string; default?: string });
      const credentialType = credential.const ?? credential.default ?? '';
      if (!credentialType && !legacy) throw new Error(`Credential type missing in ${file}: ${name}`);
      out[legacy ? title : `${file}:${title}`] = { raw: title, human: humanizeCredentialLabel(title), credentialType, slug: file.slice(0, -5) };
    }
  }
  return out;
}

describe('credential label audit', () => {
  it('every schema credential title humanizes to a reviewed name', async () => {
    const lines = Object.entries(collectCredentialTitles(true))
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([raw, human]) => `${raw} -> ${human.human}`)
      .join('\n');
    await expect(lines).toMatchFileSnapshot('./__snapshots__/credential-labels.snap.txt');
    const legacy = collectCredentialTitles(true);
    const perCredential = new Map<string, string[]>();
    for (const [, entry] of Object.entries(collectCredentialTitles(false)).sort(([a], [b]) => a.localeCompare(b))) {
      if (entry.raw in legacy) continue;
      const path = `./__snapshots__/credentials/${entry.slug}/${entry.credentialType}.labels.snap.txt`;
      perCredential.set(path, [...(perCredential.get(path) ?? []), `${entry.raw} -> ${entry.human}`]);
    }
    await expectCredentialSnapshots('labels', new Map([...perCredential].map(([path, entries]) => [path, entries.join('\n')])));
  });
});
