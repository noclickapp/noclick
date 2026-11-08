// Verifies Coinbase Exchange metadata reaches the shared credential and tool consumers.
// This protects manual connection fields and the operation catalog as discovery evolves.
import { beforeAll, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { getNodeCredentialInfo, getAgentToolOperations, loadNodeSchemas } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/coinbase.json'), 'utf8'));

describe('Coinbase Exchange integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-coinbase']));
    it('discovers a manual API key method with all three user fields', () => {
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.credential_fields?.map(field => field.name)).toEqual(['api_key', 'api_secret', 'passphrase']);
        expect(getNodeCredentialInfo('automation-coinbase')?.acceptedTypes).toEqual(['coinbase_exchange_api_key']);
        expect(getNodeCredentialInfo('automation-coinbase')?.label).toBe('Coinbase Exchange API Key');
    });
    it('exposes the 20 contract operations, including limit order creation and cancellation', () => {
        const operations = getAgentToolOperations('automation-coinbase').map(op => op.operation);
        expect(operations).toHaveLength(20);
        expect(operations).toEqual(expect.arrayContaining(['list_accounts', 'create_order', 'cancel_order', 'get_ticker']));
    });
});
