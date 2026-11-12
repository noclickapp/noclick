import { describe, expect, it } from 'vitest';
import { requirementsFromSchema, wayInRank } from './credentialMethods';

// Two ways into one app, as a node schema declares them: a sign-in still in preview (hidden but for accounts its flag
// lets in, as Canva's is while Canva reviews NoClick's app) and the vendor's MCP server.
const schema = {
    properties: { credentials: { anyOf: [{ $ref: '#/$defs/CanvaOAuthCredential' }, { $ref: '#/$defs/CanvaMcpCredential' }] } },
    $defs: {
        CanvaOAuthCredential: {
            title: 'CanvaOAuthCredential',
            'x-credential-type': 'oauth',
            'x-credential-hidden': true,
            'x-credential-preview-flag': 'canva-oauth-preview',
            properties: { credential_type: { const: 'canva_oauth' } },
        },
        CanvaMcpCredential: {
            title: 'CanvaMcpCredential',
            'x-credential-type': 'mcp',
            properties: { credential_type: { const: 'canva_mcp' } },
        },
    },
};

describe('the order of an app’s ways in', () => {
    it('puts a sign-in still in preview after every other way in', () => {
        const order = requirementsFromSchema(schema, () => true).map((r) => r.credential_type);
        expect(order).toEqual(['canva_mcp', 'canva_oauth']);
    });

    it('keeps a reviewed sign-in first', () => {
        const reviewed = { ...schema, $defs: { ...schema.$defs, CanvaOAuthCredential: { ...schema.$defs.CanvaOAuthCredential, 'x-credential-hidden': false } } };
        expect(requirementsFromSchema(reviewed, () => true).map((r) => r.credential_type)).toEqual(['canva_oauth', 'canva_mcp']);
        expect(wayInRank({ credential_type: 'x_oauth', method_kind: 'oauth', requires_custom_client: false, preview: true })).toBeGreaterThan(
            wayInRank({ credential_type: 'x_mcp', method_kind: 'mcp', requires_custom_client: false })
        );
    });
});
