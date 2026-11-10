// @vitest-environment happy-dom

// A brand mark with a file for each theme renders both, one shown per theme by the
// `dark` class, and surfaces that draw the file themselves (the workflow preview)
// read the one for their theme out of the serialized markup.
import { cleanup, render } from '@testing-library/react';
import { createRef } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';
import { ThemedBrandImg } from '~/components/shared/ThemedBrandImg';
import { serializedImgSrc } from '~/components/shared/SerializedIcon';
import { NotionNode } from '~/components/workflow/nodes/NotionNode';

afterEach(cleanup);

describe('ThemedBrandImg', () => {
    it('renders one decorative image when the mark reads in both themes', () => {
        const html = renderToStaticMarkup(<ThemedBrandImg light="/icons/a.svg" className="h-6" style={{ width: 24 }} />);
        expect(html.match(/<img[^>]*>/g)).toEqual([
            '<img aria-hidden="true" style="object-fit:contain;width:24px" alt="" src="/icons/a.svg" class="h-6"/>',
        ]);
    });

    it('renders the light file hidden in dark mode and the dark file shown only there', () => {
        const html = renderToStaticMarkup(
            <ThemedBrandImg light="/icons/a.svg" dark="/icons/a-dark.svg" className="h-6" style={{ filter: 'drop-shadow(0 0 1px black)' }} />
        );
        const [light, dark, ...more] = html.match(/<img[^>]*>/g) ?? [];
        expect(more).toEqual([]);
        expect(light).toContain('src="/icons/a.svg"');
        expect(light).toContain('class="h-6 dark:hidden"');
        expect(dark).toContain('src="/icons/a-dark.svg"');
        expect(dark).toContain('class="h-6 hidden dark:block"');
        for (const img of [light, dark]) expect(img).toContain('filter:drop-shadow(0 0 1px black)');
    });

    it('names a mark it is given a name for, and hands its ref to the light image', () => {
        const ref = createRef<HTMLImageElement>();
        render(<ThemedBrandImg ref={ref} light="/icons/a.svg" dark="/icons/a-dark.svg" alt="Cal.com" />);
        expect(ref.current?.getAttribute('src')).toBe('/icons/a.svg');
        expect(ref.current?.getAttribute('alt')).toBe('Cal.com');
        expect(ref.current?.hasAttribute('aria-hidden')).toBe(false);
    });
});

describe('serializedImgSrc', () => {
    const pair = renderToStaticMarkup(<NotionNode.Icon />);

    it('reads the file a pair shows in each theme', () => {
        expect(serializedImgSrc(pair, false)).toBe('/icons/notion-light.svg');
        expect(serializedImgSrc(pair, true)).toBe('/icons/notion.svg');
    });

    it('reads a single image, after any preload, in either theme', () => {
        const one = '<link rel="preload" as="image" href="/icons/a.svg"/><img src="/icons/a.svg" alt=""/>';
        expect(serializedImgSrc(one, false)).toBe('/icons/a.svg');
        expect(serializedImgSrc(one, true)).toBe('/icons/a.svg');
    });

    it('reads nothing from an inline svg', () => {
        expect(serializedImgSrc('<svg viewBox="0 0 24 24"><path d="M0 0h24v24H0z"/></svg>', true)).toBeUndefined();
    });
});
