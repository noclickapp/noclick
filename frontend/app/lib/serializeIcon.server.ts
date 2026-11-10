import { createElement, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

/** An icon as markup a page injects (SerializedIcon): without the image preload hint React's server renderer writes
 *  before every <img> (injected into a page's body, it fetched every icon a catalog lists, on screen or not: 1,188
 *  files on Connections), and with its images loading as they come into view. */
export function serializeIcon(Icon: ComponentType): string {
    return renderToStaticMarkup(createElement(Icon))
        .replace(/<link\b[^>]*\brel="preload"[^>]*>/g, '')
        .replace(/<img\b(?![^>]*\bloading=)/g, '<img loading="lazy" decoding="async"');
}
