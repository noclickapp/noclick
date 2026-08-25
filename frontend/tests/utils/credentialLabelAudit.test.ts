// Enforcement seam for credential display names: every credential class title
// in the generated node schemas is run through the humanizer and compared to
// the committed snapshot. Adding a node with a NEW credential class fails
// this test until the humanized name is reviewed — that's the moment to catch
// a compound brand the camel-splitter would break ("WordPress" → "Word Press")
// and add it to COMPOUND_BRANDS in ~/utils/credentialLabels.ts (or, better,
// give the Pydantic class a human title at the source — schema titles win).
// Bless a correct new name by re-running with: npx vitest run -u tests/utils/credentialLabelAudit.test.ts
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it, expect } from 'vitest';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';

const SCHEMAS_DIR = join(__dirname, '../../app/schemas/nodes');

function collectCredentialTitles(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const file of readdirSync(SCHEMAS_DIR).filter(f => f.endsWith('.json'))) {
    const schema = JSON.parse(readFileSync(join(SCHEMAS_DIR, file), 'utf8'));
    for (const [name, def] of Object.entries<Record<string, unknown>>(schema.$defs ?? {})) {
      const props = (def as { properties?: Record<string, unknown> }).properties;
      if (!props || !('credential_type' in props)) continue;
      const title = ((def as { title?: string }).title || name).replace('Credential', '');
      out[title] = humanizeCredentialLabel(title);
    }
  }
  return out;
}

describe('credential label audit', () => {
  it('every schema credential title humanizes to a reviewed name', async () => {
    const lines = Object.entries(collectCredentialTitles())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([raw, human]) => `${raw} -> ${human}`)
      .join('\n');
    await expect(lines).toMatchFileSnapshot('./__snapshots__/credential-labels.snap.txt');
  });
});
