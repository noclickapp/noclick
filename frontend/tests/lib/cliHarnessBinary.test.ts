// The self-hosted credentials panel tells the user which CLI to sign in to.
// Two harnesses have a model id that differs from their executable, so naming
// the model would send people to a command that doesn't exist.

import { describe, it, expect } from 'vitest';
import { cliHarnessBinary, isCliAgentModel, CLI_MODEL_PROVIDER } from '~/lib/agentChat';

describe('cliHarnessBinary', () => {
    it('names the executable, not the model id, where they differ', () => {
        expect(cliHarnessBinary('claude-code')).toBe('claude');
        expect(cliHarnessBinary('hermes')).toBe('hermes');
    });

    it('passes through where they match', () => {
        expect(cliHarnessBinary('codex')).toBe('codex');
        expect(cliHarnessBinary('opencode')).toBe('opencode');
        expect(cliHarnessBinary('openclaw')).toBe('openclaw');
    });

    it('covers every CLI harness, so no model renders a blank command', () => {
        for (const model of Object.keys(CLI_MODEL_PROVIDER)) {
            expect(isCliAgentModel(model)).toBe(true);
            expect(cliHarnessBinary(model)).not.toBe('the CLI');
        }
    });

    it('degrades to a readable phrase for anything else', () => {
        expect(cliHarnessBinary(undefined)).toBe('the CLI');
        expect(cliHarnessBinary('gpt-4o')).toBe('the CLI');
    });
});
