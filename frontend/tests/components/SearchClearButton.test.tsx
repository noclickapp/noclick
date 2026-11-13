// @vitest-environment happy-dom
// A search box clears with the app's own ✕, never the browser's: the shared button shows only while the box holds text,
// clears it and hands focus back, and tailwind.css hides WebKit's blue cancel button on every `type="search"` box.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { useRef, useState } from 'react';
import postcss from 'postcss';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { SearchClearButton } from '~/components/ui/SearchClearButton';

afterEach(cleanup);

function Box() {
    const [value, setValue] = useState('');
    const ref = useRef<HTMLInputElement>(null);
    return (
        <label>
            <input ref={ref} type="search" aria-label="Search apps" value={value} onChange={(e) => setValue(e.target.value)} />
            <SearchClearButton value={value} onClear={() => setValue('')} inputRef={ref} />
        </label>
    );
}

describe('SearchClearButton', () => {
    it('shows only while the box holds text, clears it and hands focus back', () => {
        render(<Box />);
        const box = screen.getByRole<HTMLInputElement>('searchbox', { name: 'Search apps' });
        expect(screen.queryByRole('button', { name: 'Clear search' })).toBeNull();

        fireEvent.change(box, { target: { value: 'wde' } });
        const clear = screen.getByRole('button', { name: 'Clear search' });
        // A muted ✕ on a round wash, in the theme's tokens.
        expect(clear.className).toContain('rounded-full');
        expect(clear.className).toContain('text-muted-foreground');
        expect(clear.className).toContain('hover:bg-foreground/[0.06]');
        // The press never takes focus from the box.
        expect(fireEvent.mouseDown(clear)).toBe(false);

        box.blur();
        fireEvent.click(clear);
        expect(box.value).toBe('');
        expect(document.activeElement).toBe(box);
        expect(screen.queryByRole('button', { name: 'Clear search' })).toBeNull();
    });
});

describe('the browser’s own search ✕', () => {
    it('is hidden on every search box', () => {
        const css = readFileSync(join(__dirname, '../../app/tailwind.css'), 'utf8');
        const hidden = new Set<string>();
        postcss.parse(css).walkRules((rule) => {
            const none = rule.nodes.some((d) => d.type === 'decl' && d.prop === '-webkit-appearance' && d.value === 'none');
            if (none) rule.selectors.forEach((s) => hidden.add(s.replace(/"/g, "'")));
        });
        for (const part of ['cancel-button', 'decoration', 'results-button', 'results-decoration']) {
            expect(hidden).toContain(`input[type='search']::-webkit-search-${part}`);
        }
    });
});
