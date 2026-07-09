// E2E check for connect-time harness API-key validation (feat/harness-provider-errors):
// sends credential:create through the real local socket → backend handler → live
// Anthropic probe, and asserts the definitive rejection comes back on the same
// response the credential form renders. Uses a syntactically-plausible but fake
// key (401 invalid_key path) so no real secret lives in the repo.

import { nc } from '~/lib/nc';
import { sendEventAsync } from '~/lib/socket-sender';

export default async function () {
    const response = await sendEventAsync({
        event_name: 'credential:create',
        request_id: `nc-test-key-validation-${Date.now()}`,
        name: 'nc-test-dead-key (delete me)',
        credential_type: 'agent_claude_code',
        credential_data: {
            credentials: {
                ANTHROPIC_API_KEY:
                    'sk-ant-api03-DEADBEEFdeadbeefDEADBEEFdeadbeefDEADBEEFdeadbeefDEADBEEFdeadbeefDEADBEEFdeadbeefDEADBEEF-deadAA',
            },
        },
        metadata: { provider: 'claude-code' },
    });

    // Must be rejected, not created.
    nc.assert.equal(Boolean(response?.credential), false, 'credential must not be created');
    const error: string = response?.error || response?.message || '';
    nc.assert.truthy(error.length > 0, 'rejection must ride the response error');
    nc.assert.truthy(
        error.includes('rejected the API key'),
        `expected invalid_key rewrite, got: ${error.slice(0, 200)}`,
    );
    nc.assert.truthy(
        error.includes('Provider message:'),
        'provider verbatim detail must ride along',
    );
    return { rejected: true, error: error.slice(0, 300) };
}
