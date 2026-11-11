import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-google-cloud-natural-language']));
it('discovers a manual API key and all document analysis operations', () => {
    const type = 'automation-google-cloud-natural-language';
    expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['google_cloud_natural_language_api_key']);
    expect(credentialRequirements(type).map(methodFromRequirement).map(method => method.method_kind)).toEqual(['api_key']);
    const operations = getAgentToolOperations(type).map(op => op.operation);
    expect(operations).toHaveLength(15);
    expect(operations).toContain('analyze_entity_sentiment_from_storage');
    expect(operations).toContain('annotate_text');
});
