import { beforeAll, describe, expect, it } from 'vitest';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-microsoft-onenote', 'automation-outlook']));

describe('Microsoft OneNote shared OAuth provider', () => {
    it('reads OneNote credentials alongside the existing Microsoft provider declaration', () => {
        expect(getNodeCredentialInfo('automation-microsoft-onenote')).toMatchObject({
            providerKey: 'microsoft',
            acceptedTypes: ['microsoft_oauth'],
            label: 'Microsoft Account',
        });
        expect(getNodeCredentialInfo('automation-outlook')).toMatchObject({
            providerKey: 'microsoft',
            label: 'Microsoft Account',
        });
    });
});
