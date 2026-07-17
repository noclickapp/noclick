// Pins the nodeSchemas <-> credentialTypes import cycle shut.
//
// The two modules used to import each other (nodeSchemas needed the
// schema-title lookup, credentialTypes needed getNodeCredentialInfo). A mutual
// import isn't a type error and typecheck stays green, so the only symptom was
// Vite SSR 500ing with "dependency module is not yet fully initialized" —
// and only once some *unrelated* third module added an edge that changed
// evaluation order. It regressed twice that way before the map moved into this
// leaf, each time costing a long hunt for a fault that looked nothing like an
// import cycle.
//
// These are source-level assertions on purpose: importing the modules here
// wouldn't reproduce the failure, because Vitest resolves cycles happily. The
// scan is what actually catches it.

import { readFileSync } from 'fs';
import { join } from 'path';
import { describe, expect, it } from 'vitest';

import { CREDENTIAL_TYPE_MAP, getCredentialTypeFromSchemaTitle } from './credentialTypeMap';

const UTILS = join(process.cwd(), 'app', 'utils');
const read = (file: string) => readFileSync(join(UTILS, file), 'utf-8');

/** Static `import ... from '<spec>'` specifiers only — ignores comments and
 *  dynamic import(), which can't create an evaluation-order cycle. */
function staticImportSpecifiers(source: string): string[] {
    const withoutBlockComments = source.replace(/\/\*[\s\S]*?\*\//g, '');
    const withoutLineComments = withoutBlockComments.replace(/^\s*\/\/.*$/gm, '');
    return [...withoutLineComments.matchAll(/^\s*import\s[^;]*?from\s+['"]([^'"]+)['"]/gm)].map(
        (m) => m[1]
    );
}

describe('credentialTypeMap leaf', () => {
    it('imports nothing — a leaf cannot participate in a cycle', () => {
        expect(staticImportSpecifiers(read('credentialTypeMap.ts'))).toEqual([]);
    });

    it('nodeSchemas does not import credentialTypes', () => {
        const specs = staticImportSpecifiers(read('nodeSchemas.ts'));
        expect(specs.filter((s) => s.includes('credentialTypes'))).toEqual([]);
    });

    it('credentialTypes may import nodeSchemas only because nodeSchemas points at the leaf', () => {
        // This direction is fine on its own; it is only half of a cycle. The
        // assertion above is what keeps the other half from coming back.
        const specs = staticImportSpecifiers(read('credentialTypes.ts'));
        expect(specs).toContain('./credentialTypeMap');
    });

    it('still resolves titles, and keeps the whole map reachable from credentialTypes', async () => {
        // A move that silently dropped entries would typecheck and pass a
        // shallow smoke test, so assert the re-export is the same object.
        expect(getCredentialTypeFromSchemaTitle('GoogleSheetsOAuthCredential')).toBe(
            'google_sheets_oauth'
        );
        // Unmapped titles fall back to a lowercased title — preserved behaviour.
        expect(getCredentialTypeFromSchemaTitle('TotallyUnknownCredential')).toBe(
            'totallyunknowncredential'
        );
        const reExported = await import('./credentialTypes');
        expect(reExported.CREDENTIAL_TYPE_MAP).toBe(CREDENTIAL_TYPE_MAP);
        expect(Object.keys(CREDENTIAL_TYPE_MAP).length).toBeGreaterThan(150);
    });
});
