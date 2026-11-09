import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/rawg-video-games-database.json'), 'utf8'));

describe('RAWG Video Games Database integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-rawg-video-games-database']));
    it('offers a manually pasted API key', () => {
        expect(getNodeCredentialInfo('automation-rawg-video-games-database')?.acceptedTypes).toEqual(['rawg_video_games_database_api_key']);
        expect(getNodeCredentialInfo('automation-rawg-video-games-database')?.label).toBe('RAWG API Key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getCredentialTypeFromSchemaTitle('RawgAPIKeyCredential')).toBe('rawg_video_games_database_api_key');
        expect(getCredentialTypeFromSchemaTitle('RAWG API Key')).toBe('rawg_video_games_database_api_key');
    });
    it('exposes twenty-four published read operations', () => {
        expect(getAgentToolOperations('automation-rawg-video-games-database')).toHaveLength(24);
    });
});
