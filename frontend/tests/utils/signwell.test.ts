import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/signwell.json'), 'utf8'));

describe('SignWell integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-signwell']));
    it('discovers the pasted API key with its reviewed label', () => {
        expect(getNodeCredentialInfo('automation-signwell')?.acceptedTypes).toEqual(['signwell_api_key']);
        expect(getNodeCredentialInfo('automation-signwell')?.label).toBe('Signwell API Key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getCredentialTypeFromSchemaTitle('Signwell API Key')).toBe('signwell_api_key');
    });
    it('exposes document, template, webhook and bulk send automation', () => {
        const operations = getAgentToolOperations('automation-signwell').map(op => op.operation);
        expect(operations).toHaveLength(22);
        expect(operations).toEqual(expect.arrayContaining(['get_me', 'create_document', 'send_document', 'create_document_from_template', 'get_completed_pdf_url', 'create_template', 'create_webhook', 'get_bulk_send_documents']));
    });
});
