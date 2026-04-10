// Tests for the shared applyNodeUpdate function.
// Verifies: operation is top-level (NOT in config), config merging, null cleanup.

import { nc } from '~/lib/nc';
import { applyNodeUpdate } from '~/lib/applyNodeUpdate';

export default async function () {
  const results: Record<string, any> = {};

  const mockNode = (data: Record<string, any>) => ({
    id: 'test',
    type: 'automation-excel',
    position: { x: 0, y: 0 },
    data,
  });

  // Test 1: operation from config is extracted to top-level and stripped from config
  {
    const node = mockNode({ label: 'Test', config: {} });
    const updated = applyNodeUpdate(node, {
      config: { operation: 'add_table_row', workbook_id: 'WB1' },
    });
    results['op_extracted_from_config'] = {
      operation: updated.data.operation,
      configHasOperation: 'operation' in ((updated.data as any).config || {}),
      configHasWorkbook: 'workbook_id' in ((updated.data as any).config || {}),
      pass: updated.data.operation === 'add_table_row' &&
            !('operation' in ((updated.data as any).config || {})) &&
            (updated.data as any).config?.workbook_id === 'WB1',
    };
  }

  // Test 2: explicit operation overrides config.operation
  {
    const node = mockNode({ label: 'Test', operation: 'old_op', config: {} });
    const updated = applyNodeUpdate(node, {
      operation: 'new_op',
      config: { workbook_id: 'WB1' },
    });
    results['explicit_op_overrides'] = {
      operation: updated.data.operation,
      configHasOperation: 'operation' in ((updated.data as any).config || {}),
      pass: updated.data.operation === 'new_op' &&
            !('operation' in ((updated.data as any).config || {})),
    };
  }

  // Test 3: stale operation in config is cleaned up
  {
    const node = mockNode({
      label: 'Test',
      operation: 'create_session',
      config: { operation: 'create_session', workbook_id: 'old' },
    });
    const updated = applyNodeUpdate(node, {
      config: { operation: 'add_table_row', workbook_id: 'new' },
    });
    results['stale_op_cleaned'] = {
      operation: updated.data.operation,
      configHasOperation: 'operation' in ((updated.data as any).config || {}),
      pass: updated.data.operation === 'add_table_row' &&
            !('operation' in ((updated.data as any).config || {})),
    };
  }

  // Test 4: null cleanup in config removes the key from data.config
  {
    const node = mockNode({
      label: 'Test',
      config: { workbook_id: 'WB1', sheet_name: 'Sheet1' },
    });
    const updated = applyNodeUpdate(node, {
      config: { workbook_id: null },
    });
    results['null_cleanup'] = {
      hasWorkbook: 'workbook_id' in ((updated.data as any).config || {}),
      hasSheetName: 'sheet_name' in ((updated.data as any).config || {}),
      pass: !('workbook_id' in ((updated.data as any).config || {})) &&
            (updated.data as any).config?.sheet_name === 'Sheet1',
    };
  }

  // Test 5: preserves existing data not in update
  {
    const node = mockNode({
      label: 'Test',
      goal: 'Original goal',
      customField: 'keep me',
      config: { someField: 'keep' },
    });
    const updated = applyNodeUpdate(node, {
      config: { newField: 'added' },
    });
    results['preserves_existing'] = {
      label: updated.data.label,
      customField: (updated.data as any).customField,
      configSomeField: (updated.data as any).config?.someField,
      configNewField: (updated.data as any).config?.newField,
      pass: updated.data.label === 'Test' &&
            (updated.data as any).customField === 'keep me' &&
            (updated.data as any).config?.someField === 'keep' &&
            (updated.data as any).config?.newField === 'added',
    };
  }

  // Test 6: operation stays null when not provided
  {
    const node = mockNode({ label: 'Test', config: {} });
    const updated = applyNodeUpdate(node, {
      config: { workbook_id: 'WB1' },
    });
    results['no_op_stays_null'] = {
      hasOperation: 'operation' in (updated.data as any) && updated.data.operation != null,
      pass: !updated.data.operation,
    };
  }

  const allPass = Object.values(results).every((r: any) => r.pass);
  return { allPass, results };
}
