import { describe, expect, it } from 'vitest';
import { getAvailableOperations, getOptionDisplayName } from '~/utils/operationHelpers';
import { getSchemaInfo } from '~/utils/schemaFieldExtractor';

describe('operation label helpers', () => {
  it('does not surface auto-generated discriminator titles as operation labels', () => {
    const schemaInfo = getSchemaInfo('agent');
    expect(schemaInfo).not.toBeNull();
    const label = getOptionDisplayName(schemaInfo!, 3);
    expect(label).toBe('Codex');
    expect(label).not.toBe('Model Type');
  });

  it('derives meaningful agent operation labels from schema options', () => {
    const operations = getAvailableOperations('agent');
    expect(operations.some((operation) => operation.label === 'Codex')).toBe(true);
    expect(operations.some((operation) => operation.label === 'Claude Code')).toBe(true);
    expect(operations.some((operation) => operation.label === 'Model Type')).toBe(false);
  });
});
