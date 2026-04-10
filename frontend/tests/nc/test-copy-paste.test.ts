// Test: verify copy-paste preserves operation and config fields.

import { nc } from '~/lib/nc';
import { buildSaveConfig } from '~/lib/applyNodeUpdate';
import { noClickParser } from '~/utils/clipboard-parsers/noclick-parser';

export default async function () {
  const results: Record<string, any> = {};

  // Simulate a clipboard blob like buildSaveConfig would produce
  const clipboardData = {
    type: 'noclick-workflow',
    version: '1.0',
    nodes: [{
      id: 'original_sheets',
      type: 'automation-google-sheets',
      position: { x: 100, y: 100 },
      config: {
        operation: 'append',
        label: 'Save to Sheets',
        goal: 'Append rows',
        spreadsheet_id: 'abc123',
        sheet_name: 'Sheet1',
        range: 'A:D',
        values: '["{{name}}", "{{email}}"]',
        credentialIds: { google_sheets_oauth: 'cred-uuid' },
      },
    }],
    edges: [],
  };

  // Parse it like the clipboard parser would
  const parsed = noClickParser.parse(JSON.stringify(clipboardData));

  if (!parsed || parsed.nodes.length === 0) {
    return { error: 'Parser returned no nodes' };
  }

  const pastedNode = parsed.nodes[0];
  const data = pastedNode.data as Record<string, any>;

  results['has_operation'] = {
    operation: data.operation,
    pass: data.operation === 'append',
  };

  results['has_config'] = {
    configKeys: Object.keys(data.config || {}),
    pass: !!data.config && Object.keys(data.config).length > 0,
  };

  results['config_has_fields'] = {
    spreadsheet_id: data.config?.spreadsheet_id,
    sheet_name: data.config?.sheet_name,
    pass: data.config?.spreadsheet_id === 'abc123' && data.config?.sheet_name === 'Sheet1',
  };

  results['operation_not_in_config'] = {
    configHasOperation: 'operation' in (data.config || {}),
    pass: !('operation' in (data.config || {})),
  };

  // Config fields MUST live in data.config (not flat on data)
  results['no_flat_config_fields'] = {
    flatSpreadsheetId: data.spreadsheet_id,
    pass: data.spreadsheet_id === undefined,
  };

  // Now test buildSaveConfig on the pasted node
  const saveConfig = buildSaveConfig(pastedNode as any);
  results['save_config_round_trip'] = {
    hasOperation: 'operation' in saveConfig,
    operation: saveConfig.operation,
    hasSpreadsheetId: 'spreadsheet_id' in saveConfig,
    pass: saveConfig.operation === 'append' && saveConfig.spreadsheet_id === 'abc123',
  };

  const allPass = Object.values(results).every((r: any) => r.pass);
  return { allPass, results };
}
