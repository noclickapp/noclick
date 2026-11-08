// Verifies EODHD credential discovery and its published read operations.
// Guards the generated metadata used by manual connect and agent tools.
import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
    loadNodeSchemas,
    getNodeCredentialInfo,
    getAgentToolOperations,
} from '~/utils/nodeSchemas';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';

const schema = JSON.parse(
    readFileSync(
        join(__dirname, '../../app/schemas/nodes/eodhd-apis.json'),
        'utf8'
    )
);

describe('EODHD API integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-eodhd-apis']));
    it('offers a manually pasted API token', () => {
        expect(
            getNodeCredentialInfo('automation-eodhd-apis')?.acceptedTypes
        ).toEqual(['eodhd_apis_api_token']);
        expect(getNodeCredentialInfo('automation-eodhd-apis')?.label).toBe(
            'EODHD API Token'
        );
        expect(
            methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind
        ).toBe('api_key');
    });
    it('exposes the 18 read operations', () => {
        const ops = getAgentToolOperations('automation-eodhd-apis').map(
            (op) => op.operation
        );
        expect(ops).toHaveLength(18);
        expect(ops).toContain('get_user');
        expect(ops).toContain('get_dividends_calendar');
    });
});
