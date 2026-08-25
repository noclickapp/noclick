// @vitest-environment jsdom
// Tests for the CLI-harness → sub-model-field detection helper.
//
// The sidebar shows a sub-model picker only when the selected agent model is
// one of the five CLI harnesses (codex / claude-code / opencode / openclaw /
// hermes). Regular LLM ids must return null so the picker stays hidden.

import { describe, it, expect } from 'vitest';
import { getCliSubModelField } from '~/components/interface/blocks/AgentSubModelPicker';

describe('getCliSubModelField', () => {
  it.each([
    ['codex', 'codex_model', 'Codex Model'],
    ['claude-code', 'claude_code_model', 'Claude Code Model'],
    ['opencode', 'opencode_model', 'OpenCode Model'],
    ['openclaw', 'openclaw_model', 'OpenClaw Model'],
    ['hermes', 'hermes_agent_model', 'Hermes Model'],
  ])('maps "%s" to fieldName=%s label=%s', (model, expectedField, expectedLabel) => {
    const result = getCliSubModelField(model);
    expect(result).not.toBeNull();
    expect(result!.fieldName).toBe(expectedField);
    expect(result!.configKey).toBe(expectedField);
    expect(result!.label).toBe(expectedLabel);
  });

  it('returns null for regular LLM ids', () => {
    expect(getCliSubModelField('openrouter/openai/gpt-4o-mini')).toBeNull();
    expect(getCliSubModelField('openrouter/anthropic/claude-3.5-sonnet')).toBeNull();
    expect(getCliSubModelField('openrouter/google/gemini-2.0-flash')).toBeNull();
  });

  it('returns null for unknown / image / video models', () => {
    expect(getCliSubModelField(undefined)).toBeNull();
    expect(getCliSubModelField('')).toBeNull();
    expect(getCliSubModelField('openrouter/openai/dall-e-3')).toBeNull();
    expect(getCliSubModelField('openrouter/google/veo-2')).toBeNull();
  });
});
