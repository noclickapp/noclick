import { describe, expect, it } from 'vitest';

import {
    STRUCTURAL_AGENT_TOOL_TYPES,
    canFeedAgentBottom,
    getAgentWirableCatalog,
} from '~/utils/nodeSchemas';

describe('structural agent-tool providers', () => {
    it('keeps the NoClick MCP provider in the same bottom-handle catalog as other structural tools', () => {
        for (const type of ['tool', 'mcp-server', 'noclick', 'alarm', 'filesystem']) {
            expect(STRUCTURAL_AGENT_TOOL_TYPES.has(type), type).toBe(true);
            expect(canFeedAgentBottom(type), type).toBe(true);
        }
        expect(getAgentWirableCatalog().tools).toContain('noclick');
    });
});
