// @vitest-environment happy-dom
// A list setting's rows whose values a read held back (a request's secret headers): the rows editor says each is saved
// and hidden, as a secret field does, rather than drawing an empty box that reads as lost.
import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { KeyValueEditor } from './KeyValueEditor';
import { WITHHELD_PLACEHOLDER, withheldRows } from './withheld';

afterEach(cleanup);

describe('withheld rows', () => {
    it('are the rows of that setting a read named', () => {
        expect(withheldRows(['headers[0].value', 'headers[2].value', 'query[1].value', 'api_key'], 'headers')).toEqual([0, 2]);
        expect(withheldRows(['headers[0].value'], 'query')).toEqual([]);
        expect(withheldRows(undefined, 'headers')).toEqual([]);
    });

    it('say a held-back value is saved and hidden until something is typed in its place', () => {
        let rows: unknown = [
            { key: 'Authorization', enabled: true },
            { key: 'Accept', value: 'application/json', enabled: true },
        ];
        const view = render(<KeyValueEditor fieldKey="headers" value={rows} onChange={(next) => (rows = next)} withheldRows={[0]} />);
        const values = () => [...view.container.querySelectorAll('input, textarea')].filter((el) => !el.getAttribute('placeholder')?.includes('Header'));
        const placeholders = () => values().map((el) => el.getAttribute('placeholder'));
        expect(placeholders()).toEqual([WITHHELD_PLACEHOLDER, '{{node.field}} or value']);
        // Typed over: the new value is what's there.
        fireEvent.change(values()[0], { target: { value: 'Bearer new' } });
        view.rerender(<KeyValueEditor fieldKey="headers" value={rows} onChange={(next) => (rows = next)} withheldRows={[0]} />);
        expect(placeholders()[0]).not.toBe(WITHHELD_PLACEHOLDER);
    });
});
