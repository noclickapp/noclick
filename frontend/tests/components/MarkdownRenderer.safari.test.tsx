// @vitest-environment jsdom
//
// Safari before 16.4 has no regex lookbehind. The production build rewrites a
// lookbehind literal into `new RegExp(...)`, which throws at render time there,
// and the root ErrorBoundary takes the whole page. mdast-util-gfm-autolink-literal
// 2.0.1 uses one on every GFM parse, so the chat crashed on iOS 15 (2026-10-20)
// and the package is pinned to 2.0.0 in package.json overrides.

import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { MarkdownRenderer } from '~/components/chat/MarkdownRenderer';

afterEach(cleanup);

const LOOKBEHIND = /\(\?<[=!]/;

/** The autolink-literal source remark-gfm actually loads (resolved through its own deps). */
function resolvedAutolinkSource(): string {
  const fromGfm = createRequire(createRequire(import.meta.url).resolve('remark-gfm'));
  const fromMdastGfm = createRequire(fromGfm.resolve('mdast-util-gfm'));
  const entry = fromMdastGfm.resolve('mdast-util-gfm-autolink-literal');
  return readFileSync(entry.replace(/index\.js$/, 'lib/index.js'), 'utf8');
}

describe('MarkdownRenderer on Safari < 16.4', () => {
  it('ships a GFM autolink parser without regex lookbehind', () => {
    expect(resolvedAutolinkSource()).not.toMatch(LOOKBEHIND);
  });

  it('still autolinks emails, www and https URLs', () => {
    const { container } = render(
      <MarkdownRenderer content={'Mail a.b@example.com or open www.noclick.com and https://docs.noclick.com/x'} />,
    );
    const hrefs = Array.from(container.querySelectorAll('a')).map(a => a.getAttribute('href'));
    expect(hrefs).toEqual(
      expect.arrayContaining(['mailto:a.b@example.com', 'http://www.noclick.com', 'https://docs.noclick.com/x']),
    );
  });
});
