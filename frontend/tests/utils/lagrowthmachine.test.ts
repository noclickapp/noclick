// Verifies the generated integration metadata through the real frontend consumers.
// API keys must render as pasted credentials and expose the complete operation set.
import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/lagrowthmachine.json';

describe('lagrowthmachine integration metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-lagrowthmachine']));
    it('offers an API key with the reviewed provider label', () => {
        expect(getNodeCredentialInfo('automation-lagrowthmachine')?.acceptedTypes).toEqual(['lagrowthmachine_api_key']);
        expect(getNodeCredentialInfo('automation-lagrowthmachine')?.label).toBe('La Growth Machine API Key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getCredentialTypeFromSchemaTitle('La Growth Machine API Key')).toBe('lagrowthmachine_api_key');
        expect(getCredentialTypeFromSchemaTitle('LagrowthmachineAPIKeyCredential')).toBe('lagrowthmachine_api_key');
    });
    it('offers account reads, lead writes and outreach replies', () => {
        const operations = getAgentToolOperations('automation-lagrowthmachine').map(op => op.operation);
        expect(operations).toHaveLength(20);
        expect(operations).toEqual(expect.arrayContaining(['get_me', 'upsert_lead', 'create_audience', 'list_campaigns', 'reply_email', 'send_linkedin_message']));
    });
});
