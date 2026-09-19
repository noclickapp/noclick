// Run the nc regression in headless Chromium as part of the browser suite.
// It mounts the real chat hook and checks DOM text through delayed reply events.
import { expect, it } from 'vitest';
import verifyAgentReplies from '../nc/coordinator-agent-replies.test';

it('renders an agent result without interrupting the coordinator', async () => {
    expect((await verifyAgentReplies()).streamingFinished).toBe(true);
});
