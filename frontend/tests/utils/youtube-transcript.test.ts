// Verifies discovery of the YouTube Transcript operations and pasted API-key method.
// Guards the generated credential aliases used by manual connection forms.
import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/youtube-transcript.json'), 'utf8'));

describe('YouTube Transcript integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-youtube-transcript']));
    it('discovers the human API key label and manual connect method', () => {
        expect(getNodeCredentialInfo('automation-youtube-transcript')?.acceptedTypes).toEqual(['youtube_transcript_api_key']);
        expect(getNodeCredentialInfo('automation-youtube-transcript')?.label).toBe('YouTube Transcript API Key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getCredentialTypeFromSchemaTitle('YoutubeTranscriptAPIKeyCredential')).toBe('youtube_transcript_api_key');
        expect(getCredentialTypeFromSchemaTitle('YouTube Transcript API Key')).toBe('youtube_transcript_api_key');
    });
    it('discovers all 25 provider operations including reads and writes', () => {
        const operations = getAgentToolOperations('automation-youtube-transcript').map(op => op.operation);
        expect(operations).toHaveLength(25);
        expect(operations).toEqual(expect.arrayContaining(['transcribe_video', 'list_transcripts', 'translate_transcript', 'create_folder', 'remove_folder_videos']));
    });
});
