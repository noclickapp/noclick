// Tests for filterConfigForExecution utility
// Verifies that node configs are correctly filtered to only include fields for the selected operation
// when sending execution requests to the backend.

import { describe, it, expect } from 'vitest';
import { filterConfigForExecution } from '~/utils/nodeSchemas';

describe('filterConfigForExecution', () => {
    describe('nodes without discriminated unions', () => {
        it('returns config unchanged for unknown node types', () => {
            const config = { field1: 'value1', field2: 'value2' };
            const result = filterConfigForExecution('unknown-node', config);
            expect(result).toEqual(config);
        });

        it('returns config unchanged when nodeType is undefined', () => {
            const config = { field1: 'value1' };
            const result = filterConfigForExecution(undefined, config);
            expect(result).toEqual(config);
        });

        it('returns config unchanged for nodes without anyOf/oneOf', () => {
            // Agent node has a simple schema without discriminated unions
            const config = {
                system_prompt: 'You are helpful',
                model: 'claude-3-sonnet',
                credentialIds: { anthropic_api_key: 'cred-123' }
            };
            const result = filterConfigForExecution('agent', config);
            expect(result).toEqual(config);
        });
    });

    describe('nodes with discriminated unions (Google Sheets)', () => {
        it('filters config to only include read operation fields', () => {
            const config = {
                operation: 'read_sheet_data',
                spreadsheet_id: 'sheet-123',
                sheet_name: 'Sheet1',
                range: 'A1:D10',
                // Stale fields from write/append operations:
                values: '[[\"data\"]]',
                // Metadata fields that should be preserved
                credentialIds: { google_sheets_oauth: 'cred-456' },
                configValid: true,
                label: 'Read Spreadsheet',
                goal: 'Fetch data from Google Sheets',
                disabled: false,
                mockedOutput: { rows: [[1, 2, 3]] }
            };

            const result = filterConfigForExecution('automation-google-sheets', config);

            // Should keep: operation, spreadsheet_id, sheet_name, range (read fields)
            // Should keep: all metadata fields (non-schema fields)
            // Should drop: values (write/append only field)
            expect(result).toEqual({
                operation: 'read_sheet_data',
                spreadsheet_id: 'sheet-123',
                sheet_name: 'Sheet1',
                range: 'A1:D10',
                credentialIds: { google_sheets_oauth: 'cred-456' },
                configValid: true,
                label: 'Read Spreadsheet',
                goal: 'Fetch data from Google Sheets',
                disabled: false,
                mockedOutput: { rows: [[1, 2, 3]] }
            });
            expect(result.values).toBeUndefined();
        });

        it('filters config to only include write operation fields', () => {
            const config = {
                operation: 'write_sheet_data',
                spreadsheet_id: 'sheet-123',
                sheet_name: 'Sheet1',
                range: 'A1',
                values: '[[\"Name\", \"Email\"]]',
                credentialIds: { google_sheets_oauth: 'cred-456' },
                configValid: false,
                label: 'Write to Sheet',
                goal: 'Update spreadsheet data',
                disabled: false,
                mockedOutput: null
            };

            const result = filterConfigForExecution('automation-google-sheets', config);

            // Write operation has: operation, spreadsheet_id, sheet_name, range, values
            expect(result).toEqual({
                operation: 'write_sheet_data',
                spreadsheet_id: 'sheet-123',
                sheet_name: 'Sheet1',
                range: 'A1',
                values: '[[\"Name\", \"Email\"]]',
                credentialIds: { google_sheets_oauth: 'cred-456' },
                configValid: false,
                label: 'Write to Sheet',
                goal: 'Update spreadsheet data',
                disabled: false,
                mockedOutput: null
            });
        });

        it('filters config to only include append operation fields', () => {
            const config = {
                operation: 'append_rows_to_sheet',
                spreadsheet_id: 'sheet-123',
                sheet_name: 'Sheet1',
                range: 'A:D',
                values: '[[\"John\", \"john@example.com\"]]',
                // Stale field that doesn't belong to any operation
                some_random_field: 'should be dropped if it is a schema field',
                credentialIds: { google_sheets_oauth: 'cred-456' },
                configValid: true,
                label: 'Append Row',
                goal: 'Add new data to sheet',
                disabled: true,
                mockedOutput: { success: true }
            };

            const result = filterConfigForExecution('automation-google-sheets', config);

            expect(result.operation).toBe('append_rows_to_sheet');
            expect(result.spreadsheet_id).toBe('sheet-123');
            expect(result.values).toBe('[[\"John\", \"john@example.com\"]]');
            expect(result.credentialIds).toEqual({ google_sheets_oauth: 'cred-456' });
            expect(result.configValid).toBe(true);
            expect(result.label).toBe('Append Row');
            expect(result.goal).toBe('Add new data to sheet');
            expect(result.disabled).toBe(true);
            expect(result.mockedOutput).toEqual({ success: true });
        });
    });

    describe('preserves non-schema fields', () => {
        it('preserves all metadata fields regardless of operation', () => {
            const config = {
                operation: 'read_sheet_data',
                spreadsheet_id: 'sheet-123',
                credentialIds: { google_sheets_oauth: 'cred-456' },
                configValid: true,
                label: 'My Node',
                goal: 'Process data',
                disabled: false,
                mockedOutput: { data: [[1, 2, 3]] },
                someCustomField: 'custom-value'
            };

            const result = filterConfigForExecution('automation-google-sheets', config);

            expect(result.credentialIds).toEqual({ google_sheets_oauth: 'cred-456' });
            expect(result.configValid).toBe(true);
            expect(result.label).toBe('My Node');
            expect(result.goal).toBe('Process data');
            expect(result.disabled).toBe(false);
            expect(result.mockedOutput).toEqual({ data: [[1, 2, 3]] });
            expect(result.someCustomField).toBe('custom-value');
        });
    });

    describe('handles edge cases', () => {
        it('returns config unchanged when discriminator value is missing', () => {
            const config = {
                spreadsheet_id: 'sheet-123',
                range: 'A1:D10',
                values: '[[\"data\"]]',
                credentialIds: { google_sheets_oauth: 'cred-456' }
                // Missing operation field
            };

            const result = filterConfigForExecution('automation-google-sheets', config);

            // Should return unchanged since no discriminator to determine operation
            expect(result).toEqual(config);
        });

        it('returns config unchanged when discriminator value is invalid', () => {
            const config = {
                operation: 'invalid_operation',
                spreadsheet_id: 'sheet-123',
                credentialIds: { google_sheets_oauth: 'cred-456' }
            };

            const result = filterConfigForExecution('automation-google-sheets', config);

            // Should return unchanged since discriminator value doesn't match any option
            expect(result).toEqual(config);
        });

        it('handles empty config', () => {
            const result = filterConfigForExecution('automation-google-sheets', {});
            expect(result).toEqual({});
        });

        it('returns null config as-is', () => {
            const result = filterConfigForExecution('automation-google-sheets', null as any);
            expect(result).toBeNull();
        });

        it('returns undefined config as-is', () => {
            const result = filterConfigForExecution('automation-google-sheets', undefined as any);
            expect(result).toBeUndefined();
        });
    });

    describe('Gmail node (another discriminated union)', () => {
        it('filters config for send operation', () => {
            const config = {
                operation: 'send_email_message',
                to: 'test@example.com',
                subject: 'Test Subject',
                body: 'Test body',
                // Stale fields from other operations
                query: 'from:someone@example.com',
                max_results: 10,
                credentialIds: { gmail_oauth: 'cred-789' }
            };

            const result = filterConfigForExecution('automation-gmail', config);

            // Should keep send operation fields
            expect(result.operation).toBe('send_email_message');
            expect(result.to).toBe('test@example.com');
            expect(result.subject).toBe('Test Subject');
            expect(result.body).toBe('Test body');
            expect(result.credentialIds).toEqual({ gmail_oauth: 'cred-789' });

            // Should drop search-only fields
            expect(result.query).toBeUndefined();
            expect(result.max_results).toBeUndefined();
        });
    });
});
