// @vitest-environment jsdom

// Regression: a form "list" field whose stored value holds objects (a
// schedule-shaped object dragged in) used to throw `.trim is not a function`
// during render and take the whole workflow page down to the error screen.

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/hooks/useResourceUpload', () => ({
    useResourceUpload: () => ({ uploadFile: vi.fn(), uploading: false, progress: null }),
}));
vi.mock('~/components/workflow/WorkflowContext', () => ({
    useWorkflowId: () => 'workflow-1',
}));

import { FieldRenderer, normalizeFields } from '~/components/interface/blocks/FieldRenderer';
import { renderSchemaWidget } from '~/components/workflow/schemaWidgetRegistry';

const SCHEDULE_OBJECT = { hour: 9, minute: 0, dayOfWeek: 1, frequency: 'day', dayOfMonth: 1 };
const OBJECT_LIST = [SCHEDULE_OBJECT];

describe('list fields holding non-string items', () => {
    afterEach(cleanup);

    it('renders an interface-form list field with an object-list value as JSON text', () => {
        const [field] = normalizeFields([{ name: 'your_name', type: 'list' }]);
        const onChange = vi.fn();

        expect(() =>
            render(<FieldRenderer field={field} value={OBJECT_LIST} onChange={onChange} />),
        ).not.toThrow();

        const row = screen.getByDisplayValue(JSON.stringify(SCHEDULE_OBJECT));
        expect(onChange).not.toHaveBeenCalled();

        // Editing still works and saves strings.
        fireEvent.change(row, { target: { value: 'Ada' } });
        expect(onChange).toHaveBeenLastCalledWith('your_name', ['Ada']);
    });

    it('renders the node-config list widget with an object-list value as JSON text', () => {
        const widget = renderSchemaWidget({
            fieldKey: 'recipients',
            fieldSchema: { 'ui:widget': 'list' },
            value: OBJECT_LIST,
            onChange: vi.fn(),
        });

        expect(() => render(widget!)).not.toThrow();
        expect(screen.getByDisplayValue(JSON.stringify(SCHEDULE_OBJECT))).toBeTruthy();
    });
});
