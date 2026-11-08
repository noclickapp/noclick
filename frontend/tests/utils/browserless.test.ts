// Check that Browserless is discoverable with a manual token connection.
// These checks pin the operation inventory and prevent an unsupported OAuth flow.
import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/browserless.json'), 'utf8'));

describe('Browserless integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-browserless']));
    it('offers a pasted API token', () => {
        expect(getNodeCredentialInfo('automation-browserless')?.acceptedTypes).toEqual(['browserless_token']);
        expect(requirementsFromSchema(schema).map(methodFromRequirement)).toEqual([
            expect.objectContaining({ method_kind: 'api_key', is_oauth: false }),
        ]);
    });
    it('exposes the contracted reads and writes', () => {
        const operations = getAgentToolOperations('automation-browserless').map(op => op.operation);
        expect(operations).toHaveLength(16);
        expect(operations).toEqual(expect.arrayContaining([
            'take_screenshot', 'generate_pdf', 'scrape_elements', 'start_crawl',
            'list_profiles', 'rename_profile', 'delete_profile', 'create_session',
        ]));
    });
});
