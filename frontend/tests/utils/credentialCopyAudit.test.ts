// Every way in, as the connect dialog words it, derived from the node schemas alone: its name, its one line, the
// steps to get the value and the host it comes from, then each field's label and help. A new credential class (or a
// changed description) fails this until the wording is reviewed; fix a bad line in the schema (an
// x-credential-instructions, a field's ui:help) or in ~/utils/credentialCopy.ts, never by hand here.
// Bless a reviewed change with: npx vitest run -u tests/utils/credentialCopyAudit.test.ts
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { copyMethodOf, fieldHelp, fieldLabel, methodCopy } from '~/utils/credentialCopy';
import { fixWordCasing } from '~/utils/credentialLabels';

const SCHEMAS_DIR = join(__dirname, '../../app/schemas/nodes');

function audit(): string {
    const seen = new Set<string>();
    const blocks: string[] = [];
    // An agent's model key and an MCP server connect in their own forms, never this one.
    const custom = new Set(['agent.json', 'mcp-server.json']);
    for (const file of readdirSync(SCHEMAS_DIR).filter((f) => f.endsWith('.json') && !custom.has(f)).sort()) {
        const schema = JSON.parse(readFileSync(join(SCHEMAS_DIR, file), 'utf8'));
        // The schema's title stands in for the app's catalog name, which only the node registry knows.
        const app = fixWordCasing(
            String(schema.title ?? file)
                .replace(/\s*Node Configuration$/i, '')
                .replace(/\s*Configuration$/i, '')
                .split(/[-\s]+/)
                .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                .join(' ')
        );
        for (const req of requirementsFromSchema(schema)) {
            if (seen.has(req.credential_type)) continue;
            seen.add(req.credential_type);
            const method = copyMethodOf(methodFromRequirement(req));
            const copy = methodCopy(method, app);
            const lines = [`## ${req.credential_type} (${app})`, `name: ${copy.name}`, `line: ${copy.line}`];
            if (copy.howTo) lines.push(`how: ${copy.howTo}`);
            if (copy.source) lines.push(`from: ${copy.source.host}`);
            for (const field of method.fields ?? []) {
                const help = fieldHelp(field, app, copy.howTo);
                lines.push(`  ${fieldLabel(field)}${field.required ? '' : ' (optional)'}${help ? ` — ${help}` : ''}`);
            }
            blocks.push(lines.join('\n'));
        }
    }
    return `${blocks.join('\n\n')}\n`;
}

describe('credential copy audit', () => {
    it('every way in reads as reviewed', async () => {
        await expect(audit()).toMatchFileSnapshot('./__snapshots__/credential-copy.snap.txt');
    });
});
