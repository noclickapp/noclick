// @vitest-environment happy-dom
// Native Vectara wiring and privacy regressions.
// Exercises both selectors, credential schema selection and normal owned auto-selection.
// The exact public logo and closed operation catalog are pinned in the fixture.
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { VectaraNode } from '~/components/workflow/nodes/integrations/vectara';
import {
    AVAILABLE_NODES,
    getSearchableNodes,
} from '~/components/workflow/nodes/nodeRegistry';
import {
    loadNodeSchemas,
    getNodeCredentialInfo,
    getAgentToolOperations,
    filterConfigForExecution,
} from '~/utils/nodeSchemas';
import {
    upsertCredentialsIntoCache,
    removeCredentialsFromCache,
} from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
const fixture = {
  "nodeType": "automation-vectara",
  "credentialType": "vectara_api_key",
  "schemaTitle": "Vectara API Key",
  "operations": [
    "get_corpus",
    "create_corpus",
    "update_corpus",
    "list_documents",
    "get_document",
    "index_document",
    "merge_document_metadata",
    "replace_document_metadata",
    "delete_document",
    "search_corpus",
    "list_corpus_jobs",
    "get_corpus_job"
  ],
  "iconSha256": "fddadeaa32add07c912fac4fb41cc69e43779e35ab9dd18d578668b117b86019"
};

beforeAll(() => loadNodeSchemas([fixture.nodeType]));

afterEach(() =>
    removeCredentialsFromCache([
        'native-vectara-owned',
        'native-vectara-display',
    ])
);
describe('native Vectara', () => {
    it('uses both actual selectors and the closed native operation set', () => {
        expect(
            AVAILABLE_NODES.find((n) => n.type === fixture.nodeType)?.label
        ).toBe('Vectara');
        expect(
            getSearchableNodes().some((n) => n.type === fixture.nodeType)
        ).toBe(true);
        expect(
            getAgentToolOperations(fixture.nodeType)
                .map((o) => o.operation)
                .sort()
        ).toEqual([...fixture.operations].sort());
    });
    it('resolves both credential aliases and actual nullable credential schema', () => {
        expect(
            getCredentialTypeFromSchemaTitle('VectaraAPIKeyCredential')
        ).toBe(fixture.credentialType);
        expect(getCredentialTypeFromSchemaTitle(fixture.schemaTitle)).toBe(
            fixture.credentialType
        );
        expect(
            getCredentialTypeFromSchemaTitle('VectaraClientCredentials')
        ).toBe('vectara_client_credentials');
        expect(getCredentialTypeFromSchemaTitle('Vectara OAuth Client')).toBe(
            'vectara_client_credentials'
        );
        expect(getNodeCredentialInfo(fixture.nodeType)?.acceptedTypes).toEqual([
            fixture.credentialType,
            'vectara_client_credentials',
        ]);
        const method = credentialRequirements(fixture.nodeType).map(methodFromRequirement)
            .find(method => method.credential_type === 'vectara_client_credentials');
        expect(method?.method_kind).toBe('api_key');
        expect(method?.is_oauth).toBe(false);
        expect(method?.credential_fields.map(field => field.name)).toEqual(expect.arrayContaining(['client_id', 'client_secret', 'token_endpoint', 'corpus_key']));
        upsertCredentialsIntoCache([
            {
                id: 'native-vectara-display',
                name: 'Display',
                credential_type: fixture.credentialType,
                owned_by_me: false,
            },
            {
                id: 'native-vectara-owned',
                name: 'Owned',
                credential_type: fixture.credentialType,
                owned_by_me: true,
            },
        ]);
        expect(autoSelectCredentialFromCache(fixture.nodeType)).toEqual({
            [fixture.credentialType]: 'native-vectara-owned',
        });
    });
    it('keeps operation fields and parent without retaining other known action fields', () => {
        const result = filterConfigForExecution(fixture.nodeType, {
            operation: 'get_document',
            corpus_key: 'owned',
            document_id: 'fixture/a',
            text: 'not for this read',
            query: 'not for this read',
            sidecar: 'retained platform metadata',
        });
        expect(result.document_id).toBe('fixture/a');
        expect(result.corpus_key).toBe('owned');
        expect(result.text).toBeUndefined();
        expect(result.query).toBeUndefined();
        expect(result.sidecar).toBe('retained platform metadata');
        expect(JSON.stringify(result)).not.toContain('"api_key":');
    });
    it('renders the exact official icon with contain layout', () => {
        const { container } = render(<VectaraNode.Icon />);
        expect(container.querySelector('img')?.getAttribute('src')).toBe(
            '/icons/vectara.png'
        );
        expect(container.querySelector('img')?.style.objectFit).toBe('contain');
        const asset = readFileSync(resolve('public/icons/vectara.png'));
        expect(createHash('sha256').update(asset).digest('hex')).toBe(
            fixture.iconSha256
        );
    });
});
