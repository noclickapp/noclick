// @vitest-environment jsdom
//
// Tests for usage-based (credential-optional) billing detection in the pure
// credential helpers — added with the Exa platform-key path so the config
// panel shows the agent-style "credential-free operation available" UI (BYOK picker
// kept) instead of hiding credentials, in both single-op and tool-provider
// (agent_tool_operations allowlist) modes.

import { describe, expect, it } from 'vitest';

const { hasUnconnectedCredentials, providerCredentialsMissing, isUsageBasedBillingAvailable } =
    await import('~/components/workflow/NodeCredentials');

const EXA = 'automation-exa';
const PPLX = 'automation-perplexity';

const singleOp = (operation: string) => ({ operation, config: { operation } });
const provider = (ops: unknown[]) => ({ config: { agent_tool_operations: ops } });

describe('isUsageBasedBillingAvailable — single-op mode', () => {
    it('is available for every platform-metered Exa search op', () => {
        for (const op of ['search', 'get_contents', 'answer', 'find_similar']) {
            expect(isUsageBasedBillingAvailable(EXA, singleOp(op)), op).toBe(true);
        }
    });

    it('is not available for BYOK-only ops (websets, monitors, agent runs)', () => {
        for (const op of ['create_webset', 'create_monitor', 'create_agent_run']) {
            expect(isUsageBasedBillingAvailable(EXA, singleOp(op)), op).toBe(false);
        }
    });

    it('covers perplexity metered ops, excludes async/account ops', () => {
        for (const op of ['chat_completion', 'search', 'academic_search', 'sec_search', 'structured_output']) {
            expect(isUsageBasedBillingAvailable(PPLX, singleOp(op)), op).toBe(true);
        }
        for (const op of ['create_async_completion', 'create_embeddings', 'usage_analytics']) {
            expect(isUsageBasedBillingAvailable(PPLX, singleOp(op)), op).toBe(false);
        }
    });
});

describe('isUsageBasedBillingAvailable — tool-provider mode', () => {
    it('is available when every allowlisted op is credentials-optional', () => {
        expect(isUsageBasedBillingAvailable(EXA, provider(['search', 'answer']))).toBe(true);
    });

    it('handles resource-scoped {operation} entries', () => {
        expect(isUsageBasedBillingAvailable(EXA, provider([{ operation: 'search' }]))).toBe(true);
    });

    it('is not available when any allowlisted op requires credentials', () => {
        expect(isUsageBasedBillingAvailable(EXA, provider(['search', 'create_monitor']))).toBe(false);
    });

    it('provider verdict wins over a lingering optional single-op selection', () => {
        expect(
            isUsageBasedBillingAvailable(EXA, {
                operation: 'search',
                config: { operation: 'search', agent_tool_operations: ['search', 'create_monitor'] },
            })
        ).toBe(false);
    });
});

describe('validation stays consistent with the UI', () => {
    it('hasUnconnectedCredentials passes optional ops, flags required ones', () => {
        expect(hasUnconnectedCredentials(EXA, {}, singleOp('search'))).toBe(false);
        expect(hasUnconnectedCredentials(EXA, {}, singleOp('create_webset'))).toBe(true);
    });

    it('providerCredentialsMissing passes an all-optional allowlist without credentials', () => {
        expect(providerCredentialsMissing(EXA, {}, provider(['search', 'get_contents']))).toBe(false);
        expect(providerCredentialsMissing(EXA, {}, provider(['search', 'create_monitor']))).toBe(true);
    });

    it('a lingering optional single-op cannot wave a required allowlist through', () => {
        // Provider-wired exa keeps its pre-wiring operation ('search', optional);
        // the allowlist has a credential-requiring op — must still flag missing.
        expect(
            providerCredentialsMissing(EXA, {}, {
                operation: 'search',
                config: { operation: 'search', agent_tool_operations: ['search', 'create_monitor'] },
            })
        ).toBe(true);
    });
});
